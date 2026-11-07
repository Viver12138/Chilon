#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材映射 v7：v6 规则引擎 + 第四批 23 条不一致的最窄规则收敛（只追加规则，不改既有语义/阈值）。

背景（见 docs/textbook_map_v7_2026-11-07.md）：
  - 第四批复核 168 块（20% 抽样）暴露 23 条「v6 错、教师对」的不一致；本版逐条诊断命中层
    （绝大多数是 v3_base：正文关键词选错 + PRI 无规则 + SEC 跳过/候选分不足），
    用「节号 + 窄条件」PRI 规则收敛，**不硬编码 block_id**、不改 v3–v6、不动
    SECTION_KP/SEC_SKIP/MIN_SCORE/FILL_CONF/既有排除词。
  - 新增规则一律**追加在既有 PRIORITY_RULES 之后**：v6 已命中的块语义完全不变，
    新规则只接管 v6 无 PRI 命中（落到 v3_base / SEC / FILL）的块。
  - 规则设计原则（与 v5/v6 一致）：节号先限定命中面；正文特征用 OCR 里稳定的
    “小节标题/定义句/设问模板/标准题干词”；能不带的宽词就不带（如 9.2 百分位数要求
    “百分位数为/第…百分位数”，避免命中 9.2.2 小节标题；10.3 独立性要求“假设…独立的”，
    避免命中复习题里的“事件A与B相互独立吗”）。
  - 反样本守卫（见 eval 的 guard_check）：同节教师已对但含相似字面的块逐条核对过，
    如 3.1 的 0073-3/0080-1（含分段公式但无“解析式为”）、4.5 的 0153-1（正文含
    “用二分法求方程的近似解”但非小节标题）、9.2 的 0209-1（小节标题“总体百分位数的估计”
    但教师=histogram）、10.3 的 0273-2（复习题“事件A与B相互独立吗”教师=classical）。
  - 映射阶段不读取教师标签；教师标签只在 eval 阶段读（360 + 288 + 310 + 第四批 168，
    评估分母 1026）。

阶段：
  --stage map   全量 1797 映射（不读教师标签）→ mapped_1797_v7.json / mapped_1797_v7_batch.txt
  --stage eval  读四批教师标签评估 → mapped_1797_reviewed_v7.json + mapped_1797_v7_eval.json
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
STRUCT = OUT / 'structure_5books.json'
BLOCKS = OUT / 'blocks_1797_with_structure.json'
V3_MAPPED = OUT / 'mapped_1797.json'
V4_MAPPED = OUT / 'mapped_1797_v4.json'
V4_EVAL = OUT / 'mapped_1797_v4_eval.json'
REVIEWED_ROUND2 = OUT / 'mapped_1797_reviewed_round2.json'
REVIEWED_ROUND3 = OUT / 'mapped_1797_reviewed_round3.json'
TEACHER_360 = OUT / 'review_360_parsed.json'
TEACHER_288 = OUT / 'review_round2_parsed.json'
TEACHER_310 = OUT / 'review_round3_parsed.json'
MAPPED = OUT / 'mapped_1797_v7.json'
BATCH = OUT / 'mapped_1797_v7_batch.txt'
REVIEWED = OUT / 'mapped_1797_reviewed_v7.json'
EVAL = OUT / 'mapped_1797_v7_eval.json'
V5_MAPPED = OUT / 'mapped_1797_v5.json'
V6_MAPPED = OUT / 'mapped_1797_v6.json'
REVIEWED_ROUND4 = OUT / 'mapped_1797_reviewed_round4.json'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
MODEL_VERSION = 'textbook-map-v7-2026-11-07'
CN_NUM = '零一二三四五六七八九十'

# ── 章级模块约束（人工课程知识；SEC/PRI 层允许 section 候选跨模块）──────────────
CHAPTER_MODULES = {
    ('必修第一册', 1): ['01'], ('必修第一册', 2): ['02', '12'], ('必修第一册', 3): ['02'],
    ('必修第一册', 4): ['02'], ('必修第一册', 5): ['04'],
    ('必修第二册', 6): ['05'], ('必修第二册', 7): ['06'], ('必修第二册', 8): ['08'],
    ('必修第二册', 9): ['10'], ('必修第二册', 10): ['10'],
    ('选择性必修第一册', 1): ['08'], ('选择性必修第一册', 2): ['09'], ('选择性必修第一册', 3): ['09'],
    ('选择性必修第二册', 4): ['07'], ('选择性必修第二册', 5): ['03'],
    ('选择性必修第三册', 6): ['11'], ('选择性必修第三册', 7): ['10'], ('选择性必修第三册', 8): ['10'],
}

# ── 人工 section→kp 候选（依据节标题/课标内容，不看教师标签）──────────────────
# (kp, prior, fallback)：prior 为节级先验加分；fallback=True 表示正文无证据时允许低置信兜底。
SECTION_KP = {
    ('必修第一册', '1.2'): [('kp_01_02_relation', 6.0, True)],
    ('必修第一册', '1.3'): [('kp_01_03_operation', 6.0, True)],
    ('必修第一册', '2.3'): [('kp_12_01_quadratic', 4.5, True)],
    ('必修第一册', '5.2'): [('kp_04_01_definition', 5.0, True), ('kp_04_02_identity', 4.5, False)],
    ('必修第一册', '5.4'): [('kp_04_05_graph', 5.0, True)],
    ('必修第一册', '5.4.2'): [('kp_04_05_graph', 5.0, True)],
    ('必修第一册', '5.5'): [('kp_04_03_sumdiff', 5.0, True), ('kp_04_04_double', 4.0, False),
                               ('kp_04_02_identity', 4.0, False)],
    ('必修第一册', '5.5.2'): [('kp_04_03_sumdiff', 4.5, False), ('kp_04_04_double', 4.0, False)],
    ('必修第二册', '6.2'): [('kp_11_02_permutation', 0.0, False)],  # 占位：不做 SEC 重选
    ('必修第二册', '6.4'): [('kp_05_08_apply', 4.0, False), ('kp_05_03_dot', 4.0, False),
                              ('kp_05_04_perpendicular', 3.5, False)],
    ('必修第二册', '6.4.3'): [('kp_04_09_cosine', 4.5, False), ('kp_04_08_sine', 4.5, False)],
    ('必修第二册', '7.1'): [('kp_06_01_concept', 4.0, False), ('kp_06_04_geometric', 3.5, False)],
    ('必修第二册', '7.2'): [('kp_06_02_operation', 4.5, False), ('kp_06_01_concept', 3.0, False)],
    ('必修第二册', '7.3'): [('kp_06_04_geometric', 4.5, False), ('kp_06_03_modulus', 3.5, False)],
    ('必修第二册', '8.1'): [('kp_08_03_position', 5.0, True)],
    ('必修第二册', '8.5'): [('kp_08_04_parallel', 5.0, True)],
    ('必修第二册', '8.6'): [('kp_08_05_perpendicular', 4.0, False), ('kp_08_03_position', 4.0, False)],
    ('必修第二册', '9.2'): [('kp_10_02_histogram', 4.5, False), ('kp_10_03_central', 4.0, False)],
    ('必修第二册', '9.2.3'): [('kp_10_03_central', 5.0, True)],
    ('必修第二册', '9.3'): [('kp_10_03_central', 4.0, False), ('kp_10_01_sample', 3.5, False)],
    ('必修第二册', '10.3'): [('kp_10_04_classical', 4.0, False)],
    ('选择性必修第一册', '2.2'): [('kp_09_01_line', 5.0, True)],
    ('选择性必修第一册', '2.3'): [('kp_09_01_line', 4.5, False)],
    ('选择性必修第一册', '2.3.4'): [('kp_09_01_line', 5.0, True)],
    ('选择性必修第一册', '2.4'): [('kp_09_02_circle', 5.0, False)],
    ('选择性必修第一册', '2.5'): [('kp_09_03_line_circle', 4.5, False)],
    ('选择性必修第一册', '2.5.2'): [('kp_09_02_circle', 4.5, False)],
    ('选择性必修第三册', '6.3'): [('kp_11_05_binomial', 4.5, False)],
    ('选择性必修第三册', '7.3'): [('kp_10_08_distribution', 4.5, False)],
    ('选择性必修第三册', '8.1'): [('kp_10_10_regression', 4.5, False)],
    ('选择性必修第三册', '8.2'): [('kp_10_10_regression', 5.0, True)],
    ('选择性必修第三册', '8.3'): [('kp_10_11_chisquare', 5.0, False)],
    ('选择性必修第二册', '4.1'): [('kp_07_01_concept', 5.0, False)],
    ('选择性必修第二册', '4.2'): [('kp_07_02_arithmetic', 5.0, False)],
    ('选择性必修第二册', '4.3'): [('kp_07_03_geometric', 5.0, False)],
    ('选择性必修第二册', '4.4'): [('kp_07_08_induction', 4.0, False)],
    ('选择性必修第二册', '5.1'): [('kp_03_08_concept', 5.0, True)],
    ('选择性必修第二册', '5.2'): [('kp_03_01_compute', 5.0, False)],
    ('选择性必修第二册', '5.2.2'): [('kp_03_01_compute', 5.0, False)],
    ('选择性必修第二册', '5.3'): [('kp_03_03_monotonic', 4.0, False), ('kp_03_04_extremum', 4.0, False),
                                    ('kp_03_05_param_hold', 3.5, False), ('kp_03_06_zeros', 3.5, False),
                                    ('kp_03_02_tangent', 3.5, False), ('kp_03_07_proof', 3.5, False)],
}
# 不做 SEC 节级重选的节（只走 PRI 规则）：v3 已工作良好或节内异质，重选风险大于收益。
SEC_SKIP = {('必修第一册', '3.4'), ('必修第二册', '6.2'), ('必修第二册', '6.4.3'),
            ('必修第二册', '7.2'), ('必修第二册', '8.3'), ('必修第二册', '9.3'),
            ('选择性必修第一册', '2.4'), ('选择性必修第一册', '2.5'),
            ('选择性必修第二册', '4.1'), ('选择性必修第二册', '4.2'), ('选择性必修第二册', '4.3'),
            ('选择性必修第二册', '4.4'), ('选择性必修第二册', '5.2'), ('选择性必修第二册', '5.2.2'),
            ('选择性必修第二册', '5.3'), ('选择性必修第三册', '8.3')}

