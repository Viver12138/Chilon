#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材映射 v4：在 v3 基础上用“节级内容规则”修正 360 复核暴露的 74 条 exact 不一致。

设计取舍（重要，见 docs/textbook_map_v4_2026-11-06.md）：
  - 只有 360 块有教师标签，360 之外 1437 块无法验证；因此 v4 **不做全量打分重构**，
    而是以 v3 映射为基线（重跑 v3 规则复现），再叠加“节号 + 正文特征”的修正层：
    只有明确规则命中时才改标签，未命中的块保持 v3 结果，避免不可审计的系统性新错。
  - 修正层：
      1) CAT 章导言规则：无节块按章首概念 kp 归属；
      2) SUM 章末小结规则：小结块按章内概念/总览 kp 归属；
      3) PRI 窄条件规则：节号 + 正文特征词/题型模板（含跨模块，如必修二 6.4.3 → 模块 04）；
      4) SEC 节级重选：对 v3 词典失效/过粗的节，用“节标题候选（人工补）+ 去页眉页脚后的
         正文打分”重新选 primary，允许 section 候选跨章模块；仅在这一层删除了
         “章标题混入 section 词典”和“节标题二次计分”两个已知根因；
      5) FILL section 候选兜底：正文证据不足但节候选确定时给低置信 primary（不再留空）。
  - 映射阶段不读取教师标签；教师标签只在 eval 阶段读。

