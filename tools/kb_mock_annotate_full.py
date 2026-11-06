#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""931 道模拟题全量知识点标注（120 词表，模型规则 + 词表/legacy 约束）。

流程：
  --stage annotate   读 questions_931.json，输出 annotations_931.json + batch_*.json + annotation_report.md
  --stage import     备份后写 PG knowledge_annotations（mock, classification_source=model,
                     model_version=mock-full-2026-11-06），幂等
  --stage rollback   从 backup_annotations_2026-11-06.json 回滚 mock annotations

标注依据：最终 PG 文本（题干+选项）+ 120 词表名称/定义 + legacy 模块；不复制 pilot 标签，
pilot 仅用于报告对比。每批 100 条，输出覆盖 931/931。

词表默认 `corpus/eval/kp_vocab.md`（仓库内副本），可用环境变量 CHILON_KP_VOCAB 覆盖。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL = ROOT / 'var' / 'mock_annotations' / 'full'
QUESTIONS = FULL / 'questions_931.json'
ANNOTATIONS = FULL / 'annotations_931.json'
REPORT = FULL / 'annotation_report.md'
PILOT = ROOT / 'var' / 'mock_annotations' / 'pilot_100.json'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
BACKUP = FULL / 'backup_annotations_2026-11-06.json'
PG_REPORT = FULL / 'pg_import_report.md'
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
MODEL_VERSION = 'mock-full-2026-11-06'