# ── 章导言（无 section）→ 章首概念 kp ─────────────────────────────────────
CHAPTER_INTRO_KP = {
    ('必修第一册', 1): 'kp_01_01_concept',
    ('必修第二册', 9): 'kp_10_01_sample',
    ('选择性必修第一册', 1): 'kp_08_07_vector',
    ('选择性必修第一册', 3): 'kp_09_04_conic_def',
    ('选择性必修第二册', 5): 'kp_03_08_concept',
}
# 章末小结 → 章内“概念/总览”kp
CHAPTER_SUMMARY_KP = {
    ('必修第二册', 6): 'kp_05_01_concept',
    ('选择性必修第二册', 4): 'kp_07_01_concept',
}

# ── 窄条件规则（优先于 SEC 重选；节号 + 正文特征，neg 为排除）────────────────
# (book, sections, regex, neg_regex, kp, conf, note)
PRIORITY_RULES = [
    # 必修一 · 1.2/1.3 集合关系/运算题干特征
    ('必修第一册', ('1.2',), r'子集|真子集|集合相等|Venn|包含', None, 'kp_01_02_relation', 0.68,
     '1.2 节内子集/集合关系'),
    ('必修第一册', ('1.3',), r'交集|并集|补集|\\complement|\\cap|\\cup|∁', None, 'kp_01_03_operation', 0.72,
     '1.3 节内集合运算'),
    # 必修一 · 2.3 基本不等式应用
    ('必修第一册', ('2.3',), r'造价|基本不等式|一正二定|用料最省', r'小结|本章知识结构', 'kp_12_03_basic', 0.62,
     '2.3 节内基本不等式应用'),
    # 必修一 · 3.1 分段函数
    ('必修第一册', ('3.1',), r'分段函数|分段', None, 'kp_02_13_segment', 0.70,
     '3.1 节内分段函数'),
    # 必修一 · 3.2 最值/值域
    # 必修一 · 3.2 最值/值域
    # v5 修正：v4 用裸“最大值|最小值|值域”会把 3.2 节导语（正文含节标题“函数的基本性质”、
    # 举“有没有最大值或最小值”）和“例3 根据定义证明…单调递增”误判成 range；教师=monotonic，
    # 且 v3 基线本来就对。v5 只加窄排除：节标题/导语特征 + 定义证明单调的题型特征。
    # 注意不能用裸“单调”：0088-1（教师=range）正文含“在区间[2，6]上单调递减”是最大值例题的
    # 单调性分析，排除它会把它打回 v3 的 monotonic（新 harmed）。
    ('必修第一册', ('3.2',), r'最大值|最小值|值域',
     r'函数的基本性质|定义证明|证明[^。]{0,12}单调', 'kp_02_03_range', 0.66,
     '3.2 节内最值/值域'),
    # 必修一 · 3.2.2 单调性证明
    ('必修第一册', ('3.2.2',), r'单调递增|单调递减|单调性|单调区间', r'奇偶|奇函数|偶函数', 'kp_02_04_monotonic', 0.68,
     '3.2.2 节内单调性证明'),
    # 必修一 · 3.4 函数模型
    ('必修第一册', ('3.4',), r'函数模型|实际问题的函数|建立函数|个税|应纳税', None, 'kp_02_12_abstract', 0.64,
     '3.4 节内函数建模'),
    # 必修一 · 3.4 幂函数
    ('必修第一册', ('3.4',), r'幂函数', None, 'kp_02_10_power', 0.64,
     '3.4 节内幂函数'),
    # 必修一 · 3.4 分段函数公式续写（v6 新增）
    # 个税/阶梯计费例题在 0100-2/0101-1 这类续写块里只有“当…时，所以 y=…；”的分段公式，
    # 没有“函数模型/个税”等建模词，v3 基线落到 kp_02_01_concept（教师=segment）。
    # 顺序必须放在“3.4 节内函数建模”之后：0100-1（教师=abstract 的题头）含“个税/应纳税”，
    # 先被建模规则命中，不会被本规则抢走。
    ('必修第一册', ('3.4',), r'当[^。]{0,80}时[，,]?[^。]{0,80}y\s*=[^。]{0,60}[；;]', None,
     'kp_02_13_segment', 0.66, '3.4 节内分段函数公式续写'),
    # 必修一 · 4.5.3 指数增长模型
    # v5 修正：v4 的“浮萍|增长率为|a^t|y=a”会把 4.5.3 的马尔萨斯人口模型（0155/0157-3）、
    # 碳14 半衰期（0157-2）等“函数模型应用”块误判成 exponential；这些块教师=abstract，
    # v3 基线本来就对。v5 只加窄排除：函数模型/建模语境 + 两个具体模型名。
    # 反向样本 0162-2（浮萍 y=a^t，教师=exponential）不含排除词，继续命中。
    ('必修第一册', ('4.5.3',), r'浮萍|增长率为|a\s*\^\s*\{?\s*t|y=a',
     r'函数模型|碳14|马尔萨斯|人口模型|建模', 'kp_02_08_exponential', 0.62,
     '4.5.3 节内指数增长模型'),
    # 必修一 · 4.5.3 统计数据/人口数据建模（v6 新增）
    # 0155-2 是国家统计局人口数据表（拟合函数模型），v3 基线按“人口”字面落到 kp_02_09_logarithm，
    # 教师=kp_02_12_abstract。0155-1/0156-1 同样命中但本来就是 abstract（只改 rule 字段）。
    ('必修第一册', ('4.5.3',), r'国家统计局|人口总数', None, 'kp_02_12_abstract', 0.66,
     '4.5.3 节内统计/人口数据建模'),
    # 必修一 · 4.5.3 二分法求零点习题（v6 新增）
    # 0162-1 是“习题4.5 复习巩固”里的二分法/零点题组，v3 基线落到 kp_02_12_abstract，
    # 教师=kp_02_11_zero。不用裸“二分法|零点”（会命中 0162-2 浮萍块与 0167-2 等未复核块），
    # 只用“二分法…零点”的连写短语：本数据集内仅 0162-1 命中。
    ('必修第一册', ('4.5.3',), r'二分法[^。]{0,20}零点', None, 'kp_02_11_zero', 0.68,
     '4.5.3 节内二分法求零点习题'),
    # 必修一 · 5.2 同角关系/诱导求值（只认同角关系题型，避免把“用定义求值/求证”误判）
    ('必修第一册', ('5.2',),
     r'(?s)(?=.*(同角|平方关系|商的关系)).*|用\s*cos\s*[αa]|用\s*sin\s*[αa]|已知[^。]{0,45}sin[^。]{0,45}求\s*\\?cos|'
     r'已知[^。]{0,45}cos[^。]{0,45}求\s*\\?sin|已知[^。]{0,45}tan[^。]{0,45}求', None,
     'kp_04_02_identity', 0.68, '5.2 节内同角关系'),
    # 必修一 · 5.4/5.4.2 sin/cos 图像与性质
    ('必修第一册', ('5.4', '5.4.2'), r'(sin|cos)', r'解三角形|△ABC', 'kp_04_05_graph', 0.66,
     '5.4 节内图像与性质'),
    # 必修一 · 5.5 和差角公式
    ('必修第一册', ('5.5',), r'和\s*\(?\s*差\s*\)?\s*角|两角和|两角差|cos\s*\(\s*π|cos\s*\(\s*\\pi|tan\s*\(\s*[aα]?\s*-\s*\\?pi', None,
     'kp_04_03_sumdiff', 0.68, '5.5 节内和差角公式'),
    # 必修一 · 5.7 节内同角关系练习
    ('必修第一册', ('5.7',), r'扇形.{0,12}(弧长|面积)|sinx\s*=\s*2\s*cos|同角', None, 'kp_04_02_identity', 0.62,
     '5.7 节内同角关系练习'),
    # 必修一 · 5.7 节内和差角/辅助角
    ('必修第一册', ('5.7',), r'tan\s*\(\s*[aα]\s*-\s*\\?pi|1\s*-\s*tan|tan\s*2\s*0', None, 'kp_04_03_sumdiff', 0.62,
     '5.7 节内和差角公式'),
    # 必修一 · 5.7 港口潮汐应用结论（v6 新增）
    # 0254-2（“……进港，……出港.每次可以在港口停留5小时左右”）是潮汐应用题的结论块，
    # 只有一句应用结论，v3 判 vocab_gap（空标签）；教师=kp_04_11_apply。
    # 不能用宽“进港|出港|港口”：0254-1 的演算正文也含进/出港（模型标签 graph）。
    # “在港口停留/港口停留”在本数据集 5.7 内仅 0254-2 命中。
    ('必修第一册', ('5.7',), r'在港口停留|港口停留', None, 'kp_04_11_apply', 0.64,
     '5.7 节内港口潮汐应用结论'),
    # 必修二 · 6.3.4 用数量积推两角差余弦
    ('必修第二册', ('6.3.4',), r'cos\s*\(\s*[αa]\s*-\s*[βb]|两角差', None, 'kp_05_03_dot', 0.64,
     '6.3.4 节内数量积推导两角差余弦'),
    # 必修二 · 6.4 向量应用栏目
    ('必修第二册', ('6.4',), r'平面向量的应用|向量在物理中的应用|向量在几何中的应用', None,
     'kp_05_08_apply', 0.70, '6.4 节内向量应用栏目'),
    # 必修二 · 6.4.3 章末小结
    ('必修第二册', ('6.4.3',), r'小结|本章知识结构', None, 'kp_05_01_concept', 0.70,
     '6.4.3 节内章末小结'),
    # 必修二 · 6.4.3 定理/练习（只认节内正文的定理名与解三角形模板，避开章末复习/向量题混排）
    ('必修第二册', ('6.4.3',), r'利用正弦定理|正弦定理求|2\.正弦定理', r'小结|本章知识结构',
     'kp_04_08_sine', 0.70, '6.4.3 节内正弦定理'),
    # v6 新增：解三角形模板“分别根据下列条件解三角形”独立成规，置于既有余弦规则之前。
    # 根因：0068-1 正文命中既有余弦规则，但同一块后一题是航行应用题（含“航行”），
    # 被既有规则的排除词误杀，回落 v3 基线 kp_05_01_concept。这里保留“游泳/水流/测量/塔高/
    # 台风”等排除，只把模板句作为更强的正条件；仍排除章末小结。
    ('必修第二册', ('6.4.3',), r'分别根据下列条件解三角形',
     r'游泳|水流|测量|塔高|台风|小结|本章知识结构', 'kp_04_09_cosine', 0.70,
     '6.4.3 节内解三角形模板（分别根据下列条件）'),
    ('必修第二册', ('6.4.3',), r'解这个三角形|分别根据下列条件解三角形', r'游泳|水流|投影向量|测量|塔高|台风|航行|小结|本章知识结构',
     'kp_04_09_cosine', 0.68, '6.4.3 节内余弦定理解三角形练习'),
    # v6 新增：0061-3 是“已知三内角 A，B，C 的对边……求 A / 求 b,c”的解三角形题，
    # 既不命中“解这个三角形/分别根据下列条件”模板（该块另有“测量实习作业”被排除），
    # 也没有定理名；用“内角A，B，C的对边”这一解三角形标准设问特征窄命中（全量仅此 1 块）。
    ('必修第二册', ('6.4.3',), r'内角\s*A\s*[，,]\s*B\s*[，,]\s*C\s*的对边', None,
     'kp_04_09_cosine', 0.68, '6.4.3 节内解三角形（三内角对边设问）'),
    ('必修第二册', ('6.4.3',), r'\\overrightarrow[^。]{0,120}\\cdot|\\cdot[^。]{0,120}\\overrightarrow', r'小结|本章知识结构',
     'kp_05_03_dot', 0.66, '6.4.3 节内（复习题）向量数量积'),
    ('必修第二册', ('6.4.3',), r'(?s)(?=.*\\overrightarrow)(?=.*求[^。]{0,80}的坐标)', r'测量|塔高|仰角|台风|航行|选择题|小结|本章知识结构',
     'kp_05_02_coordinate', 0.64, '6.4.3 节内（复习题）向量坐标运算'),
    # 必修二 · 7.3 复数的三角表示式（r(cosθ+isinθ) 推导）
    ('必修第二册', ('7.3',), r'a\s*\+\s*b\s*i\s*=\s*r|r\s*\(\s*\\?cos\s*θ\s*\+\s*i', None, 'kp_06_04_geometric', 0.62,
     '7.3 节内复数三角表示式'),
    # 必修二 · 7.1 复平面
    ('必修第二册', ('7.1',), r'复平面', r'小结', 'kp_06_04_geometric', 0.72,
     '7.1 节内复数几何表示'),
    # 必修二 · 7.2 复数四则运算练习
    ('必修第二册', ('7.2',), r'计算', None, 'kp_06_02_operation', 0.68,
     '7.2 节内复数四则运算'),
    # 必修二 · 8.1 基本立体图形（词表无对应，按结构特征归入空间位置关系）
    ('必修第二册', ('8.1',), r'棱柱|棱锥|棱台|圆柱|圆锥|圆台|多面体|旋转体|几何体|四面体|平行六面体', None,
     'kp_08_03_position', 0.62, '8.1 节内空间几何体结构（最近邻口径）'),
    # 必修二 · 8.6 异面直线所成角定义（v6 新增，必须排在“异面→位置关系”规则之前）
    # 0154-1 是 8.6.1 里“异面直线所成角”的定义+例1 块，正文含“把……所成的角叫做异面直线
    # a 与 b 所成的角(或夹角)”；v5 被下面宽“异面”规则先命中抢成 kp_08_03_position，
    # 教师=kp_08_06_angle。这里用定义句“叫做异面直线”窄命中；同节 0153-1/0155-1/0155-2
    # （教师=position）不含该定义句，仍走下面的宽规则。
    ('必修第二册', ('8.6',), r'叫做异面直线', None, 'kp_08_06_angle', 0.68,
     '8.6 节内异面直线所成角定义'),
    # 必修二 · 8.6 异面直线
    ('必修第二册', ('8.6',), r'异面', None, 'kp_08_03_position', 0.66,
     '8.6 节内异面直线位置关系'),
    # 必修二 · 9.2.3 集中趋势
    ('必修第二册', ('9.2.3',), r'平均数|中位数|众数|集中趋势|百分位', None, 'kp_10_03_central', 0.68,
     '9.2.3 节内集中趋势估计'),
    # 必修二 · 9.3 统计案例（样本数字特征/数据分析）
    ('必修第二册', ('9.3',), r'平均数|中位数|方差|数据|样本', None, 'kp_10_03_central', 0.62,
     '9.3 节内统计案例（样本数字特征口径）'),
    # 必修二 · 10.3 频率估计概率
    ('必修第二册', ('10.3',), r'频率', None, 'kp_10_04_classical', 0.62,
     '10.3 节内用频率估计概率'),
    # 选必一 · 2.2 直线的方程
    ('选择性必修第一册', ('2.2',), r'直线(的|方程)|斜率|截距', r'圆的方程|圆心|参数方程', 'kp_09_01_line', 0.70,
     '2.2 节内直线方程'),
    # 选必一 · 2.3.4 平行线间距离
    ('选择性必修第一册', ('2.3.4',), r'距离|平行', r'圆的方程|圆心', 'kp_09_01_line', 0.66,
     '2.3.4 节内直线间距离'),
    # 选必三 · 6.3 计数原理章末复习
    ('选择性必修第三册', ('6.3',), r'复习参考题\s*6', None, 'kp_11_01_principle', 0.60,
     '6.3 节内计数原理章末复习'),
    # 选必三 · 6.3 杨辉三角与组合数
    ('选择性必修第三册', ('6.3',), r'C\s*_\s*\{\s*n\s*-\s*1\s*\}|组合数的性质', None, 'kp_11_03_combination', 0.64,
     '6.3 节内杨辉三角与组合数'),
    # 选必三 · 7.3 随机变量数字特征
    ('选择性必修第三册', ('7.3',), r'随机变量.{0,20}(均值|期望|方差)|E\s*\(\s*[Xx]\s*\)|D\s*\(\s*[Xx]\s*\)', None,
     'kp_10_08_distribution', 0.70, '7.3 节内随机变量期望/方差'),
    # 选必三 · 8.1 样本相关系数
    ('选择性必修第三册', ('8.1',), r'样本相关系数|相关系数|散点图|线性相关', None, 'kp_10_10_regression', 0.66,
     '8.1 节内样本相关系数'),
    # 选必三 · 8.3 章末数学建模/回归应用
    ('选择性必修第三册', ('8.3',), r'数学建模|建立统计模型|PM\s*2|回归方程|回归结果', None,
     'kp_10_10_regression', 0.64, '8.3 节内回归建模应用'),
    # 选必二 · 4.4 节内章末小结
    ('选择性必修第二册', ('4.4',), r'小结|本章知识结构', None, 'kp_07_01_concept', 0.70,
     '4.4 节内章末小结'),
    # 选必二 · 4.4 节内等比数列应用
    ('选择性必修第二册', ('4.4',), r'成等比|倍加增|算法统宗|复利|对偶', None, 'kp_07_03_geometric', 0.64,
     '4.4 节内等比数列应用'),
    # 选必二 · 5.1 节导语/变化率问题小节（v6 新增，置于既有 5.1 规则之前）
    # 0064-1 是 5.1 节开头+5.1.1 变化率问题导语块：正文谈“函数的单调性/增长快慢”旧知识，
    # 但不含“平均/瞬时变化率”字样，既有规则不命中；随后 SEC 节级重选按正文“单调性”把它
    # 重选成 kp_03_03_monotonic（教师=kp_03_08_concept）。
    # 用节标题/小节标题窄命中（全量 5.1 内仅 0064-1）：0069-1 是“5.1.2 导数的概念及其几何
    # 意义”块（教师=tangent），不含“导数的概念及其意义/5.1.1”，不受影响。
    ('选择性必修第二册', ('5.1',), r'导数的概念及其意义|5\.1\.1', None, 'kp_03_08_concept', 0.66,
     '5.1 节导语/变化率问题小节'),
    # 选必二 · 5.1 导数概念
    ('选择性必修第二册', ('5.1',), r'瞬时变化率|平均变化率', None, 'kp_03_08_concept', 0.70,
     '5.1 节内导数概念'),
    # 选必二 · 5.3 极值定义
    ('选择性必修第二册', ('5.3',), r'先增.{0,20}后减|极大值|极小值|极值', r'判断下列函数的单调性|求单调区间|单调区间', 'kp_03_04_extremum', 0.66,
     '5.3 节内极值定义'),
    # 选必二 · 5.3 变化率/图像陡峭
    ('选择性必修第二册', ('5.3',), r'平缓|陡峭|变化得较', r'单调性|单调区间|单调递增|单调递减', 'kp_03_08_concept', 0.60,
     '5.3 节内导数几何意义'),
    # 选必二 · 5.3 最优化应用
    ('选择性必修第二册', ('5.3',), r'容积|用料最省|方盒', None, 'kp_03_04_extremum', 0.62,
     '5.3 节内最优化应用'),
]

