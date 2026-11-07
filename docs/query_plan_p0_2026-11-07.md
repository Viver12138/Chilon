# QueryPlan P0：硬过滤 + 过滤遵守率（2026-11-07）

> 依据：2026-11-07 专家《高中数学知识库检索问题诊断与优化建议》P0 优先级。
> 范围：只做 QueryPlan v0 + 硬过滤 + Filter Compliance Rate；**不做** content_type 分池、同义词、UI。
> 数据：`teacher_questions.v2.json`（60 条 / 20 strict）；索引 `chilon_chunks_qwen3_7_text_embedding_v1`。

## 1. 目标

把教师查询先变成结构化 **QueryPlan**，明确“要找什么对象、必须满足什么条件”：

- 明确的年份 / 来源 / 题型 / 卷别 / 对象类型 → **硬过滤**；
- 知识点、关键词、难度/定位词 → **软信号**（只影响召回/排序）；
- 硬过滤下 0 条时**不静默回退**；
- 用 **Filter Compliance Rate** 检查结果是否真的遵守了用户条件。

## 2. QueryPlan v0

Schema：`schemas/query_plan.v0.schema.json`；实现：`backend/app/services/query_plan.py`。

```json
{
  "version": "query-plan/v0",
  "query": "找一道解析几何的压轴题",
  "intent": "question_search",
  "object_scope": "question",
  "hard": {
    "question_scope": "question"
  },
  "soft": {
    "knowledge_points": ["解析几何"],
    "keywords": ["解析几何", "压轴"],
    "role_hints": ["challenge"]
  },
  "uncertain": ["难度/题目定位只作为软标签（当前无 metadata 硬过滤）"]
}
```

### 2.1 intent / object_scope

| intent | 触发 | object_scope |
| --- | --- | --- |
| `formula_search` | 明确“公式/表达式/通项”，且不是“找一道…” | knowledge（教材） |
| `knowledge_search` | 明确“定义/定理/性质/概念/内容/适用条件” | knowledge（教材） |
| `question_search` | “找一道/找几道/给我/有没有/出几道 + 题/卷/真题” | question |
| `mixed_search` | 无法唯一确定（如“导数和微分有什么区别”） | any |

本批 60 条的实际分布：**question_search 34、knowledge_search 15、formula_search 6、mixed_search 5**；55 条带硬过滤。

### 2.2 硬过滤字段

| 字段 | 取值 | 来源 |
| --- | --- | --- |
| `question_scope` | `knowledge` / `question` | intent 推导 |
| `source_types` | textbook / gaokao_paper / mock_exam | 明确“教材/真题/模拟题”；知识/公式查询默认 textbook |
| `year_range` | 如 [2022,2026] | “近五年/近三年/20xx” |
| `papers` | 卷别名 | “新高考Ⅰ卷/全国甲卷…” |
| `question_types` | single_choice / multiple_choice / fill_blank / free_response | “选择题/填空题/解答题” |

**不进入硬过滤**：知识点、关键词、压轴/基础/易错（当前无 `question_role`/`difficulty` 元数据）。

### 2.3 执行语义

- 硬过滤存在时：文本/向量检索只返回满足全部硬条件的候选；**不触发 <8 条回退**；
- 稀有词 rescue 在硬过滤存在时**禁用**（避免“绕过用户年份/来源约束”）；
- 0 条就是 0 条，由产品层决定是否展示“更早年份相关组”（本 P0 只保证不偷偷放宽）；
- 重排只在正确候选池内排序，不能修复缺失的候选。

## 3. 结果

### 3.1 与当前软过滤基线对比（同一 60 条）

| 组 | 基线 Recall@8 | QP Recall@8 | 基线 strict | QP strict |
| --- | ---: | ---: | ---: | ---: |
| V 仅向量 | 59/60 = 98.3% | **60/60 = 100%** | 18/20 = 90% | **19/20 = 95%** |
| H 混合 | 58/60 = 96.7% | **60/60 = 100%** | 17/20 = 85% | **19/20 = 95%** |
| HR 混合+重排 | 60/60 = 100% | 60/60 = 100% | 19/20 = 95% | **20/20 = 100%** |

### 3.2 过滤遵守率

| 组 | 查询级 Filter Compliance | 结果级命中遵守率 | 硬过滤查询 | 硬过滤下 0 结果 |
| --- | ---: | ---: | ---: | ---: |
| T 仅文本 | 70.9% | 70.9% | 55 | **16** |
| V 仅向量 | **100%** | 100% | 55 | 0 |
| H 混合 | **100%** | 100% | 55 | 0 |
| HR 重排 | **100%** | 100% | 55 | 0 |

> 查询级定义：该查询有硬过滤，top-8 非空，且 top-8 **每一条**都满足全部硬条件。  
> T 组 16 条 0 结果，是纯文本匹配在日语/同义表达下的真实短板；V/H/HR 在硬过滤后候选充足。

### 3.3 典型改善

- **Q-B-02 切线方程公式**：formula_search → 教材硬过滤；HR strict 命中组合 gold（p73+p64），从基线 miss 变为命中，HR strict 20/20。
- **Q-B-09 / Q-E-09 解析几何压轴/大题**：question_search + question_scope=question；不再返回教材目录/小结，H/HR 都命中。
- **年份/来源/题型**：明确条件不再被静默放宽；T 的 16 条 0 结果是“确实没有满足文字+硬条件的候选”，不是偷偷回退。

## 4. 边界与未做

1. **object_scope 仍是粗粒度**：只有 knowledge（教材）vs question；没有 `content_type`（定义/定理/公式/题目/解析/目录），所以“公式卡/定理卡”还无法真正分池。
2. **question_role/difficulty 没有 metadata**：压轴/基础/易错只是软标签，没有硬过滤；本批“找压轴题”仍靠语义召回。
3. **T 组 16 条 0 结果**：纯文本路径对口语/同义表达弱；生产默认是 H/HR，不受影响，但这说明 QueryPlan 不能只配文本检索。
4. **0 结果的产品呈现未做**：当前只保证“不静默回退”，还没有“符合条件 0 条 / 更早年份 N 条”的分组 UI。
5. **评测仍是 60 条 / 20 strict、单次运行**：只能用于验证 P0 行为，不是线上准确率；尚无 CI。

## 5. 下一步（P0 收尾）

1. **content_type 元数据**：给教材块补 definition / theorem / formula / question / solution / catalog；先规则+人工抽检，再启用类型分池。
2. **question_role / difficulty**：补“压轴/基础/综合/易错”标签，作为题目硬过滤或强软排序。
3. **零结果与更早年份分组**：产品层与 API 契约（`no_result_under_filters` + `related_older`）。
4. **run 元数据**：每次评测记录 dataset sha、QueryPlan 版本、硬过滤集合、retrieval config、judge 版本。
5. **回归测试**：把 Q-B-02、Q-B-09、Q-E-09、年份冲突等加入固定回归集。

## 6. 命令与产物

```powershell
# 生成 QueryPlan 并跑 P0 评测
.venv\Scripts\python.exe tools\eval_v2_qp.py `
  --database-url "postgresql+psycopg://postgres:...@127.0.0.1:55495/chilon" `
  --out-prefix var/retrieval/v2_eval_qp_2026-11-07
```

- 计划 schema：`schemas/query_plan.v0.schema.json`
- 提取器：`backend/app/services/query_plan.py`
- 硬过滤支持：`backend/app/services/hybrid_retrieval.py`（`question_scope`）
- P0 评测工具：`tools/eval_v2_qp.py`
- JSON：`var/retrieval/v2_eval_qp_2026-11-07.json`
- 报告：本文件