# 关键词表：kp_id -> [(中文关键词, 权重)]；权重 4=强特征，2=中，1=弱
KEYWORDS = {
    # 01 集合与逻辑
    'kp_01_01_concept': [('集合', 2), ('元素', 1), ('列举法', 3), ('描述法', 3), ('属于', 1)],
    'kp_01_02_relation': [('子集', 4), ('真子集', 4), ('空集', 3), ('集合相等', 3), ('子集个数', 4)],
    'kp_01_03_operation': [('交集', 4), ('并集', 4), ('补集', 4), ('A∩B', 4), ('A∪B', 4), ('∁', 3), ('集合的运算', 4)],
    'kp_01_04_venn': [('韦恩图', 4), ('Venn', 4), ('容斥', 4), ('容斥原理', 4)],
    'kp_01_05_quantifier': [('全称量词', 4), ('存在量词', 4), ('命题的否定', 4), ('∀', 3), ('∃', 3)],
    'kp_01_06_sufficient': [('充分条件', 4), ('必要条件', 4), ('充要条件', 4), ('充分不必要', 5), ('必要不充分', 5)],
    'kp_01_07_proposition': [('四种命题', 4), ('逻辑联结词', 4), ('且命题', 3), ('或命题', 3), ('真假', 1)],
    # 02 函数
    'kp_02_01_concept': [('函数的概念', 4), ('同一函数', 4), ('对应关系', 3), ('定义域', 2), ('值域', 2)],
    'kp_02_02_domain': [('定义域', 5), ('分母不为零', 4), ('偶次根', 3), ('对数真数', 3)],
    'kp_02_03_range': [('值域', 5), ('最大值', 2), ('最小值', 2), ('最值', 2)],
    'kp_02_04_monotonic': [('单调递增', 5), ('单调递减', 5), ('单调区间', 5), ('单调性', 4)],
    'kp_02_05_parity': [('奇函数', 5), ('偶函数', 5), ('奇偶性', 5), ('f(-x)', 3)],
    'kp_02_06_period': [('周期', 5), ('周期性', 5), ('对称轴', 3), ('对称中心', 3)],
    'kp_02_07_transform': [('平移', 3), ('伸缩', 3), ('翻折', 5), ('图像变换', 5), ('向左平移', 4), ('向右平移', 4)],
    'kp_02_08_exponential': [('指数函数', 5), ('指数', 3), ('a^x', 2), ('比较大小', 2)],
    'kp_02_09_logarithm': [('对数函数', 5), ('对数', 4), ('log', 3), ('ln', 3), ('换底', 4)],
    'kp_02_10_power': [('幂函数', 5), ('x^α', 3)],
    'kp_02_11_zero': [('零点', 5), ('零点存在', 5), ('函数零点', 5)],
    'kp_02_12_abstract': [('抽象函数', 5), ('满足f(', 3), ('函数模型', 4), ('实际问题的函数', 4)],
    'kp_02_13_segment': [('分段函数', 5), ('分段', 3)],
    # 03 导数
    'kp_03_01_compute': [('求导', 4), ('导数', 3), ("f'(x)", 3), ('复合函数求导', 4)],
    'kp_03_02_tangent': [('切线', 5), ('切点', 4), ('公切线', 5), ('切线方程', 5)],
    'kp_03_03_monotonic': [('导数', 2), ('单调性', 4), ('单调区间', 3), ('含参讨论', 3)],
    'kp_03_04_extremum': [('极值', 5), ('极大值', 5), ('极小值', 5), ('极值点', 5), ('最值', 2)],
    'kp_03_05_param_hold': [('恒成立', 5), ('存在性', 4), ('任意', 3), ('参数范围', 3), ('分离参数', 4)],
    'kp_03_06_zeros': [('零点个数', 5), ('函数零点', 4), ('交点个数', 4)],
    'kp_03_07_proof': [('证明不等式', 5), ('放缩', 4), ('数列不等式', 4)],
    'kp_03_08_concept': [('平均变化率', 5), ('瞬时变化率', 5), ('导数的几何意义', 5), ('物理意义', 3)],
    # 04 三角函数/解三角形
    'kp_04_01_definition': [('弧度', 4), ('任意角', 4), ('终边', 3), ('三角函数定义', 4)],
    'kp_04_02_identity': [('同角', 4), ('诱导公式', 5), ('平方关系', 3), ('商关系', 3)],
    'kp_04_03_sumdiff': [('两角和', 4), ('两角差', 4), ('和差角', 5), ('辅助角', 4), ('sin(α+β)', 3)],
    'kp_04_04_double': [('二倍角', 5), ('降幂', 5), ('半角', 4)],
    'kp_04_05_graph': [('周期', 3), ('对称轴', 3), ('对称中心', 3), ('单调区间', 3), ('Asin', 4), ('ωx', 3)],
    'kp_04_06_transform': [('平移', 3), ('伸缩', 2), ('图像变换', 4), ('横坐标', 3)],
    'kp_04_07_range': [('值域', 3), ('最值', 2), ('换元', 2)],
    'kp_04_08_sine': [('正弦定理', 5), ('a/sinA', 4), ('外接圆半径', 4)],
    'kp_04_09_cosine': [('余弦定理', 5), ('三边', 2), ('夹角', 2)],
    'kp_04_10_area': [('面积', 4), ('三角形形状', 4), ('判断三角形形状', 5)],
    'kp_04_11_apply': [('测量', 4), ('方位角', 4), ('仰角', 4), ('俯角', 4)],
    # 05 平面向量
    'kp_05_01_concept': [('向量', 2), ('数乘', 3), ('线性运算', 4), ('向量加减', 4)],
    'kp_05_02_coordinate': [('坐标', 2), ('向量的坐标', 4), ('向量坐标', 4)],
    'kp_05_03_dot': [('数量积', 5), ('点乘', 4), ('夹角', 2), ('投影', 2)],
    'kp_05_04_perpendicular': [('垂直', 3), ('平行', 2), ('共线', 2), ('垂直条件', 4)],
    'kp_05_05_modulus': [('向量的模', 4), ('模', 1), ('距离', 1), ('|a|', 2)],
    'kp_05_06_decompose': [('基底', 5), ('分解', 3), ('投影向量', 4)],
    'kp_05_07_collinear': [('三点共线', 5), ('系数和', 4), ('共线定理', 4)],
    'kp_05_08_apply': [('向量与', 3), ('几何综合', 3)],
    # 06 复数
    'kp_06_01_concept': [('实数部', 5), ('虚部', 5), ('纯虚数', 5), ('复数相等', 4), ('复数', 1)],
    'kp_06_02_operation': [('复数', 1), ('分母实数化', 4), ('复数运算', 4), ('化简', 1)],
    'kp_06_03_modulus': [('共轭', 5), ('复数的模', 5), ('|z|', 4), ('zz', 3)],
    'kp_06_04_geometric': [('复平面', 5), ('对应点', 4), ('轨迹', 3), ('几何意义', 3)],
    'kp_06_05_power': [('i的幂', 5), ('i^n', 4), ('虚数单位', 2)],
    # 07 数列
    'kp_07_01_concept': [('数列', 2), ('通项', 2), ('前n项和', 2)],
    'kp_07_02_arithmetic': [('等差', 5), ('公差', 5), ('中项', 3), ('等差中项', 5)],
    'kp_07_03_geometric': [('等比', 5), ('公比', 5), ('等比中项', 5)],
    'kp_07_04_sn': [('Sn', 4), ('前n项和', 4), ('a_n=S_n', 5), ('求a_n', 3)],
    'kp_07_05_summation': [('错位相减', 5), ('裂项', 5), ('分组求和', 5), ('倒序相加', 5), ('求和', 2)],
    'kp_07_06_recurrence': [('递推', 5), ('递推式', 5), ('构造', 4), ('构造等比', 4)],
    'kp_07_07_inequality': [('放缩', 4), ('数列不等式', 5), ('证明不等式', 4)],
    'kp_07_08_induction': [('数学归纳法', 5), ('归纳法', 4)],
    # 08 立体几何
    'kp_08_01_threeview': [('三视图', 5), ('直观图', 4), ('斜二测', 4)],
    'kp_08_02_area_volume': [('表面积', 5), ('体积', 4), ('外接球', 3), ('内切球', 3)],
    'kp_08_03_position': [('位置关系', 5), ('异面直线', 4), ('线面', 2), ('面面', 2)],
    'kp_08_04_parallel': [('线面平行', 5), ('面面平行', 5), ('平行证明', 5)],
    'kp_08_05_perpendicular': [('线面垂直', 5), ('面面垂直', 5), ('垂直证明', 5)],
    'kp_08_06_angle': [('线面角', 5), ('二面角', 5), ('夹角', 2), ('锐钝', 2)],
    'kp_08_07_vector': [('空间向量', 5), ('法向量', 5), ('建系', 4), ('空间直角坐标系', 4)],
    'kp_08_08_distance': [('点到平面', 4), ('异面直线', 3), ('距离', 2), ('空间距离', 5)],
    'kp_08_09_sphere': [('外接球', 5), ('内切球', 5), ('球半径', 3), ('外接球的表面积', 5)],
    'kp_08_10_folding': [('折叠', 5), ('展开', 4), ('折成', 4)],
    # 09 解析几何
    'kp_09_01_line': [('直线', 1), ('斜率', 3), ('倾斜角', 4), ('直线方程', 4), ('距离公式', 4)],
    'kp_09_02_circle': [('圆的方程', 5), ('圆心', 4), ('半径', 2), ('圆C', 2)],
    'kp_09_03_line_circle': [('直线与圆', 5), ('弦长', 4), ('切线', 2), ('相切', 3)],
    'kp_09_04_conic_def': [('圆锥曲线', 4), ('定义', 1), ('标准方程', 3), ('椭圆的定义', 4)],
    'kp_09_05_ellipse': [('椭圆', 5), ('a>b>0', 3), ('焦点', 2)],
    'kp_09_06_hyperbola': [('双曲线', 5), ('渐近线', 5), ('实轴', 4), ('虚轴', 4)],
    'kp_09_07_parabola': [('抛物线', 5), ('准线', 5), ('焦半径', 5), ('通径', 4)],
    'kp_09_08_eccentricity': [('离心率', 5), ('e=', 3), ('a,b,c', 2)],
    'kp_09_09_chord': [('弦长', 4), ('中点弦', 5), ('点差法', 4)],
    'kp_09_10_intersection': [('联立', 4), ('韦达定理', 5), ('判别式', 4), ('Δ', 3)],
    'kp_09_11_fixed': [('定点', 5), ('定值', 5), ('过定点', 5)],
    'kp_09_12_locus': [('轨迹', 5), ('轨迹方程', 5), ('相关点法', 4)],
    'kp_09_13_polar': [('极坐标', 5), ('极径', 5), ('极角', 4)],
    'kp_09_14_param_eq': [('参数方程', 5), ('参数t', 4), ('参数方程与普通方程', 5)],
    # 10 概率统计
    'kp_10_01_sample': [('抽样', 5), ('分层抽样', 5), ('系统抽样', 5), ('简单随机', 4)],
    'kp_10_02_histogram': [('频率分布直方图', 5), ('直方图', 4), ('频率/组距', 4)],
    'kp_10_03_central': [('平均数', 4), ('中位数', 4), ('众数', 4), ('方差', 4), ('极差', 3), ('茎叶图', 4)],
    'kp_10_04_classical': [('古典概型', 5), ('等可能', 4), ('基本事件', 4)],
    'kp_10_05_geometric': [('几何概型', 5), ('面积比', 3), ('长度比', 3)],
    'kp_10_06_event': [('互斥', 5), ('对立', 4), ('相互独立', 5), ('独立事件', 5)],
    'kp_10_07_conditional': [('条件概率', 5), ('全概率', 5), ('贝叶斯', 4)],
    'kp_10_08_distribution': [('分布列', 5), ('数学期望', 5), ('期望', 3), ('方差', 2)],
    'kp_10_09_binomial': [('二项分布', 5), ('超几何', 5), ('独立重复', 5)],
    'kp_10_10_regression': [('回归', 4), ('回归方程', 5), ('最小二乘', 4), ('预测', 2)],
    'kp_10_11_chisquare': [('独立性检验', 5), ('卡方', 5), ('K²', 5), ('K2', 4)],
    'kp_10_12_normal': [('正态分布', 5), ('正态曲线', 5), ('3σ', 4)],
    'kp_10_13_event': [('样本空间', 5), ('随机事件', 5), ('事件的关系', 4)],
    # 11 计数原理
    'kp_11_01_principle': [('分类加法', 5), ('分步乘法', 5), ('计数原理', 5)],
    'kp_11_02_permutation': [('排列', 4), ('排列数', 5), ('A(n,m)', 4)],
    'kp_11_03_combination': [('组合', 4), ('组合数', 5), ('C(n,m)', 4)],
    'kp_11_04_grouping': [('分组', 4), ('分配', 3), ('隔板', 5), ('均分', 4), ('分组分配', 5)],
    'kp_11_05_binomial': [('二项式', 5), ('展开式', 4), ('通项', 3), ('二项展开', 5)],
    'kp_11_06_coefficient': [('系数和', 5), ('赋值法', 5), ('系数最大', 5), ('奇偶项', 4)],
    # 12 不等式
    'kp_12_01_quadratic': [('一元二次不等式', 5), ('解集', 3), ('判别式', 4)],
    'kp_12_02_absolute': [('绝对值不等式', 5), ('绝对值', 3)],
    'kp_12_03_basic': [('基本不等式', 5), ('一正二定', 5), ('积的最值', 4), ('和的最小值', 4)],
    'kp_12_04_region': [('可行域', 5), ('线性规划', 5), ('目标函数', 5)],
    'kp_12_05_property': [('比较大小', 4), ('不等式性质', 5)],
    'kp_12_06_param': [('恒成立', 4), ('含参不等式', 5), ('解集为', 3)],
    'kp_12_07_proof': [('证明不等式', 5), ('比较法', 4), ('综合法', 4), ('分析法', 4)],
    'kp_12_08_integrated': [('不等式与函数', 5), ('函数与不等式', 5)],
    'kp_12_09_abs_inequality': [('绝对值不等式', 4), ('选讲', 3)],
    'kp_12_10_cauchy': [('柯西不等式', 6), ('柯西', 5)],
    # 14 算法
    'kp_14_01_flowchart': [('程序框图', 5), ('循环结构', 5), ('条件结构', 5), ('算法语句', 4)],
    # 15 几何证明
    'kp_15_01_similar_triangle': [('相似三角形', 5), ('相似', 4), ('比例线段', 5), ('中位线', 4)],
    'kp_15_02_circle_power': [('圆幂', 5), ('相交弦', 5), ('切割线', 5), ('切线长定理', 5), ('四点共圆', 5)],
    # 16 极限
    'kp_16_01_limit': [('极限', 5), ('无穷等比', 5), ('左右极限', 5), ('极限存在', 5)],
    # 17 矩阵
    'kp_17_01_matrix_transform': [('矩阵', 5), ('矩阵变换', 5), ('二阶矩阵', 5)],
    'kp_17_02_matrix_eigen': [('逆矩阵', 5), ('特征值', 5), ('特征向量', 5)],
    # 18 定积分
    'kp_18_01_integral': [('定积分', 5), ('曲边梯形', 5), ('积分', 3)],
}