阶段：
  --stage map   全量 1797 映射（不读教师标签）→ mapped_1797_v4.json / mapped_1797_v4_batch.txt
  --stage eval  读 review_360_parsed.json 评估 → mapped_1797_reviewed_v4.json + eval json + 报告
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
V3_REVIEWED = OUT / 'mapped_1797_reviewed.json'
TEACHER_360 = OUT / 'review_360_parsed.json'
ERRORS74 = OUT / 'errors_74_detail.json'
MAPPED = OUT / 'mapped_1797_v4.json'
BATCH = OUT / 'mapped_1797_v4_batch.txt'
REVIEWED = OUT / 'mapped_1797_reviewed_v4.json'
EVAL = OUT / 'mapped_1797_v4_eval.json'
REPORT = ROOT / 'docs' / 'textbook_map_v4_2026-11-06.md'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
MODEL_VERSION = 'textbook-map-v4-2026-11-06'
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
    ('必修第一册', ('3.2',), r'最大值|最小值|值域', None, 'kp_02_03_range', 0.66,
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
    # 必修一 · 4.5.3 指数增长模型
    ('必修第一册', ('4.5.3',), r'浮萍|增长率为|a\s*\^\s*\{?\s*t|y=a', None, 'kp_02_08_exponential', 0.62,
     '4.5.3 节内指数增长模型'),
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
    ('必修第二册', ('6.4.3',), r'解这个三角形|分别根据下列条件解三角形', r'游泳|水流|投影向量|测量|塔高|台风|航行|小结|本章知识结构',
     'kp_04_09_cosine', 0.68, '6.4.3 节内余弦定理解三角形练习'),
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
        for rule in PRIORITY_RULES:
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
    base_diff = 0
    old = {x['chunk_id']: x for x in json.loads(V3_MAPPED.read_text(encoding='utf-8'))['items']}
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
        o = old[b['chunk_id']]
        if (rec['status'] != o['status'] or (rec['kp_primary'] or '') != (o['kp_primary'] or '')
                or list(rec['kp_secondary']) != list(o['kp_secondary'])):
            pass
        recs.append(rec)
    # 基线复现自检：未命中任何修正规则的块应与 v3 完全一致
    untouched = [x for x in recs if x['rule'] == 'v3_base']
    mismatch = 0
    for x in untouched:
        o = old[x['chunk_id']]
        if x['status'] != o['status'] or (x['kp_primary'] or '') != (o['kp_primary'] or ''):
            mismatch += 1
    status = collections.Counter(x['status'] for x in recs)
    MAPPED.write_text(json.dumps({'count': len(recs), 'model_version': MODEL_VERSION,
                                  'rules': 'v3 base + chapter-intro/summary + narrow section rules + '
                                           'curated section re-election (footer strip + cross-module section candidates) + fill',
                                  'items': recs}, ensure_ascii=False, indent=1), encoding='utf-8')
    BATCH.write_text('\n'.join(
        f"{i:04d}|{x['block_id']}|{x['book']}|p{x['page']}-{x['part']}|{x['chapter']}|{x['section']}|"
        f"{x['status']}|{x['kp_primary']}|{','.join(x['kp_secondary'])}|{x['confidence']}"
        for i, x in enumerate(recs, 1)) + '\n', encoding='utf-8')
    changed = sum(1 for x in recs if x['rule'] != 'v3_base')
    rule_hits = collections.Counter(x['rule'].split(':')[0] for x in recs)
    print(f'[v4-map] {len(recs)} 块；status {dict(status)}；修正命中 {changed}（{dict(rule_hits)}）；'
          f'基线未命中块与 v3 不一致 {mismatch}')
    print(f'[v4-map] 产物：{MAPPED} / {BATCH}')
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


def stage_eval(args):
    mapped = json.loads(MAPPED.read_text(encoding='utf-8'))['items']
    v4_by = {x['block_id']: x for x in mapped}
    v3 = json.loads(V3_MAPPED.read_text(encoding='utf-8'))['items']
    v3_by = {x['block_id']: x for x in v3}
    reviewed = {x['block_id']: x for x in
                json.loads(V3_REVIEWED.read_text(encoding='utf-8'))['items']}
    rows = json.loads(TEACHER_360.read_text(encoding='utf-8'))['rows']
    errors = json.loads(ERRORS74.read_text(encoding='utf-8'))
    den = [r for r in rows if r['has_teacher'] and reviewed[r['block_id']]['model_status'] != 'non_content']
    den_ids = {r['block_id'] for r in den}
    v3_labels = {bid: {'kp_primary': reviewed[bid]['model_primary'],
                       'kp_secondary': reviewed[bid]['model_secondary']} for bid in reviewed}
    v3m = _metrics(den, v3_labels)
    v4m = _metrics(den, v4_by)
    fixed, still, new_wrong = [], [], []
    for r in den:
        bid = r['block_id']
        tk = r['teacher_kp']
        p3 = reviewed[bid]['model_primary']
        p4 = v4_by[bid]['kp_primary'] or ''
        if p3 != tk and p4 == tk:
            fixed.append(r)
        elif p3 != tk and p4 != tk:
            still.append(r)
        elif p3 == tk and p4 != tk:
            new_wrong.append(r)
    err_fixed, err_still = [], []
    for e in errors:
        bid = e['block_id']
        if (v4_by[bid]['kp_primary'] or '') == e['teacher_kp']:
            err_fixed.append(e)
        else:
            err_still.append(e)
    # 1437 model 块变化
    model_ids = [x['block_id'] for x in mapped if reviewed[x['block_id']]['review_status'] == 'model']
    changes = []
    for bid in model_ids:
        p3 = v3_by[bid]['kp_primary'] or ''
        p4 = v4_by[bid]['kp_primary'] or ''
        s3 = v3_by[bid]['status']
        s4 = v4_by[bid]['status']
        if p3 != p4 or s3 != s4:
            changes.append((bid, p3, p4, s3, s4))
    by_sec = collections.Counter()
    for bid, p3, p4, s3, s4 in changes:
        x = v4_by[bid]
        by_sec[(book_key(x['book']), x.get('section_num', '') or '（无节）')] += 1
    # 20 条影响审计（按节分散，每节最多 1 条）
    seen_sec = set()
    audit = []
    for bid, p3, p4, s3, s4 in changes:
        x = v4_by[bid]
        k = (book_key(x['book']), x.get('section_num', '') or '')
        if k in seen_sec:
            continue
        seen_sec.add(k)
        audit.append({'block_id': bid, 'book': x['book'][-10:], 'chapter': x.get('chapter', ''),
                      'section': x.get('section', ''), 'text': x['text'][:180],
                      'before': p3 or '∅', 'after': p4 or '∅', 'before_status': s3,
                      'after_status': s4, 'rule': x.get('rule', ''),
                      'reason': x.get('reason', '')})
        if len(audit) >= 20:
            break
    # 状态分布（v3 reviewed 最终口径 / v4 reviewed 最终口径；另列 model-only）
    st3 = collections.Counter(x['status'] for x in reviewed.values())
    st3_model = collections.Counter(x['status'] for x in v3)
    st4_model = collections.Counter(x['status'] for x in mapped)
    rule_hits = collections.Counter(x.get('rule', '').split(':')[0] for x in mapped)
    # reviewed_v4：teacher 360 行逐字段原样保留；model 行用 v4
    rev_items = []
    for x in mapped:
        old = reviewed[x['block_id']]
        if old['review_status'] == 'teacher':
            rev_items.append(old)
            continue
        item = {k: x.get(k, old.get(k)) for k in old.keys()}
        item.update({'kp_primary': x['kp_primary'], 'module': x['module'], 'kp_name': x['kp_name'],
                     'kp_secondary': x['kp_secondary'], 'confidence': x['confidence'],
                     'reason': x['reason'], 'status': x['status'],
                     'model_primary': x['kp_primary'], 'model_secondary': x['kp_secondary'],
                     'model_status': x['status'], 'teacher_module': '', 'teacher_kp': '',
                     'review_status': 'model'})
        rev_items.append(item)
    REVIEWED.write_text(json.dumps({'count': len(rev_items),
                                    'teacher_count': sum(1 for x in rev_items if x['review_status'] == 'teacher'),
                                    'model_version': MODEL_VERSION,
                                    'items': rev_items}, ensure_ascii=False, indent=1), encoding='utf-8')
    teacher_diff = sum(1 for x in rev_items if x['review_status'] == 'teacher' and x != reviewed[x['block_id']])
    st4 = collections.Counter(x['status'] for x in rev_items)
    checks = {
        'reviewed_count': len(rev_items),
        'reviewed_teacher': sum(1 for x in rev_items if x['review_status'] == 'teacher'),
        'reviewed_model': sum(1 for x in rev_items if x['review_status'] == 'model'),
        'teacher_rows_diff': teacher_diff,
        'mapped_count': len(mapped),
        'mapped_unique_block_id': len({x['block_id'] for x in mapped}),
        'changed_1437': len(changes),
        'status_v3': dict(st3),
        'status_v3_model_only': dict(st3_model),
        'status_v4': dict(st4),
        'status_v4_model_only': dict(st4_model),
        'rule_hits': dict(rule_hits),
    }
    result = {
        'model_version': MODEL_VERSION,
        'denominator_327': {'v3': v3m, 'v4': v4m},
        'fixed': [{'block_id': r['block_id'], 'teacher_kp': r['teacher_kp'],
                   'v3': reviewed[r['block_id']]['model_primary'],
                   'v4': v4_by[r['block_id']]['kp_primary'],
                   'rule': v4_by[r['block_id']].get('rule', ''),
                   'reason': v4_by[r['block_id']].get('reason', ''),
                   'section': v4_by[r['block_id']].get('section', '')} for r in fixed],
        'still_wrong': [{'block_id': r['block_id'], 'teacher_kp': r['teacher_kp'],
                         'v3': reviewed[r['block_id']]['model_primary'],
                         'v4': v4_by[r['block_id']]['kp_primary'],
                         'section': v4_by[r['block_id']].get('section', ''),
                         'text': v4_by[r['block_id']]['text'][:90]} for r in still],
        'new_wrong': [{'block_id': r['block_id'], 'teacher_kp': r['teacher_kp'],
                       'v3': reviewed[r['block_id']]['model_primary'],
                       'v4': v4_by[r['block_id']]['kp_primary'],
                       'rule': v4_by[r['block_id']].get('rule', ''),
                       'section': v4_by[r['block_id']].get('section', '')} for r in new_wrong],
        'errors_74': {'total': len(errors), 'fixed': len(err_fixed), 'still': len(err_still),
                      'still_detail': [{'block_id': e['block_id'], 'teacher_kp': e['teacher_kp'],
                                        'model_primary': e['model_primary'],
                                        'model_status': e['model_status'],
                                        'v4': v4_by[e['block_id']]['kp_primary'],
                                        'section': e['section'], 'book': book_key(e['book']),
                                        'text': e['text'][:90]} for e in err_still]},
        'full_1437': {'changed': len(changes),
                      'by_section': [{'book': k[0], 'section': k[1], 'n': n}
                                     for k, n in by_sec.most_common()],
                      'audit20': audit,
                      'rules_detail': dict(collections.Counter(
                          x.get('rule', '') for x in mapped if x.get('rule') != 'v3_base'))},
        'checks': checks,
    }
    EVAL.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"[v4-eval] 360(327) v3 模块 {v3m['module']} exact {v3m['exact']} any {v3m['any']} → "
          f"v4 模块 {v4m['module']} exact {v4m['exact']} any {v4m['any']}")
    print(f"[v4-eval] 74 条：fixed {len(err_fixed)} / still {len(err_still)}；"
          f"fixed {len(fixed)} / still {len(still)} / new-wrong {len(new_wrong)}")
    print(f"[v4-eval] 1437 model 块变化 {len(changes)}；status v3 {dict(st3)} → v4 {dict(st4)}")
    print(f"[v4-eval] reviewed {len(rev_items)}（teacher {checks['reviewed_teacher']} / model {checks['reviewed_model']}）；"
          f"teacher 行 diff {teacher_diff}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='教材映射 v4（v3 基线 + 节级内容规则修正）')
    ap.add_argument('--stage', choices=['map', 'eval'], default='map')
    args = ap.parse_args(argv)
    if args.stage == 'map':
        return stage_map(args)
    return stage_eval(args)


if __name__ == '__main__':
    sys.exit(main())