# ── v7 新增窄条件规则（第四批 23 条不一致；一律追加在既有规则之后）──────────────
# (book, sections, regex, neg_regex, kp, conf, note)
V7_RULES = [
    # 必修一 · 3.1 分段函数解析式（0076-1）
    # 该块是「结合图3.1-5，得出函数 M(x) 的解析式为 M(x)={…分段…}」的表示法续块；
    # 既有「分段函数|分段」规则不命中。用「解析式为」+ 分段公式环境窄命中。
    # 反样本 0073-3/0080-1 也含同样的 {…} 分段公式，但没有「解析式为」引导语，教师=concept，
    # 因此不能用裸的 \left\{\begin{array}（实测会把这两块抢成 segment）。
    ('必修第一册', ('3.1',), r'解析式为[^。]{0,40}\\left\\\{\s*\\begin\{array\}', None,
     'kp_02_13_segment', 0.66, '3.1 节内分段函数解析式（解析式为分段公式）'),
    # 必修一 · 4.5.2 二分法求方程的近似解（0151-2）
    # 该块以 4.5.2 小节标题开头，是二分法/零点的导入块；既有 4.5.3 二分法规则不在 4.5 节。
    # 用小节标题连写（0153-1 的例2 正文也含「用二分法求方程的近似解」，但不是小节标题）。
    ('必修第一册', ('4.5',), r'4\.5\.2\s*用二分法求方程[^。]{0,12}近似解', None,
     'kp_02_11_zero', 0.66, '4.5.2 小节标题：用二分法求方程的近似解'),
    # 必修一 · 4.5.3 三个方案增长比较（0158-2）
    # 该块是「方案三…三个模型…对增长情况进行分析…表4.5-5」的续块，v3 基线按“增长/数据”
    # 落到对数函数；教师=abstract（函数模型应用）。同节 0157-3/0159-1/0161-1 教师也是
    # abstract（命中只改 rule 字段，不改标签）。
    ('必修第一册', ('4.5.3',), r'三个方案|三种方案|增长情况', None, 'kp_02_12_abstract', 0.64,
     '4.5.3 节内函数模型增长比较'),
    # 必修一 · 5.2 同角关系恒等式（0191-2）
    # 该块开头是 (1+tan²α)cos²α 化简 +「求证 sin⁴+sin²cos²+cos²=1」，是 5.2.2 同角关系练习；
    # 既有 5.2 同角规则不命中，SEC 重选抢成 definition。用 1+tan² 这一同角关系标志窄命中。
    ('必修第一册', ('5.2',), r'1\s*\+\s*\\?tan\s*\^\s*\{\s*2', None,
     'kp_04_02_identity', 0.64, '5.2 节内同角关系恒等式（1+tan²）'),
    # 必修一 · 5.7 三角函数应用结论（0256-2）
    # 该块是习题5.7 里「消峰平谷」电价方案的应用结论，v3 基线 graph；教师=apply。
    # 「消峰平谷」为本数据集内唯一短语，不致误伤。
    ('必修第一册', ('5.7',), r'消峰平谷', None, 'kp_04_11_apply', 0.64,
     '5.7 节内三角函数应用结论（消峰平谷）'),
    # 必修二 · 6.2.4 习题6.2 向量作图/化简（0030-1）
    # 该块是习题6.2 复习巩固 5.作图验证/6.求作向量/8.化简，属向量线性运算；v3 基线因
    # 章节落在 6.2.4 节被数量积关键词带走。用「作图验证|求作向量」窄命中。
    ('必修第二册', ('6.2.4',), r'作图验证|求作向量', None, 'kp_05_01_concept', 0.62,
     '6.2.4 节内（习题6.2）向量作图'),
    # 必修二 · 6.2.4 向量位移合成（0030-4）
    # 该块含 14/15/16 题（用 a,b 表示向量；AB+DC=2EF（向量式）；飞机位移合成），
    # 属向量线性运算；教师=concept。用「位移」+ 排除数量积/做功（0024-1 定义块含“功/位移”）。
    ('必修第二册', ('6.2.4',), r'位移', r'数量积|做功', 'kp_05_01_concept', 0.62,
     '6.2.4 节内向量位移合成'),
    # 必修二 · 6.3 平面向量基本定理/力的分解导入（0032-2）
    # 该块是「一个力可以分解为两个力…将向量 a 分解为两个向量」的基本定理导入；
    # 教师=decompose。用「分解为两个(力|向量)」，避开裸“分解/基本定理”（0032-1 教师=coordinate）。
    ('必修第二册', ('6.3',), r'分解为两个(力|向量)', None, 'kp_05_06_decompose', 0.64,
     '6.3 节内平面向量基本定理（力的分解导入）'),
    # 必修二 · 6.3.4 数乘坐标/中点坐标（0039-2）
    # 该块是「三等分点求点 P 的坐标 / 中点坐标公式」的例题续块；教师=coordinate。
    ('必修第二册', ('6.3.4',), r'三等分点|中点坐标', None, 'kp_05_02_coordinate', 0.64,
     '6.3.4 节内数乘运算的坐标表示（中点/三等分点）'),
    # 必修二 · 6.4.3 解三角形应用（0057-1/0058-1）
    # 两块是 6.4.3「应用举例」的例10/例11（测量高度/测量角度）+ 练习（仰角/基线/方向）；
    # 教师=apply（解三角形应用）。排除章末小结与海伦/秦九韶阅读材料（0062-* 是面积公式）。
    ('必修第二册', ('6.4.3',), r'仰角|基线|测量高度|测量角度|目标方向',
     r'小结|本章知识结构|海伦|秦九韶', 'kp_04_11_apply', 0.66,
     '6.4.3 节内解三角形应用（测量/仰角/方向）'),
    # 必修二 · 6.4.3 数学探究「用向量法研究三角形的性质」（0071-2）
    # 该块用基底/平面向量基本定理做三角形中线证明；教师=向量与几何综合。
    ('必修第二册', ('6.4.3',), r'由平面向量基本定理|基底可以有不同的选', None,
     'kp_05_08_apply', 0.64, '6.4.3 节内向量法研究三角形（基底推导）'),
    # 必修二 · 7.2 复数乘除算式续块（0087-3）
    # 该块只有 (4)(…)(…) 与 (5)(1+i)(1-i)+(-1+i) 两行算式，没有“计算”触发词；
    # 用共轭乘积 (1+i)(1-i) 这一复数乘法标志窄命中（0085-2 的 (1+i)² 不命中）。
    ('必修第二册', ('7.2',), r'\(1\s*\+\s*i\s*\)\s*\(\s*1\s*-\s*i\s*\)', None,
     'kp_06_02_operation', 0.62, '7.2 节内复数乘除运算续块'),
    # 必修二 · 7.3 复数乘除运算的几何意义（0095-1）
    # 该块是例4（向量绕 O 旋转 120° 求对应复数）与乘除几何意义探究；教师=geometric。
    # 既有 7.3 三角表示规则只认代数/三角形式互化，不命中。
    ('必修第二册', ('7.3',), r'复数乘法.{0,10}几何意义|绕点\s*O\s*按(逆时针|顺时针)方向旋转', None,
     'kp_06_04_geometric', 0.64, '7.3 节内复数乘除运算的几何意义（旋转）'),
    # 必修二 · 8.6.2 直线与平面所成的角（0159-1）
    # 该块是线面角定义 + 例4（求直线与平面所成角）+ 射影；教师=angle。
    # 既有 8.6 的角规则只挂在 section 8.6，8.6.2 无规则，落到 v3 基线的 perpendicular。
    ('必修第二册', ('8.6.2',), r'直线与平面所成的角', None, 'kp_08_06_angle', 0.66,
     '8.6.2 节内直线与平面所成的角'),
    # 必修二 · 8.6.2 混合块主考棱台体积推导（0162-1）
    # 该块主体是「例6 推导棱台的体积公式」（V−V′），随后接 8.6.3 二面角引言；
    # 教师=表面积与体积。用「棱台的体积」（0161-1 的例6 同短语顺带修正，见 eval 审计）。
    ('必修第二册', ('8.6.2',), r'棱台的体积', None, 'kp_08_02_area_volume', 0.64,
     '8.6.2 节内棱台体积推导'),
    # 必修二 · 9.2 百分位数计算/估计（0211-1）
    # 该块是「50，75百分位数…百分位数为第7,14,21项…例3 估计80%/95%分位数」例题续块；
    # 教师=样本数字特征。不用裸“百分位数”（0209-1 的小节标题“总体百分位数的估计”教师=histogram）。
    ('必修第二册', ('9.2',), r'百分位数(为|分别|约为)|第[^。]{0,12}百分位数', None,
     'kp_10_03_central', 0.64, '9.2 节内百分位数计算/估计'),
    # 必修二 · 9.2.3 方差/标准差（0222-2）
    # 该块是样本方差性质 + 产量稳定性 + 分层抽样均值方差练习；教师=样本数字特征
    # （kp_10_03_central 词表口径含均值/中位数/众数/方差/标准差）。同节教师行均为 central。
    ('必修第二册', ('9.2.3',), r'方差|标准差', None, 'kp_10_03_central', 0.64,
     '9.2.3 节内方差/标准差（样本数字特征）'),
    # 必修二 · 9.3 百分位数应用（0233-1）
    # 该块是「75% 居民第一档…阶梯电价」的百分位数决策题；教师=central。
    ('必修第二册', ('9.3',), r'阶梯电价', None, 'kp_10_03_central', 0.62,
     '9.3 节内百分位数应用（阶梯电价）'),
    # 必修二 · 10.3 事件独立性（0274-2）
    # 该块是「假设对抽到的不同题目能否答对是独立的」独立性假设题；教师=互斥与独立。
    # 不用裸“相互独立”（0273-2 复习题“事件A与B相互独立吗”教师=classical）。
    ('必修第二册', ('10.3',), r'假设[^。]{0,40}独立的', None, 'kp_10_06_event', 0.62,
     '10.3 节内事件独立性假设'),
    # 选必一 · 3.3.2 复习题椭圆轨道（0150-1）
    # 该块是复习参考题3 第1题「卫星轨道是以地心为一个焦点的椭圆」；教师=椭圆性质。
    # 不用裸“椭圆”（3.3.2 抛物线正文大量“类比椭圆”）。
    ('选择性必修第一册', ('3.3.2',), r'为一个焦点的椭圆', None, 'kp_09_05_ellipse', 0.64,
     '3.3.2 节内椭圆轨道复习题'),
    # 选必二 · 5.2.2 牛顿法迭代求零点（0088-2）
    # 该块是牛顿法「用 x1 代替 x0 重复上面的过程得到 x2」的迭代续块；教师=零点个数。
    # 用「代替+零点」双条件（0087-3/0088-1/0088-3 无“代替”，教师=tangent）。
    ('选择性必修第二册', ('5.2.2',), r'(?=.*代替)(?=.*零点)', None, 'kp_03_06_zeros', 0.62,
     '5.2.2 节内牛顿法迭代（用 x1 代替 x0 求零点）'),
    # 选必二 · 5.3 利用导数判断单调性（0091-2）
    # 该块是例1 的解答续块（f′(x)>0 ⇒ 单调递增，f′(x)<0 ⇒ 单调递减）；
    # 教师=单调性讨论。排除极值/最值/最优应用语境（这些由既有极值/最优化规则处理）。
    ('选择性必修第二册', ('5.3',), r'单调递增|单调递减',
     r'极值|极大值|极小值|最值|容积|利润|单调区间', 'kp_03_03_monotonic', 0.62,
     '5.3 节内利用导数判断单调性'),
]