# legacy 中文模块 -> 词表模块前缀（用于加分，不直接决定 primary）
LEGACY_MODULES = {
    '集合与逻辑': 'kp_01', '集合与常用逻辑用语': 'kp_01', '常用逻辑用语': 'kp_01',
    '函数': 'kp_02', '导数及其应用': 'kp_03', '三角函数': 'kp_04',
    '平面向量': 'kp_05', '复数': 'kp_06', '数列': 'kp_07',
    '立体几何': 'kp_08', '解析几何': 'kp_09', '概率与统计': 'kp_10',
    '计数原理': 'kp_11', '不等式': 'kp_12', '算法初步': 'kp_14',
    '几何证明选讲': 'kp_15', '极限': 'kp_16', '矩阵与变换': 'kp_17',
    '定积分': 'kp_18',
}
# 解三角形有独立 legacy 模块，但词表 kp 在 kp_04
LEGACY_SUB = {'解三角形': ['kp_04_08_sine', 'kp_04_09_cosine', 'kp_04_10_area', 'kp_04_11_apply']}

# 特殊强规则：命中则直接加高权重（解决主考意图）
SPECIAL = [
    (r'离心率', 'kp_09_08_eccentricity', 8),
    (r'渐近线', 'kp_09_06_hyperbola', 8),
    (r'准线|焦半径', 'kp_09_07_parabola', 7),
    (r'外接球|内切球', 'kp_08_09_sphere', 8),
    (r'二面角', 'kp_08_06_angle', 7),
    (r'折叠|折成', 'kp_08_10_folding', 7),
    (r'分布列|数学期望|随机变量的期望', 'kp_10_08_distribution', 8),
    (r'二项分布|超几何', 'kp_10_09_binomial', 8),
    (r'独立性检验|卡方|K\s*[²2]', 'kp_10_11_chisquare', 8),
    (r'回归方程|回归直线', 'kp_10_10_regression', 8),
    (r'正态分布', 'kp_10_12_normal', 8),
    (r'条件概率|全概率', 'kp_10_07_conditional', 8),
    (r'二项式', 'kp_11_05_binomial', 8),
    (r'隔板', 'kp_11_04_grouping', 8),
    (r'极坐标', 'kp_09_13_polar', 8),
    (r'参数方程', 'kp_09_14_param_eq', 8),
    (r'定积分|曲边梯形', 'kp_18_01_integral', 8),
    (r'程序框图', 'kp_14_01_flowchart', 8),
    (r'特征值|特征向量', 'kp_17_02_matrix_eigen', 8),
    (r'矩阵', 'kp_17_01_matrix_transform', 7),
    (r'极限', 'kp_16_01_limit', 7),
    (r'柯西', 'kp_12_10_cauchy', 8),
    (r'数学归纳法', 'kp_07_08_induction', 8),
    (r'三视图', 'kp_08_01_threeview', 8),
    (r'线面角', 'kp_08_06_angle', 7),
    (r'基本不等式', 'kp_12_03_basic', 8),
    (r'可行域|线性规划', 'kp_12_04_region', 8),
    (r'一元二次不等式', 'kp_12_01_quadratic', 8),
    (r'绝对值不等式', 'kp_12_02_absolute', 7),
    (r'正弦定理', 'kp_04_08_sine', 8),
    (r'余弦定理', 'kp_04_09_cosine', 8),
    (r'等差', 'kp_07_02_arithmetic', 7),
    (r'等比', 'kp_07_03_geometric', 7),
    (r'错位相减|裂项', 'kp_07_05_summation', 8),
    (r'递推', 'kp_07_06_recurrence', 7),
    (r'切线', 'kp_03_02_tangent', 7),
    (r'极值', 'kp_03_04_extremum', 7),
    (r'零点', 'kp_02_11_zero', 5),
    (r'椭圆', 'kp_09_05_ellipse', 7),
    (r'双曲线', 'kp_09_06_hyperbola', 7),
    (r'抛物线', 'kp_09_07_parabola', 7),
    (r'圆的方程|圆心', 'kp_09_02_circle', 6),
    (r'直线与圆', 'kp_09_03_line_circle', 8),
    (r'弦长|中点弦', 'kp_09_09_chord', 7),
    (r'定点|定值', 'kp_09_11_fixed', 7),
    (r'轨迹', 'kp_09_12_locus', 6),
    (r'联立|韦达', 'kp_09_10_intersection', 6),
    (r'复数.*(模|共轭)|共轭', 'kp_06_03_modulus', 7),
    (r'复平面', 'kp_06_04_geometric', 7),
    (r'纯虚数|虚部', 'kp_06_01_concept', 7),
    (r'样本空间|随机事件', 'kp_10_13_event', 6),
    (r'古典概型', 'kp_10_04_classical', 7),
    (r'几何概型', 'kp_10_05_geometric', 7),
    (r'互斥|相互独立', 'kp_10_06_event', 6),
    (r'频率分布直方图|直方图', 'kp_10_02_histogram', 7),
    (r'抽样', 'kp_10_01_sample', 6),
    (r'平均数|中位数|方差|茎叶图', 'kp_10_03_central', 5),
    (r'分布列', 'kp_10_08_distribution', 8),
]


def load_vocab():
    text = VOCAB_MD.read_text(encoding='utf-8')
    vocab = {}
    for line in text.splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', parts[0].strip('`')):
            kid = parts[0].strip('`')
            vocab[kid] = {'name': parts[1], 'desc': parts[2]}
    if len(vocab) != 120:
        raise SystemExit(f'词表解析到 {len(vocab)} 项，应为 120')
    return vocab


def parse_legacy(v):
    if not v or v in ('None', '[]'):
        return []
    if isinstance(v, list):
        return v
    try:
        x = eval(v)  # noqa: S307 - 输入来自本地 JSON
        return x if isinstance(x, list) else []
    except Exception:  # noqa: BLE001
        return []


def score_question(text, legacy_modules, vocab):
    text = text or ''
    scores = collections.defaultdict(float)
    matched = collections.defaultdict(list)
    for kid, pairs in KEYWORDS.items():
        for word, w in pairs:
            if word in text:
                scores[kid] += w
                matched[kid].append(word)
    for pat, kid, w in SPECIAL:
        if re.search(pat, text):
            scores[kid] += w
            matched[kid].append(pat)
    for mod in legacy_modules:
        prefix = LEGACY_MODULES.get(mod)
        if prefix:
            for kid in vocab:
                if kid.startswith(prefix + '_'):
                    scores[kid] += 0.8
                    matched[kid].append('legacy:' + mod)
        for kid in LEGACY_SUB.get(mod, []):
            scores[kid] += 2.0
            matched[kid].append('legacy:' + mod)
    return scores, matched