MIN_SCORE = 2.0
FILL_CONF = 0.55


def load():
    spec = importlib.util.spec_from_file_location('v3', ROOT / 'tools' / 'kb_textbook_map_v3.py')
    v3 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v3)
    tb1, mockann = v3.load()
    return v3, tb1, mockann


def book_key(title):
    for suffix in sorted(['选择性必修第三册', '选择性必修第二册', '选择性必修第一册',
                          '必修第一册', '必修第二册'], key=len, reverse=True):
        if title.endswith(suffix):
            return suffix
    return title


def cn_number(n):
    if n <= 10:
        return CN_NUM[n]
    if n < 20:
        return '十' + CN_NUM[n - 10]
    if n % 10 == 0:
        return CN_NUM[n // 10] + '十'
    return CN_NUM[n // 10] + '十' + CN_NUM[n % 10]


def chapter_title_variants(chapter, chapter_num):
    out = set()
    if not chapter:
        return out
    c = re.sub(r'\s+', '', chapter)
    out.add(c)
    if chapter_num:
        out.add(c.replace(f'第{chapter_num}章', f'第{cn_number(chapter_num)}章'))
        out.add(c.replace(f'第{cn_number(chapter_num)}章', f'第{chapter_num}章'))
    return out


def _compact(text):
    chars, idx = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch)
            idx.append(i)
    return ''.join(chars), idx


def strip_running_headers(text, block):
    """去掉页面边界的“第N章 <章标题> + 页码”运行页眉/页脚（只对非空 section 生效）。

    根因：OCR 每页页脚/页眉带章标题，例如“第二章直线和圆的方程59”，会让正文打分
    误命中“圆的方程”“函数的概念”“指数函数”等，属于非正文噪声。
    """
    if not block.get('section_num') and not block.get('section'):
        return text
    comp, idx = _compact(text)
    if not comp:
        return text
    variants = chapter_title_variants(block.get('chapter', ''), block.get('chapter_num'))
    drop = set()
    for v in sorted(variants, key=len, reverse=True):
        if len(v) < 4:
            continue
        start = 0
        while True:
            p = comp.find(v, start)
            if p < 0:
                break
            end = p + len(v)
            if p <= 60 or end >= len(comp) - 60:
                for j in range(p, end):
                    drop.add(idx[j])
                k = end
                while k < len(comp) and comp[k].isdigit() and k - end < 4:
                    drop.add(idx[k])
                    k += 1
                k = p - 1
                while k >= 0 and comp[k].isdigit() and p - 1 - k < 4:
                    drop.add(idx[k])
                    k -= 1
            start = p + 1
    if not drop:
        return text
    return ''.join(ch for i, ch in enumerate(text) if i not in drop)


def build_auto_dict(structure, mockann, vocab):
    """节标题 → 候选 kp（仅用于无人工词条的节；不混入章标题）。"""
    auto = {}
    for sec in structure['sections']:
        bk = book_key(sec['book'])
        key = (bk, sec['section_num'])
        if key in SECTION_KP:
            continue
        allowed = CHAPTER_MODULES.get((bk, sec['chapter_num']))
        ss, _m = mockann.score_question(sec['section'], [], vocab)
        cand = []
        for k, v in sorted(ss.items(), key=lambda kv: (-kv[1], kv[0])):
            if v < 1:
                continue
            if allowed and k.split('_')[1] not in allowed:
                continue
            cand.append((k, v))
        auto[key] = cand[:3]
    return auto


def module_map():
    mods = {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            mid = m.group(2)
            mods[mid.split('_')[1]] = {'id': mid, 'name': re.split(r'（', m.group(1))[0].strip()}
    return mods


def confidence_from(score, margin):
    if score >= 8 and margin >= 2:
        conf = 0.92
    elif score >= 5 and margin >= 1:
        conf = 0.85
    elif score >= 3:
        conf = 0.72
    else:
        conf = 0.62
    if margin < 0.8:
        conf -= 0.08
    return round(max(0.4, min(0.95, conf)), 2)


def _sec_in(section_num, sections):
    return (section_num or '') in sections


def match_rule(rule, block, clean):
    book, sections, regex, neg = rule[0], rule[1], rule[2], rule[3]
    if book_key(block['book']) != book:
        return False
    if not _sec_in(block.get('section_num', ''), sections):
        return False
    if not re.search(regex, clean):
        return False
    if neg and re.search(neg, clean):
        return False
    return True


class Mapper:
    def __init__(self, v3, tb1, mockann, vocab, structure):
        self.v3 = v3
        self.tb1 = tb1
        self.mockann = mockann
        self.vocab = vocab
        self.dictionary = v3.build_dictionary(structure, vocab, mockann)
        self.auto = build_auto_dict(structure, mockann, vocab)

    def _body_scores(self, clean, block):
        scores, matched = self.mockann.score_question(clean, [], self.vocab)
        allowed = CHAPTER_MODULES.get((book_key(block['book']), block.get('chapter_num')))
        if allowed:
            scores = {k: v for k, v in scores.items() if k.split('_')[1] in allowed}
            matched = {k: v for k, v in matched.items() if k.split('_')[1] in allowed}
        return scores, matched

    def base(self, block):
        rec = self.v3.map_block(block, self.vocab, self.mockann, self.tb1, self.dictionary)
        rec['rule'] = 'v3_base'
        return rec

    def sec_elect(self, block, clean):
        """SEC 节级重选：节标题候选 + 去页眉页脚正文打分；允许 section 候选跨模块。"""
        bk = book_key(block['book'])
        key = (bk, block.get('section_num', '') or '')
        entry = SECTION_KP.get(key)
        if entry is None or key in SEC_SKIP:
            return None
        scores, matched = self._body_scores(clean, block)
        cand_order = {}
        fallback = False
        for i, (kp, prior, fb) in enumerate(entry):
            scores[kp] = scores.get(kp, 0.0) + prior
            matched.setdefault(kp, []).append('section:' + (block.get('section', '')[:18] or key[1]))
            cand_order[kp] = i
            fallback = fallback or fb
        # 章级候选（长尾节）只作低权重补充
        for kp, v in self.auto.get(key, []):
            scores[kp] = scores.get(kp, 0.0) + min(2.0, 0.6 * v)
            cand_order.setdefault(kp, 50 + len(cand_order))
        ranked = sorted(((k, v) for k, v in scores.items() if v > 0),
                        key=lambda kv: (-kv[1], cand_order.get(kv[0], 99), kv[0]))
        if not ranked or ranked[0][1] < MIN_SCORE:
            return None
        top, sc = ranked[0]
        body_top = max([v for k, v in scores.items() if k not in {c[0] for c in entry}] or [0.0])
        return {'kp': top, 'score': sc, 'ranked': ranked, 'matched': matched,
                'fallback_ok': fallback, 'body_top': body_top,
                'cand_order': cand_order, 'section': block.get('section', '') or key[1]}

    def map(self, block):
        base = self.base(block)
        if base['status'] == 'non_content':
            return base
        clean = strip_running_headers(block['text'], block)
        bk = book_key(block['book'])
        chapter_num = block.get('chapter_num')
        sec_num = block.get('section_num', '') or ''
        vocab = self.vocab

        def override(kp, conf, rule, reason):
            base.update({'kp_primary': kp, 'module': kp.split('_')[1], 'kp_name': vocab[kp]['name'],
                         'kp_secondary': [], 'confidence': conf, 'status': 'mapped',
                         'rule': rule, 'reason': reason})
            return base

        # 1) 章导言
        if not sec_num:
            kp = CHAPTER_INTRO_KP.get((bk, chapter_num))
            if kp and kp in vocab:
                return override(kp, 0.70, 'CAT:chapter_intro',
                                f'章导言无节归属，按章首概念归属{vocab[kp]["name"]}。')
        # 2) 章末小结：只走 SUM 规则；无章级 summary 映射时保留 v3 基线（小结块常把全章
        #    知识点并列，节内关键词规则/节级重选容易误判，如 5.7 小结出现“同角”）。
        if re.search(r'小结|本章知识结构', clean):
            kp = CHAPTER_SUMMARY_KP.get((bk, chapter_num))
            if kp and kp in vocab:
                return override(kp, 0.70, 'SUM:chapter_summary',
                                f'章末小结块，按章内概念/总览归属{vocab[kp]["name"]}。')
            return base
        # 3) 窄条件规则
        for rule in PRIORITY_RULES + V7_RULES:
            if match_rule(rule, block, clean):
                return override(rule[4], rule[5], 'PRI:' + rule[6],
                                f'节「{block.get("section", "")}」+ 正文特征：{rule[6]}；主考{vocab[rule[4]]["name"]}。')
        # 4) 节级重选（含兜底填充）
        el = self.sec_elect(block, clean)
        if el:
            top = el['kp']
            ranked = el['ranked']
            second = ranked[1][1] if len(ranked) > 1 else 0
            margin = el['score'] - second
            fill = base['status'] != 'mapped' or not (base.get('kp_primary'))
            if fill:
                conf = FILL_CONF
                rule = 'FILL:section_candidate'
                reason = (f'正文关键词证据不足，但节「{block.get("section", "")}」有 section→kp 候选，'
                          f'按低置信归属{vocab[top]["name"]}（待复核）。')
            else:
                conf = confidence_from(el['score'], margin)
                rule = 'SEC:section_elect'
                reason = (f'节「{block.get("section", "")}」节标题候选 + 去页眉页脚正文「'
                          f'{"/".join(dict.fromkeys(el["matched"].get(top, [])))[:40] or "节级先验"}」，'
                          f'主考{vocab[top]["name"]}。')
            secondary = []
            for k, v in ranked[1:]:
                if v < 3:
                    continue
                if k.split('_')[1] == top.split('_')[1]:
                    continue
                secondary.append(k)
                if len(secondary) == 2:
                    break
            base.update({'kp_primary': top, 'module': top.split('_')[1], 'kp_name': vocab[top]['name'],
                         'kp_secondary': secondary, 'confidence': conf, 'status': 'mapped',
                         'rule': rule, 'reason': reason})
        return base


def derive_ids(blocks):
    old = json.loads(V3_MAPPED.read_text(encoding='utf-8'))['items']
    id_map = {x['chunk_id']: x['block_id'] for x in old}
    missing = [b['chunk_id'] for b in blocks if b['chunk_id'] not in id_map]
    if missing or len(id_map) != len(blocks):
        raise SystemExit(f'block_id 推导失败：missing {len(missing)} / map {len(id_map)} / blocks {len(blocks)}')
    if len(set(id_map.values())) != len(blocks):
        raise SystemExit('block_id 不唯一')
    return id_map


def stage_map(args):
    v3, tb1, mockann = load()
    vocab = mockann.load_vocab()
    structure = json.loads(STRUCT.read_text(encoding='utf-8'))
    blocks = json.loads(BLOCKS.read_text(encoding='utf-8'))['blocks']
    id_map = derive_ids(blocks)
    mods = module_map()
    mapper = Mapper(v3, tb1, mockann, vocab, structure)
    recs = []
    for b in blocks:
        rec = mapper.map(b)
        rec['block_id'] = id_map[b['chunk_id']]
        if rec.get('module') and rec['module'] in mods:
            rec['module_id'] = mods[rec['module']]['id']
            rec['module_name'] = mods[rec['module']]['name']
        else:
            rec['module_id'] = ''
            rec['module_name'] = ''
        rec['model_version'] = MODEL_VERSION
        recs.append(rec)
    # 基线复现自检：未命中任何修正规则的块应与 v3 完全一致
    old = {x['chunk_id']: x for x in json.loads(V3_MAPPED.read_text(encoding='utf-8'))['items']}
    untouched = [x for x in recs if x['rule'] == 'v3_base']
    mismatch = sum(1 for x in untouched
                   if x['status'] != old[x['chunk_id']]['status']
                   or (x['kp_primary'] or '') != (old[x['chunk_id']]['kp_primary'] or ''))
    status = collections.Counter(x['status'] for x in recs)
    MAPPED.write_text(json.dumps({
        'count': len(recs), 'model_version': MODEL_VERSION,
        'rules': 'v7 = v6 规则引擎 + 22 条新增窄条件 PRI 规则（第四批 23 条不一致逐条收敛；'
                 '规则一律追加在既有 PRIORITY_RULES 之后，v6 已命中块语义不变；'
                 'SECTION_KP/SEC_SKIP/阈值/排除词均未改；无 block_id 硬编码）',
        'items': recs}, ensure_ascii=False, indent=1), encoding='utf-8')
    BATCH.write_text('\n'.join(
        f"{i:04d}|{x['block_id']}|{x['book']}|p{x['page']}-{x['part']}|{x['chapter']}|{x['section']}|"
        f"{x['status']}|{x['kp_primary']}|{','.join(x['kp_secondary'])}|{x['confidence']}"
        for i, x in enumerate(recs, 1)) + '\n', encoding='utf-8')
    changed = sum(1 for x in recs if x['rule'] != 'v3_base')
    rule_hits = collections.Counter(x['rule'].split(':')[0] for x in recs)
    # v6→v7 变化审计（全量 1797）
    old6 = {x['block_id']: x for x in json.loads(V6_MAPPED.read_text(encoding='utf-8'))['items']}
    rev4 = {x['block_id']: x for x in
            json.loads(REVIEWED_ROUND4.read_text(encoding='utf-8'))['items']}
    diff = [(x['block_id'], old6[x['block_id']]['kp_primary'], x['kp_primary'],
             old6[x['block_id']]['status'], x['status'], x['rule'],
             'T' if rev4[x['block_id']].get('review_status') == 'teacher' else 'm')
            for x in recs
            if (old6[x['block_id']]['kp_primary'] or '') != (x['kp_primary'] or '')
            or old6[x['block_id']]['status'] != x['status']
            or list(old6[x['block_id']]['kp_secondary']) != list(x['kp_secondary'])]
    print(f'[v7-map] {len(recs)} 块；status {dict(status)}；修正命中 {changed}（{dict(rule_hits)}）；'
          f'基线未命中块与 v3 不一致 {mismatch}')
    print(f'[v7-map] v6→v7 变化 {len(diff)} 块：')
    for bid, p6, p7, s6, s7, rule, kind in sorted(diff):
        print(f'  {bid} [{kind}]: {p6} ({s6}) → {p7} ({s7})  [{rule}]')
    print(f'[v7-map] 产物：{MAPPED} / {BATCH}')
    return 0


def _metrics(den, rows_by_id):
    mod = exact = any_ = 0
    for r in den:
        tk = r['teacher_kp']
        tm = tk.split('_')[1]
        lab = rows_by_id[r['block_id']]
        p = lab.get('kp_primary') or ''
        sec = list(lab.get('kp_secondary') or [])
        mod += bool(p) and p.split('_')[1] == tm
        exact += p == tk
        any_ += tk in ([p] if p else []) + sec
    return {'module': mod, 'exact': exact, 'any': any_, 'n': len(den)}



def _den(items):
    """评估分母口径：教师给了 kp 标签，且该块模型侧非 non_content。"""
    return [x for x in items
            if (x.get('teacher_kp') or '').startswith('kp_')
            and (x.get('model_status') or '') != 'non_content']


def stage_eval(args):
    """v7 评估：360 + 288 + 310 + 第四批 168 教师标签（1126 条；分母 1026）。

    - 固定分母：教师有 kp 标签且模型非 non_content（360: 327，288: 270，310: 273，第四批: 156）。
    - 指标：模块命中 / exact / any；v3 / v4 / v5 / v6 / v7 同分母对比。
    - 23 条第四批目标逐块 before/after + v6 历史 8 条目标不回退 + 反样本守卫 + 新 harmed。
    - 全量 v6→v7 变化清单（teacher 27 / model 9）与 671 model 行变化逐条审计。
    - 产物：mapped_1797_reviewed_v7.json（teacher 1126 行逐字段取自 reviewed_round4；
      model 671 行用 v7 映射；teacher_version 逐行保留）。
    """
    mapped = json.loads(MAPPED.read_text(encoding='utf-8'))['items']
    v7_by = {x['block_id']: x for x in mapped}
    v6_by = {x['block_id']: x for x in json.loads(V6_MAPPED.read_text(encoding='utf-8'))['items']}
    v5_by = {x['block_id']: x for x in json.loads(V5_MAPPED.read_text(encoding='utf-8'))['items']}
    v4_by = {x['block_id']: x for x in json.loads(V4_MAPPED.read_text(encoding='utf-8'))['items']}
    v3_by = {x['block_id']: x for x in json.loads(V3_MAPPED.read_text(encoding='utf-8'))['items']}
    base_items = json.loads(REVIEWED_ROUND4.read_text(encoding='utf-8'))['items']
    base_by = {x['block_id']: x for x in base_items}
    teacher_items = [x for x in base_items if x.get('review_status') == 'teacher']
    model_items = [x for x in base_items if x.get('review_status') == 'model']
    teacher_ids = [x['block_id'] for x in teacher_items]
    model_ids = [x['block_id'] for x in model_items]

    BATCHES = [('360', 'textbook-review-2026-11-06'),
               ('288', 'textbook-review-v4-round2-2026-11-06'),
               ('310', 'textbook-review-v5-round3-2026-11-07'),
               ('round4', 'textbook-review-v6-round4-2026-11-07')]
    ver_items = collections.defaultdict(list)
    for x in teacher_items:
        ver_items[x.get('teacher_version') or ''].append(x)
    subsets = {}
    for name, ver in BATCHES:
        subsets[name] = _den(ver_items.get(ver, []))
    den_all = subsets['360'] + subsets['288'] + subsets['310'] + subsets['round4']
    subsets['total_1026'] = den_all

    def five_way(den):
        return {'n': len(den), 'v3': _metrics(den, v3_by), 'v4': _metrics(den, v4_by),
                'v5': _metrics(den, v5_by), 'v6': _metrics(den, v6_by),
                'v7': _metrics(den, v7_by)}

    metrics = {k: five_way(v) for k, v in subsets.items()}
    m = metrics

    def kp_of(by, bid):
        x = by.get(bid)
        return (x.get('kp_primary') or '') if x else ''

    # ── 第四批 23 条目标（v6 错、教师对）────────────────────────────────────
    TARGET_IDS = [
        'TB-B1-0076-1-p0076-01',   # 3.1 分段函数解析式
        'TB-B1-0151-2-p0151-02',   # 4.5.2 二分法求方程近似解
        'TB-B1-0158-2-p0158-02',   # 4.5.3 函数模型增长比较
        'TB-B1-0191-2-p0191-02',   # 5.2 同角关系恒等式
        'TB-B1-0256-2-p0256-02',   # 5.7 三角函数应用结论
        'TB-B2-0030-1-p0030-01',   # 6.2.4 向量作图/化简
        'TB-B2-0030-4-p0030-04',   # 6.2.4 向量位移合成
        'TB-B2-0032-2-p0032-02',   # 6.3 平面向量基本定理（分解）
        'TB-B2-0039-2-p0039-02',   # 6.3.4 中点/三等分点坐标
        'TB-B2-0057-1-p0057-01',   # 6.4.3 解三角形应用（测量高度）
        'TB-B2-0058-1-p0058-01',   # 6.4.3 解三角形应用（测量角度）
        'TB-B2-0071-2-p0071-02',   # 6.4.3 向量法研究三角形
        'TB-B2-0087-3-p0087-03',   # 7.2 复数乘除运算续块
        'TB-B2-0095-1-p0095-01',   # 7.3 复数乘除几何意义
        'TB-B2-0159-1-p0159-01',   # 8.6.2 直线与平面所成的角
        'TB-B2-0162-1-p0162-01',   # 8.6.2 棱台体积推导
        'TB-B2-0211-1-p0211-01',   # 9.2 百分位数估计
        'TB-B2-0222-2-p0222-02',   # 9.2.3 方差/标准差
        'TB-B2-0233-1-p0233-01',   # 9.3 阶梯电价（百分位数）
        'TB-B2-0274-2-p0274-02',   # 10.3 事件独立性假设
        'TB-B3-0150-1-p0150-01',   # 3.3.2 椭圆轨道复习题
        'TB-B5-0088-2-p0088-02',   # 5.2.2 牛顿法迭代求零点
        'TB-B5-0091-2-p0091-02',   # 5.3 导数判断单调性
    ]
    # v6 历史目标（第三批 8 条）：v7 不得回退
    V6_TARGETS = [
        'TB-B1-0101-1-p0101-01', 'TB-B1-0155-2-p0155-02', 'TB-B1-0162-1-p0162-01',
        'TB-B1-0254-2-p0254-02', 'TB-B2-0061-3-p0061-03', 'TB-B2-0068-1-p0068-01',
        'TB-B2-0154-1-p0154-01', 'TB-B5-0064-1-p0064-01',
    ]
    # 同规则顺带修正（非 23 条目标；逐条解释见报告）
    EXPECTED_EXTRA = {
        'TB-B2-0060-2-p0060-02': '同 6.4.3 解三角形应用规则顺带修正（教师=apply，v6=concept 历史错块；净收益）',
        'TB-B2-0223-1-p0223-01': '同 9.2.3 方差/标准差规则顺带修正（教师=central，v6=histogram）',
        'TB-B5-0090-3-p0090-03': '同 5.3 导数判断单调性规则顺带修正（教师=monotonic，v6=tangent）',
        'TB-B2-0102-1-p0102-01': '教师行（教师只给模块/无 kp，reviewed 中原样保留）；模型侧标签 concept→geometric，'
                                 '仅 mapped 层变化，不影响教师标签',
    }
    # 671 model 行里被新规则顺带改写的 9 条（无教师标签；逐条人工核对为“同向更正确”，见报告 §6）
    EXPECTED_MODEL = {
        'TB-B2-0029-2-p0029-02': '习题6.2 位移合成题（含“两次位移的合成”）→ 向量概念/线性运算，v6 的 dot 无数量积证据',
        'TB-B2-0034-2-p0034-02': '习题6.3 用 a,b 基底表示向量（用基底表示 CD/CE）→ 分解，v6 的 coordinate 无坐标运算证据',
        'TB-B2-0040-1-p0040-01': '例题续块：三等分点坐标公式推导 → 坐标表示',
        'TB-B2-0040-2-p0040-02': '习题：线段 AB 的三等分点求坐标 → 坐标表示',
        'TB-B2-0044-1-p0044-01': '综合运用：平行四边形三等分点 + 用基底表示 → 坐标表示（块内含“三等分点/坐标”）',
        'TB-B2-0056-1-p0056-01': '6.4.3 应用举例 例9（测量河对岸两点距离，基线/测量方案）→ 解三角形应用',
        'TB-B2-0094-1-p0094-01': '7.3.2 复数乘除运算的三角表示及其几何意义 → 复平面几何意义',
        'TB-B2-0161-1-p0161-01': '8.6.2 例5/例6（例6 推导棱台的体积公式）→ 表面积与体积（与 0162-1 教师标签同向）',
        'TB-B5-0090-2-p0090-02': '5.3.1 导数正负与函数单调性（h′(t)<0 ⇒ 单调递减）→ 单调性讨论',
    }
    label_by = {x['block_id']: x['teacher_kp'] for x in den_all}
    target_check = []
    for bid in TARGET_IDS:
        tk = label_by.get(bid, '')
        row = {'block_id': bid, 'section': v7_by[bid].get('section', ''),
               'section_num': v7_by[bid].get('section_num', ''),
               'teacher_kp': tk, 'v3': kp_of(v3_by, bid), 'v4': kp_of(v4_by, bid),
               'v5': kp_of(v5_by, bid), 'v6': kp_of(v6_by, bid), 'v7': kp_of(v7_by, bid),
               'rule_v6': v6_by[bid].get('rule', ''), 'rule_v7': v7_by[bid].get('rule', ''),
               'fixed': kp_of(v6_by, bid) != tk and kp_of(v7_by, bid) == tk}
        target_check.append(row)
    targets_fixed = sum(1 for c in target_check if c['fixed'])
    v6_target_check = []
    for bid in V6_TARGETS:
        tk = base_by[bid].get('teacher_kp', '')
        v6_target_check.append({'block_id': bid, 'teacher_kp': tk,
                                'v6': kp_of(v6_by, bid), 'v7': kp_of(v7_by, bid),
                                'still_fixed': kp_of(v7_by, bid) == tk})
    v6_targets_kept = sum(1 for c in v6_target_check if c['still_fixed'])

    # ── 反样本守卫（新规则命中面的反向样本，逐条核对）────────────────────────
    GUARDS = [
        ('TB-B1-0073-3-p0073-03', 'kp_02_01_concept', '3.1 含 {…} 分段公式但无“解析式为”，不被分段规则抢走'),
        ('TB-B1-0080-1-p0080-01', 'kp_02_01_concept', '3.1 分段公式题组（无“解析式为”）保持 concept'),
        ('TB-B1-0075-1-p0075-01', 'kp_02_13_segment', '3.1 既有“分段”规则仍先命中'),
        ('TB-B1-0153-1-p0153-01', 'kp_02_09_logarithm', '4.5 例2 正文含“用二分法求方程的近似解”但非小节标题，不被抢走'),
        ('TB-B1-0157-3-p0157-03', 'kp_02_12_abstract', '4.5.3 增长比较规则命中但标签不变'),
        ('TB-B1-0159-1-p0159-01', 'kp_02_12_abstract', '4.5.3 增长比较规则命中但标签不变'),
        ('TB-B1-0162-2-p0162-02', 'kp_02_08_exponential', '浮萍 y=a^t 仍命中指数规则'),
        ('TB-B1-0186-1-p0186-01', 'kp_04_01_definition', '5.2 定义证明块（求证 sinα=y/r）不被同角规则抢走'),
        ('TB-B1-0254-1-p0254-01', 'kp_04_05_graph', '5.7 潮汐演算块不含“消峰平谷”，保持 graph'),
        ('TB-B2-0024-1-p0024-01', 'kp_05_03_dot', '6.2.4 数量积定义块含“位移”但被排除词挡住'),
        ('TB-B2-0032-1-p0032-01', 'kp_05_02_coordinate', '6.3 节导入（基本定理及坐标表示）保持 coordinate'),
        ('TB-B2-0033-1-p0033-01', 'kp_05_06_decompose', '6.3 分解块（按 e1,e2 方向分解）保持 decompose'),
        ('TB-B2-0060-1-p0060-01', 'kp_04_09_cosine', '6.4.3 “分别根据下列条件”块保持 cosine'),
        ('TB-B2-0062-1-p0062-01', 'kp_05_01_concept', '6.4.3 海伦/秦九韶阅读材料被排除词挡住'),
        ('TB-B2-0068-1-p0068-01', 'kp_04_09_cosine', '6.4.3 解三角形模板块保持 cosine'),
        ('TB-B2-0070-1-p0070-01', 'kp_05_03_dot', '6.4.3 数学探究导语块保持原有标签'),
        ('TB-B2-0085-2-p0085-02', 'kp_06_03_modulus', '7.2 (1+i)² 块保持 modulus'),
        ('TB-B3-0139-1-p0139-01', 'kp_09_07_parabola', '3.3.2 抛物线正文（类比椭圆）保持 parabola'),
        ('TB-B2-0158-1-p0158-01', 'kp_08_05_perpendicular', '8.6.2 线面垂直判定块保持 perpendicular'),
        ('TB-B2-0163-1-p0163-01', 'kp_08_06_angle', '8.6.2 二面角定义块保持 angle'),
        ('TB-B2-0209-1-p0209-01', 'kp_10_02_histogram', '9.2.2 小节标题“总体百分位数的估计”块保持 histogram'),
        ('TB-B2-0219-1-p0219-01', 'kp_10_03_central', '9.2.3 极差/离散程度块保持 central'),
        ('TB-B2-0273-2-p0273-02', 'kp_10_04_classical', '10.3 复习题“事件A与B相互独立吗”保持 classical'),
        ('TB-B5-0087-3-p0087-03', 'kp_03_01_compute', '5.2.2 牛顿法导语块（无“代替”）保持 compute'),
        ('TB-B5-0088-1-p0088-01', 'kp_03_02_tangent', '5.2.2 牛顿法首块保持 tangent'),
        ('TB-B5-0103-1-p0103-01', 'kp_03_04_extremum', '5.3 极值块由既有极值规则先命中'),
        ('TB-B5-0100-3-p0100-03', 'kp_03_01_compute', '5.3 图象/特殊点续块保持 compute'),
    ]
    guard_check = []
    for bid, exp, note in GUARDS:
        p6, p7 = kp_of(v6_by, bid), kp_of(v7_by, bid)
        kept = p7 == exp
        guard_check.append({'block_id': bid, 'expect': exp, 'v6': p6, 'v7': p7,
                            'kept': kept, 'note': note})

    # ── v6→v7 口径变化：fixed / harmed / still_wrong ─────────────────────────
    fixed, harmed, still_wrong = [], [], []
    for r in den_all:
        bid = r['block_id']
        tk = r['teacher_kp']
        p6, p7 = kp_of(v6_by, bid), kp_of(v7_by, bid)
        row = {'block_id': bid, 'teacher_kp': tk, 'v6': p6, 'v7': p7,
               'section': v7_by[bid].get('section', ''),
               'section_num': v7_by[bid].get('section_num', ''),
               'rule_v7': v7_by[bid].get('rule', '')}
        if p6 != tk and p7 == tk:
            fixed.append(row)
        elif p6 == tk and p7 != tk:
            harmed.append(row)
        elif p6 != tk and p7 != tk:
            still_wrong.append(row)

    # ── v6→v7 全量变化审计（mapped 1797）────────────────────────────────────
    all_changes = []
    for x in mapped:
        bid = x['block_id']
        o = v6_by[bid]
        if (o['kp_primary'] or '') != x['kp_primary'] or o['status'] != x['status'] \
                or list(o['kp_secondary']) != list(x['kp_secondary']):
            all_changes.append({'block_id': bid, 'book': x['book'][-10:],
                                'section': x.get('section', ''),
                                'section_num': x.get('section_num', ''),
                                'before': o['kp_primary'] or '∅', 'after': x['kp_primary'] or '∅',
                                'before_status': o['status'], 'after_status': x['status'],
                                'rule': x.get('rule', ''), 'reason': x.get('reason', ''),
                                'teacher_kp': base_by[bid].get('teacher_kp', ''),
                                'is_teacher_row': base_by[bid].get('review_status') == 'teacher',
                                'is_target': bid in set(TARGET_IDS),
                                'extra_note': EXPECTED_EXTRA.get(bid, ''),
                                'text': x['text'][:180]})
    changed_model = [c for c in all_changes if not c['is_teacher_row']]
    changed_teacher_ids = {c['block_id'] for c in all_changes if c['is_teacher_row']}
    unexpected = sorted(set(c['block_id'] for c in all_changes)
                        - set(TARGET_IDS) - set(EXPECTED_EXTRA) - set(EXPECTED_MODEL))
    unaudited_model = sorted(set(c['block_id'] for c in changed_model) - set(EXPECTED_MODEL))
    missing_targets = sorted(set(TARGET_IDS)
                             - {c['block_id'] for c in all_changes if c['is_target']})
    model_changes = []
    for bid in model_ids:
        a, b = v6_by[bid], v7_by[bid]
        if (a['kp_primary'] or '') != (b['kp_primary'] or '') or a['status'] != b['status'] \
                or list(a['kp_secondary']) != list(b['kp_secondary']):
            model_changes.append({'block_id': bid, 'before': a['kp_primary'] or '∅',
                                  'after': b['kp_primary'] or '∅',
                                  'section': b.get('section', ''),
                                  'rule': b.get('rule', ''),
                                  'reason': b.get('reason', ''),
                                  'audit_note': EXPECTED_MODEL.get(bid, ''),
                                  'text': b['text'][:150]})

    # ── reviewed_v7：teacher 1126 行逐字段原样保留；model 671 行用 v7 ────────
    rev_items = []
    for old in base_items:
        bid = old['block_id']
        if old.get('review_status') == 'teacher':
            rev_items.append(old)
            continue
        x = v7_by[bid]
        item = {k: old.get(k) for k in old.keys()}
        item.update({
            'kp_primary': x['kp_primary'], 'module': x['module'], 'kp_name': x['kp_name'],
            'kp_secondary': x['kp_secondary'], 'confidence': x['confidence'],
            'reason': x['reason'], 'status': x['status'],
            'module_id': x.get('module_id', ''), 'module_name': x.get('module_name', ''),
            'model_primary': x['kp_primary'], 'model_secondary': x['kp_secondary'],
            'model_status': x['status'], 'teacher_module': '', 'teacher_kp': '',
            'review_status': 'model'})
        rev_items.append(item)
    REVIEWED.write_text(json.dumps({'count': len(rev_items),
                                    'teacher_count': sum(1 for x in rev_items
                                                         if x['review_status'] == 'teacher'),
                                    'model_version': MODEL_VERSION,
                                    'items': rev_items}, ensure_ascii=False, indent=1),
                        encoding='utf-8')
    rev_by = {x['block_id']: x for x in rev_items}
    teacher_diff = sum(1 for bid in teacher_ids if rev_by[bid] != base_by[bid])
    teacher_ver_lost = sum(1 for bid in teacher_ids
                           if rev_by[bid].get('teacher_version') != base_by[bid].get('teacher_version'))
    ver = collections.Counter(base_by[bid].get('teacher_version', '') for bid in teacher_ids)

    st_v7 = collections.Counter(x['status'] for x in mapped)
    st_rev = collections.Counter(x['status'] for x in rev_items)
    st_teacher = collections.Counter(base_by[bid]['status'] for bid in teacher_ids)
    st_model_v7 = collections.Counter(x['status'] for x in mapped if x['block_id'] in set(model_ids))
    rule_hits = collections.Counter(x.get('rule', '').split(':')[0] for x in mapped)

    checks = {
        'teacher_labels': len(teacher_ids),
        'teacher_labels_360': len(ver_items.get(BATCHES[0][1], [])),
        'teacher_labels_288': len(ver_items.get(BATCHES[1][1], [])),
        'teacher_labels_310': len(ver_items.get(BATCHES[2][1], [])),
        'teacher_labels_round4': len(ver_items.get(BATCHES[3][1], [])),
        'denominator': len(den_all),
        'denominator_360': len(subsets['360']),
        'denominator_288': len(subsets['288']),
        'denominator_310': len(subsets['310']),
        'denominator_round4': len(subsets['round4']),
        'targets_fixed': targets_fixed,
        'targets_total': len(TARGET_IDS),
        'v6_targets_kept': v6_targets_kept,
        'v6_targets_total': len(V6_TARGETS),
        'fixed': len(fixed),
        'new_harmed': len(harmed),
        'still_wrong': len(still_wrong),
        'exact_360_v6': m['360']['v6']['exact'], 'exact_360_v7': m['360']['v7']['exact'],
        'exact_288_v6': m['288']['v6']['exact'], 'exact_288_v7': m['288']['v7']['exact'],
        'exact_310_v6': m['310']['v6']['exact'], 'exact_310_v7': m['310']['v7']['exact'],
        'exact_round4_v6': m['round4']['v6']['exact'], 'exact_round4_v7': m['round4']['v7']['exact'],
        'module_360_v6': m['360']['v6']['module'], 'module_360_v7': m['360']['v7']['module'],
        'module_288_v6': m['288']['v6']['module'], 'module_288_v7': m['288']['v7']['module'],
        'module_310_v6': m['310']['v6']['module'], 'module_310_v7': m['310']['v7']['module'],
        'module_round4_v6': m['round4']['v6']['module'], 'module_round4_v7': m['round4']['v7']['module'],
        'exact_total_v6': m['total_1026']['v6']['exact'],
        'exact_total_v7': m['total_1026']['v7']['exact'],
        'module_total_v6': m['total_1026']['v6']['module'],
        'module_total_v7': m['total_1026']['v7']['module'],
        'any_total_v6': m['total_1026']['v6']['any'],
        'any_total_v7': m['total_1026']['v7']['any'],
        'changed_v6_to_v7_mapped': len(all_changes),
        'changed_teacher_rows': len(changed_teacher_ids),
        'changed_model_rows': len(changed_model),
        'expected_model_changes': len(EXPECTED_MODEL),
        'unaudited_model_changes': unaudited_model,
        'unexpected_changes': unexpected,
        'missing_targets': missing_targets,
        'guard_kept': sum(1 for c in guard_check if c['kept']),
        'guard_total': len(guard_check),
        'reviewed_count': len(rev_items),
        'reviewed_teacher': len(teacher_ids),
        'reviewed_model': len(model_ids),
        'teacher_rows_diff': teacher_diff,
        'teacher_version_lost': teacher_ver_lost,
        'mapped_count': len(mapped),
        'mapped_unique_block_id': len({x['block_id'] for x in mapped}),
        'teacher_version': dict(ver),
        'status_v7_mapped': dict(st_v7),
        'status_reviewed_v7': dict(st_rev),
        'status_teacher': dict(st_teacher),
        'status_model_v7': dict(st_model_v7),
        'rule_hits': dict(rule_hits),
    }
    result = {
        'model_version': MODEL_VERSION,
        'metrics': metrics,
        'target_check': target_check,
        'v6_target_check': v6_target_check,
        'guard_check': guard_check,
        'fixed': fixed,
        'harmed': harmed,
        'still_wrong': still_wrong,
        'changes_v6_to_v7': all_changes,
        'model_row_changes': model_changes,
        'expected_model_changes': EXPECTED_MODEL,
        'checks': checks,
    }
    EVAL.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')

    print(f"[v7-eval] 分母 {len(den_all)}（360:{len(subsets['360'])} + 288:{len(subsets['288'])}"
          f" + 310:{len(subsets['310'])} + round4:{len(subsets['round4'])}）；教师标签 {len(teacher_ids)}")
    print(f"[v7-eval] 360 v6 {m['360']['v6']['exact']}/{m['360']['v6']['n']}"
          f" → v7 {m['360']['v7']['exact']}/{m['360']['v7']['n']}；"
          f"288 v6 {m['288']['v6']['exact']}/{m['288']['v6']['n']}"
          f" → v7 {m['288']['v7']['exact']}/{m['288']['v7']['n']}；"
          f"310 v6 {m['310']['v6']['exact']}/{m['310']['v6']['n']}"
          f" → v7 {m['310']['v7']['exact']}/{m['310']['v7']['n']}；"
          f"round4 v6 {m['round4']['v6']['exact']}/{m['round4']['v6']['n']}"
          f" → v7 {m['round4']['v7']['exact']}/{m['round4']['v7']['n']}；"
          f"合计 v6 {m['total_1026']['v6']['exact']}/{m['total_1026']['n']}"
          f" → v7 {m['total_1026']['v7']['exact']}/{m['total_1026']['n']}")
    print(f"[v7-eval] 模块命中 360 {m['360']['v7']['module']}/{m['360']['v7']['n']}、"
          f"288 {m['288']['v7']['module']}/{m['288']['v7']['n']}、"
          f"310 {m['310']['v7']['module']}/{m['310']['v7']['n']}、"
          f"round4 {m['round4']['v7']['module']}/{m['round4']['v7']['n']}、"
          f"合计 {m['total_1026']['v7']['module']}")
    print(f"[v7-eval] 23 条目标修复 {targets_fixed}/23；v6 历史 8 条目标保持 {v6_targets_kept}/8；"
          f"fixed {len(fixed)} / harmed {len(harmed)} / still_wrong {len(still_wrong)}；"
          f"守卫 {sum(1 for c in guard_check if c['kept'])}/{len(guard_check)}")
    print(f"[v7-eval] mapped v6→v7 变化 {len(all_changes)} 块（teacher {len(changed_teacher_ids)} /"
          f" model {len(changed_model)}）；意外变化 {unexpected}；目标缺失 {missing_targets}；"
          f"model 变化未审计 {unaudited_model}")
    print(f"[v7-eval] reviewed {len(rev_items)}（teacher {len(teacher_ids)} / model {len(model_ids)}）；"
          f"teacher 行 diff {teacher_diff}；teacher_version {dict(ver)}")
    print(f"[v7-eval] 产物：{EVAL} / {REVIEWED}")
    bad = harmed or teacher_diff or teacher_ver_lost or unexpected or missing_targets \
        or unaudited_model or sum(1 for c in guard_check if not c['kept']) \
        or targets_fixed != len(TARGET_IDS)
    if bad:
        print('[v7-eval] WARN: 存在 harmed / 意外变化 / 守卫破坏 / 目标未修 / teacher 行差异')
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='教材映射 v7（v6 规则引擎 + 22 条窄条件修正）')
    ap.add_argument('--stage', choices=['map', 'eval'], default='map')
    args = ap.parse_args(argv)
    if args.stage == 'map':
        return stage_map(args)
    return stage_eval(args)


if __name__ == '__main__':
    sys.exit(main())