def annotate_item(item, vocab):
    scores, matched = score_question(item['text'], parse_legacy(item.get('legacy_knowledge_points')), vocab)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ranked = [(k, v) for k, v in ranked if v > 0]
    if not ranked or ranked[0][1] < 2.0:
        return {'kp_primary': '', 'kp_secondary': [], 'confidence': 0.5,
                'rationale': '题干未出现明确考点词，按词表难以归属，暂空 primary，待人工/抽检复核。',
                'status': 'no_attribution', 'candidates': []}
    top_id, top_s = ranked[0]
    second_s = ranked[1][1] if len(ranked) > 1 else 0
    margin = top_s - second_s
    if top_s >= 8 and margin >= 2:
        conf = 0.92
    elif top_s >= 5 and margin >= 1:
        conf = 0.85
    elif top_s >= 3:
        conf = 0.72
    else:
        conf = 0.62
    if margin < 0.8:
        conf -= 0.08
    conf = round(max(0.45, min(0.95, conf)), 2)
    # secondary：不同模块的前 2 个候选，且分数 >= 2
    secondary = []
    top_mod = top_id.split('_')[1]
    for kid, sc in ranked[1:]:
        if sc < 2.0 or kid == top_id:
            continue
        if kid.split('_')[1] == top_mod:
            continue
        secondary.append(kid)
        if len(secondary) == 2:
            break
    words = []
    for w in matched.get(top_id, []):
        if w not in words:
            words.append(w)
    kw = '、'.join(w.replace('legacy:', 'legacy ') for w in words[:4])
    rationale = f'题干出现「{kw}」，主考{vocab[top_id]["name"]}；'
    if secondary:
        rationale += '兼及' + '、'.join(vocab[x]['name'] for x in secondary) + '。'
    else:
        rationale += '未发现明显跨模块兼考点。'
    return {'kp_primary': top_id, 'kp_secondary': secondary, 'confidence': conf,
            'rationale': rationale, 'status': 'model', 'candidates': ranked[:5]}



# ── 训练：既有高考 5954 条 kp_primary 作为训练集（字符 n-gram 逻辑回归 + 词表规则集成） ──
def db_url():
    if os.environ.get('CHILON_TEST_DATABASE_URL'):
        return os.environ['CHILON_TEST_DATABASE_URL']
    if os.environ.get('CHILON_DATABASE_URL'):
        return os.environ['CHILON_DATABASE_URL']
    pw = subprocess.run(['docker', 'exec', CONTAINER, 'printenv', 'POSTGRES_PASSWORD'],
                        capture_output=True, text=True).stdout.strip()
    if not pw:
        raise RuntimeError('无法读取容器 env')
    return f'postgresql://{DB_USER}:{urllib.parse.quote(pw)}@{DB_HOST}:{DB_PORT}/{DB_NAME}'


def tokenize(text, nmax=3):
    s = text or ''
    s = re.sub(r'\\[a-zA-Z]+', ' ', s)
    s = re.sub(r'[^一-龥A-Za-z]+', ' ', s)
    out = []
    for run in s.split():
        if not run:
            continue
        for n in range(2, nmax + 1):
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                if re.search(r'[一-龥]', g):
                    out.append(g)
    return out


def load_training():
    import psycopg
    conn = psycopg.connect(db_url())
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT a.value::text, c.text_content
        FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id = a.question_id
        JOIN knowledge_document_versions dv ON dv.id = q.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        JOIN knowledge_chunks c ON c.document_version_id = q.document_version_id
             AND c.locator = q.stem_locator
        WHERE a.superseded_by IS NULL AND a.annotation_type='kp_primary'
          AND s.source_type='gaokao_paper'
    """)
    rows = cur.fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows]


def train_model(rows):
    import numpy as np
    cnt = collections.Counter()
    for _l, _t in rows:
        cnt.update(set(tokenize(_t)))
    feats = [g for g, c in cnt.items() if c >= 3]
    idx = {g: i for i, g in enumerate(feats)}
    classes = sorted({l for l, _t in rows})
    cidx = {c: i for i, c in enumerate(classes)}
    X, Y = [], []
    for label, text in rows:
        ids = [idx[g] for g in set(tokenize(text)) if g in idx]
        X.append(ids)
        Y.append(cidx[label])
    C, V = len(classes), len(feats)
    rng = np.random.default_rng(20261106)
    W = np.zeros((C, V), dtype=np.float32)
    b = np.zeros(C, dtype=np.float32)
    for _ep in range(15):
        order = list(range(len(X)))
        rng.shuffle(order)
        for ii in order:
            ids = np.asarray(X[ii], dtype=np.int32)
            if len(ids) == 0:
                continue
            y = Y[ii]
            z = W[:, ids].sum(1) + b
            z -= z.max()
            p = np.exp(z)
            p /= p.sum()
            g = p
            g[y] -= 1
            W[:, ids] -= 0.5 * g[:, None]
            b -= 0.5 * g
    return {'W': W, 'b': b, 'feats': feats, 'idx': idx, 'classes': classes}


def combined_predict(text, legacy_modules, model, vocab, alpha=0.8):
    import numpy as np
    scores, matched = score_question(text, legacy_modules, vocab)
    ts = set(tokenize(text))
    ids = [model['idx'][g] for g in ts if g in model['idx']]
    W, b, classes = model['W'], model['b'], model['classes']
    z = W[:, ids].sum(1) + b if ids else b.copy()
    z -= z.max()
    prob = np.exp(z)
    prob /= prob.sum()
    comb = {}
    for ci, c in enumerate(classes):
        comb[c] = float(math.log(float(prob[ci]) + 1e-9) + alpha * scores.get(c, 0.0))
    for c, sc in scores.items():
        if c not in comb:
            comb[c] = alpha * sc
    z2 = np.asarray(list(comb.values()), dtype=np.float64)
    z2 -= z2.max()
    p2 = np.exp(z2)
    p2 /= p2.sum()
    ranked = sorted(((c, comb[c], float(p2[i])) for i, c in enumerate(comb)),
                    key=lambda x: (-x[2], x[0]))
    return ranked, matched, scores


def annotate_item_model(item, vocab, model):
    legacy = parse_legacy(item.get('legacy_knowledge_points'))
    ranked, matched, rule_scores = combined_predict(item['text'], legacy, model, vocab)
    if not ranked:
        return {'kp_primary': '', 'kp_secondary': [], 'confidence': 0.5,
                'rationale': '题干无可用中文特征，暂空 primary。', 'status': 'no_attribution',
                'candidates': []}
    top_id, _cs, p1 = ranked[0]
    p2 = ranked[1][2] if len(ranked) > 1 else 0.0
    # 低证据：概率低且规则也弱 → 留空
    if p1 < 0.22 and rule_scores.get(top_id, 0) < 2:
        return {'kp_primary': '', 'kp_secondary': [], 'confidence': 0.5,
                'rationale': '模型与词表规则证据均不足，暂空 primary，待人工/抽检复核。',
                'status': 'no_attribution', 'candidates': ranked[:5]}
    conf = 0.58 + 0.38 * p1
    if p1 - p2 < 0.10:
        conf -= 0.06
    conf = round(max(0.45, min(0.95, conf)), 2)
    secondary = []
    top_mod = top_id.split('_')[1]
    for c, _s, pp in ranked[1:]:
        if pp < 0.05:
            continue
        if c.split('_')[1] == top_mod:
            continue
        if c in secondary:
            continue
        secondary.append(c)
        if len(secondary) == 2:
            break
    words = []
    for w in matched.get(top_id, []):
        if w not in words:
            words.append(w)
    kw = '、'.join(w.replace('legacy:', '') for w in words[:4])
    if kw:
        rationale = f'题干关键词「{kw}」与「{vocab[top_id]["name"]}」匹配，主考{vocab[top_id]["name"]}；'
    else:
        rationale = f'题干与既有 5954 条高考标注中「{vocab[top_id]["name"]}」类最接近，主考{vocab[top_id]["name"]}；'
    if secondary:
        rationale += '兼及' + '、'.join(vocab[c]['name'] for c in secondary) + '。'
    else:
        rationale += '未发现明显跨模块兼考点。'
    return {'kp_primary': top_id, 'kp_secondary': secondary, 'confidence': conf,
            'rationale': rationale, 'status': 'model', 'candidates': ranked[:5]}


def stage_annotate(args):
    vocab = load_vocab()
    data = json.loads(QUESTIONS.read_text(encoding='utf-8'))
    items = data['items']
    if len(items) != 931:
        raise SystemExit(f'题数 {len(items)} ≠ 931')
    print('[train] 读取既有高考标注并训练字符 n-gram 模型 …', flush=True)
    train_rows = load_training()
    print(f'[train] 训练样本 {len(train_rows)}', flush=True)
    model = train_model(train_rows)
    print('[train] 完成；开始 931 题标注', flush=True)
    anns = []
    for it in items:
        a = annotate_item_model(it, vocab, model)
        anns.append({'qid': it['qid'], 'source_id': it['source_id'], 'set_title': it['set_title'],
                     'question_no': it['question_no'], 'question_type': it.get('question_type'),
                     'legacy_knowledge_points': it.get('legacy_knowledge_points'),
                     'kp_primary': a['kp_primary'], 'kp_secondary': a['kp_secondary'],
                     'confidence': a['confidence'], 'rationale': a['rationale'],
                     'status': a['status'], 'classification_source': 'model',
                     'model_version': MODEL_VERSION, 'candidates': a['candidates']})
    # 批次文件
    FULL.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(anns), 100):
        batch = anns[i:i + 100]
        (FULL / f'annotations_batch_{i//100+1:02d}.json').write_text(
            json.dumps({'batch': i//100 + 1, 'items': batch}, ensure_ascii=False, indent=1),
            encoding='utf-8')
    # 校验
    errors = []
    qids = [x['qid'] for x in anns]
    if len(qids) != 931 or len(set(qids)) != 931:
        errors.append('qid 覆盖/唯一性失败')
    if set(qids) != {x['qid'] for x in items}:
        errors.append('qid 与 questions_931 不一致')
    for x in anns:
        if x['kp_primary'] and x['kp_primary'] not in vocab:
            errors.append(f'{x["qid"]}: primary 非法')
        for k in x['kp_secondary']:
            if k not in vocab:
                errors.append(f'{x["qid"]}: secondary 非法')
        if len(x['kp_secondary']) > 2:
            errors.append(f'{x["qid"]}: secondary>2')
        if not (0 <= x['confidence'] <= 1):
            errors.append(f'{x["qid"]}: confidence 越界')
        if not x['rationale']:
            errors.append(f'{x["qid"]}: rationale 空')
    payload = {'schema': 'chilon-mock-annotations/v1', 'model_version': MODEL_VERSION,
               'total': len(anns), 'errors': errors, 'items': anns}
    ANNOTATIONS.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    # 统计
    primary = [x for x in anns if x['kp_primary']]
    low = [x for x in primary if x['confidence'] <= 0.70]
    empty = [x for x in anns if not x['kp_primary']]
    kp_counts = collections.Counter(x['kp_primary'] for x in primary)
    mod_counts = collections.Counter(x['kp_primary'].split('_')[1] for x in primary)
    # pilot 对比
    pilot = json.loads(PILOT.read_text(encoding='utf-8'))['items']
    pby = {x['question_id']: x['annotation'] for x in pilot}
    ours = {x['qid']: x for x in anns}
    same = same_mod = both = 0
    pilot_diff = []
    for qid, pa in pby.items():
        oa = ours.get(qid)
        if not oa:
            continue
        both += 1
        if oa['kp_primary'] == pa['kp_primary']:
            same += 1
        if oa['kp_primary'] and pa['kp_primary'] and oa['kp_primary'].split('_')[1] == pa['kp_primary'].split('_')[1]:
            same_mod += 1
        elif oa['kp_primary'] != pa['kp_primary']:
            pilot_diff.append({'qid': qid, 'ours': oa['kp_primary'], 'pilot': pa['kp_primary'],
                               'conf': oa['confidence']})
    # 跨模块歧义 Top20（候选前二不同模块且分差小）
    amb = []
    for x in anns:
        cands = x.get('candidates') or []
        if len(cands) >= 2 and cands[0][1] - cands[1][1] < 2 and cands[0][0].split('_')[1] != cands[1][0].split('_')[1]:
            amb.append(x)
    amb.sort(key=lambda x: x['confidence'])
    L = ['---', 'type: report', 'title: 931 题全量标注报告', 'updated: 2026-11-06',
         'status: model', '---', '',
         '# 931 题全量知识点标注报告', '',
         f'> 模型：`{MODEL_VERSION}`；输入：`questions_931.json`（最终 PG 文本）；词表：120 条。  ',
         '> 本报告为模型标注结果；未调用 OCR、未写 legacy/高考。', '',
         '## 1. 覆盖与校验', '',
         f'- 题数：**{len(anns)}/931**；qid 唯一：**{"✅" if len(set(qids))==931 else "❌"}**',
         f'- **primary 非空：{len(primary)}（{len(primary)/931*100:.1f}%）**；空 primary：**{len(empty)}**',
         f'- kp_id 全部合法：**{"✅" if not errors else "❌"}**；secondary≤2：✅；校验错误：**{len(errors)}**',
         f'- 低置信（≤0.70）：**{len(low)}**（{len(low)/len(primary)*100:.1f}% of non-empty）', '',
         '## 2. 模块/词表分布', '',
         '| 模块 | 数量 |', '| --- | --- |']
    for mod, n in sorted(mod_counts.items(), key=lambda kv: -kv[1]):
        L.append(f'| kp_{mod} | {n} |')
    L += ['', '## 3. 词表使用 Top 20', '', '| kp_id | 名称 | 数量 |', '| --- | --- | --- |']
    for kid, n in kp_counts.most_common(20):
        L.append(f'| `{kid}` | {vocab[kid]["name"]} | {n} |')
    L += ['', '## 4. 低置信（≤0.70）', '', '| qid | primary | 置信 | 理由 |', '| --- | --- | --- | --- |']
    for x in low[:60]:
        L.append(f'| `{x["qid"]}` | `{x["kp_primary"]}` | {x["confidence"]} | {x["rationale"]} |')
    L += ['', '## 5. 跨模块歧义 Top 20', '', '| qid | 候选1 | 候选2 | 置信 |', '| --- | --- | --- | --- |']
    for x in amb[:20]:
        L.append(f'| `{x["qid"]}` | `{x["candidates"][0][0]}` | `{x["candidates"][1][0]}` | {x["confidence"]} |')
    L += ['', '## 6. 与 pilot 100 同题对比（仅参考，不据此改标签）', '',
          f'- 可比题数：{both}；primary 完全相同：**{same}（{same/both*100:.1f}%）**；'
          f'模块相同：**{same_mod}（{same_mod/both*100:.1f}%）**',
          '- 说明：pilot 基于修复前文本；结论仅用于发现口径差异，不复制 pilot 标签。', '',
          '### 差异示例（前 20）', '', '| qid | 本标注 | pilot | 本置信 |', '| --- | --- | --- | --- |']
    for d in pilot_diff[:20]:
        L.append(f'| `{d["qid"]}` | `{d["ours"]}` | `{d["pilot"]}` | {d["conf"]} |')
    L += ['', '---', '', '> 批次文件：`annotations_batch_01..10.json`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[annotate] {len(anns)}/931；primary {len(primary)}；空 {len(empty)}；低置信 {len(low)}；错误 {len(errors)}')
    print(f'pilot 对比：同题 {both}；primary 相同 {same}（{same/both*100:.1f}%）；模块相同 {same_mod}（{same_mod/both*100:.1f}%）')
    return 0 if not errors else 2


def _mock_question_map(url):
    import psycopg
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id::text, q.question_no, q.id::text, q.stem_locator
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam'
    """)
    rows = cur.fetchall()
    conn.close()
    return {f'mock_{sid}_q{int(no):02d}': qid for sid, no, qid, _loc in rows}


def stage_import(args):
    import psycopg
    d = json.loads(ANNOTATIONS.read_text(encoding='utf-8'))
    items = d['items']
    if len(items) != 931:
        raise SystemExit(f'annotations {len(items)} ≠ 931')
    url = db_url()
    qmap = _mock_question_map(url)
    if len(qmap) != 931:
        raise SystemExit(f'PG mock questions {len(qmap)} ≠ 931')
    # 备份：现有 mock annotations（应为空）
    conn = psycopg.connect(url); cur = conn.cursor()
    cur.execute("""
        SELECT a.id::text, a.question_id::text, a.annotation_type, a.value,
               a.classification_source, a.confidence::float8, a.model_version, a.created_at::text
        FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL
    """)
    existing = [dict(zip(['id','question_id','type','value','source','confidence','model_version','created_at'], r))
                for r in cur.fetchall()]
    conn.close()
    if not BACKUP.exists():
        BACKUP.write_text(json.dumps({'schema': 'chilon-mock-annotations-backup/v1',
                                      'mock_annotations': existing,
                                      'model_version': MODEL_VERSION}, ensure_ascii=False, indent=1),
                          encoding='utf-8')
        print(f'[备份] {BACKUP}（现有 mock annotations {len(existing)}）')
    else:
        print(f'[备份] 保留已有 {BACKUP}')
    # upsert
    plan = {'primary_upsert': 0, 'secondary_upsert': 0, 'secondary_delete': 0, 'unchanged': 0}
    conn = psycopg.connect(url)
    try:
        with conn.transaction():
            cur = conn.cursor()
            for x in items:
                qid = qmap[x['qid']]
                for typ, value in (('kp_primary', x['kp_primary'] or ''),
                                   ('kp_secondary', json.dumps(x['kp_secondary'], ensure_ascii=False))):
                    if typ == 'kp_secondary' and not x['kp_secondary']:
                        # 不写空 secondary；若之前有本模型的行则删除
                        cur.execute("""DELETE FROM knowledge_annotations
                            WHERE question_id=%s::uuid AND annotation_type='kp_secondary'
                              AND superseded_by IS NULL AND classification_source='model'
                              AND model_version=%s""", (qid, MODEL_VERSION))
                        if cur.rowcount:
                            plan['secondary_delete'] += cur.rowcount
                        continue
                    cur.execute("""SELECT id::text, value, confidence::float8, model_version
                        FROM knowledge_annotations
                        WHERE question_id=%s::uuid AND annotation_type=%s AND superseded_by IS NULL""",
                                (qid, typ))
                    row = cur.fetchone()
                    conf = str(x['confidence'])
                    if row and row[1] == value and abs(float(row[2]) - float(conf)) < 1e-9 and row[3] == MODEL_VERSION:
                        plan['unchanged'] += 1
                        continue
                    if row:
                        cur.execute("""UPDATE knowledge_annotations
                            SET value=%s, classification_source='model', confidence=%s::numeric,
                                model_version=%s
                            WHERE id=%s::uuid""", (value, conf, MODEL_VERSION, row[0]))
                    else:
                        cur.execute("""INSERT INTO knowledge_annotations
                            (id, question_id, annotation_type, value, classification_source,
                             confidence, model_version)
                            VALUES (%s::uuid, %s::uuid, %s, %s, 'model', %s::numeric, %s)""",
                                    (str(uuid.uuid4()), qid, typ, value, conf, MODEL_VERSION))
                    if typ == 'kp_primary':
                        plan['primary_upsert'] += 1
                    else:
                        plan['secondary_upsert'] += 1
        conn.commit()
    finally:
        conn.close()
    # 校验
    conn = psycopg.connect(url); cur = conn.cursor()
    cur.execute("""SELECT a.annotation_type, count(*) FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL
        GROUP BY 1""")
    mock_counts = dict(cur.fetchall())
    cur.execute("""SELECT count(*) FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='gaokao_paper' AND a.superseded_by IS NULL""")
    gk_count = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL AND a.annotation_type='kp_primary'
          AND a.value<>''""")
    primary_nonempty = cur.fetchone()[0]
    conn.close()
    # 幂等 re-plan：再次执行应无变化（比较值）
    conn = psycopg.connect(url); cur = conn.cursor()
    changed = 0
    for x in items:
        qid = qmap[x['qid']]
        cur.execute("""SELECT value, confidence::float8, model_version FROM knowledge_annotations
            WHERE question_id=%s::uuid AND annotation_type='kp_primary' AND superseded_by IS NULL""", (qid,))
        row = cur.fetchone()
        if (not row or row[0] != (x['kp_primary'] or '')
                or abs(float(row[1]) - float(x['confidence'])) > 1e-9 or row[2] != MODEL_VERSION):
            changed += 1
    conn.close()
    L = ['---', 'type: report', 'title: 模拟题 annotations 写 PG 报告', 'updated: 2026-11-06',
         'status: done', '---', '',
         '# 模拟题 931 条标注写 PG 报告', '',
         f'> model_version：`{MODEL_VERSION}`；classification_source：`model`；只写 mock，不动高考/legacy。', '',
         '## 写入计数', '',
         '| 项 | 值 |', '| --- | --- |',
         f'| kp_primary upsert | {plan["primary_upsert"]} |',
         f'| kp_secondary upsert | {plan["secondary_upsert"]} |',
         f'| kp_secondary 清理空行 | {plan["secondary_delete"]} |',
         f'| 幂等跳过 | {plan["unchanged"]} |',
         f'| mock active primary 行 | {mock_counts.get("kp_primary", 0)} |',
         f'| mock active secondary 行 | {mock_counts.get("kp_secondary", 0)} |',
         f'| primary 非空 | {primary_nonempty} |',
         f'| 高考 annotations active | {gk_count}（应 8007） |',
         f'| 幂等复跑变化 primary | {changed}（应 0） |', '',
         f'- 备份：`{BACKUP}`', '', '---', '', '> 回滚：`tools/kb_mock_annotate_full.py --stage rollback`。', '']
    PG_REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[import] primary {mock_counts.get("kp_primary",0)}｜secondary {mock_counts.get("kp_secondary",0)}｜'
          f'primary_nonempty {primary_nonempty}｜gk {gk_count}｜幂等变化 {changed}')
    return 0 if (mock_counts.get('kp_primary',0) == 931 and gk_count == 8007 and changed == 0) else 4


def stage_rollback(args):
    import psycopg
    url = db_url()
    conn = psycopg.connect(url)
    try:
        with conn.transaction():
            cur = conn.cursor()
            # 删除本模型写入的 mock annotations；若无备份则清空 mock 标注
            cur.execute("""DELETE FROM knowledge_annotations a
                USING knowledge_questions q, knowledge_document_versions dv, knowledge_sources s
                WHERE a.question_id=q.id AND q.document_version_id=dv.id AND s.id=dv.source_id
                  AND s.source_type='mock_exam' AND a.superseded_by IS NULL
                  AND a.classification_source='model' AND a.model_version=%s""", (MODEL_VERSION,))
            deleted = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    print(f'[rollback] 删除 mock annotations {deleted}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='931 题全量标注/写 PG/回滚')
    ap.add_argument('--stage', choices=['annotate', 'import', 'rollback'], default='annotate')
    args = ap.parse_args(argv)
    if args.stage == 'annotate':
        return stage_annotate(args)
    if args.stage == 'import':
        return stage_import(args)
    return stage_rollback(args)


if __name__ == '__main__':
    sys.exit(main())
