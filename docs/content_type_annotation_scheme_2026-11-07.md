# 教材块内容类型（content_type）标注方案 v0

> 日期：2026-11-07  
> 触发：专家 P0 建议——检索要先按“对象类型”分流（公式/定义/定理/题目/解析/目录），不能把所有块混在一个 top-8。  
> 范围：**1797 个教师已复核教材块**；题目/解析块的 `solution` 类型另做，不在本方案内。

## 1. 为什么需要 content_type

当前只区分了 `source_type`（教材/真题/模拟）和 `question_type`（选择/填空/解答），但教材块内部仍有：

- 定义、定理/性质、公式；
- 例题（含解答）、练习/习题；
- 目录/章末小结、阅读/探究材料；
- 其他过渡性正文。

所以“问公式却返回题目”“问定义却返回章末小结”依然会发生。`content_type` 是给每个教材块一个**主类型**，检索时才能：

- formula_search → 只召回 formula/definition 块；
- theorem/definition_search → 只召回 theorem/definition 块；
- 找题 → question 块（已有 question_scope，不依赖教材块）；
- 目录/阅读 → 默认降权或不进入知识卡结果。

## 2. 枚举与判定

| 主类型 | 含义 | 判定要点 |
| --- | --- | --- |
| `definition` | 定义/概念 | “叫做/称为/定义为/我们把/一般地，设…”；整块主要在给定义 |
| `theorem` | 定理/性质/判定/推论 | “定理/性质/判定/推论/基本事实”；整块主要在陈述或证明结论 |
| `formula` | 公式/表达式/通项 | “公式/表达式/通项”；整块主要给公式或公式推导 |
| `example` | 例题（含解答） | 以“例1/例2/例题”开头或主体是例题 |
| `exercise` | 练习/习题/复习题 | “练习/习题/复习巩固/综合运用/拓广探索/复习参考题”，或整块为编号习题 |
| `catalog` | 目录/本册导引/章末小结/知识结构 | 结构性内容，不是知识点本体 |
| `reading` | 阅读与思考/探究与发现/数学文化/文献阅读/信息技术应用 | 拓展性材料 |
| `other` | 过渡正文/章导引/无法归类 | 以上都不明显 |

**主类优先级**（一个块只选一个主类）：

```text
catalog > reading > exercise > example > definition > theorem > formula > other
```

理由：结构性/练习性块即使正文里出现“定义/公式”字样，也不应被当成知识卡；例题里含定义时优先 example。

**多标签**：每个块同时记录 `labels`（数组）与 `mixed`（是否多标签）。例如“例1”里给出一个定义 → `primary=example`, `labels=[example, definition]`。检索路由只看 `primary`，但后续可以按 `labels` 扩展。

## 3. 标注单位与字段

单位：`textbook_block_annotations` 的 active 教材块（一个 OCR 块 = 一个 `chunk_id`）。

| 字段 | 说明 |
| --- | --- |
| `block_id` | 教材块 ID（如 TB-B1-0011-2-p0011-02） |
| `chunk_id` | `knowledge_chunks.id`，PG 事实源 |
| `source_title` / `page` | 教材/页码 |
| `text` | 块正文（标注时看 `text_excerpt`） |
| `primary` | 上表 8 类之一 |
| `labels` | 多标签数组 |
| `mixed` | labels 长度 > 1 |
| `confidence` | `explicit`（规则明确）/ `weak`（需人工确认） |
| `method` | `rule-v0` / `teacher` |
| `review_status` | `draft` / `reviewed` / `rejected`（正式入库时） |

## 4. 当前 draft（rule-v0）

工具：`tools/classify_textbook_content_types.py`，只写离线 draft，**不改 PG**。

`var/textbook_mapping/textbook_content_type_draft.json`：

- 1797 块；mixed **495**（28%）；
- 分布：definition **250**、theorem **116**、formula **64**、example **302**、exercise **385**、catalog **30**、reading **51**、other **599**。

**重要**：这是规则预标，有噪声（尤其 exercise/example/other）；`other` 偏高说明规则还偏保守。**不能直接当正式标注或上线路由**，必须先做教师抽样复核。

## 5. 教师复核（本次）

- 分层抽样：每册约 24 条，共 **120 条**（按 primary 类型轮转抽取，固定 seed）；
- 文件：`review_sheets/samples/教材内容类型标注复核_2026-11-07.xlsx`；
- 列：block_id、教材、页码、摘录、规则主类、规则标签、教师确认主类（下拉）、教师补充标签、备注；
- 判定：教师只看摘录，选该块在教材中**主要承担的角色**；多类型写补充标签；不要按检索结果反推。

质量门槛：

1. 两位标注人独立确认 120 条，Cohen's κ ≥ **0.70**；
2. 分歧由第三人裁决；
3. 规则主类与教师主类一致率 <80% 时，先改规则再标全量，不直接铺 1797 条；
4. 复核通过后，用同一规则+人工修正产出 `content-type-reviewed/v1` 并冻结。

## 6. 存储与迁移（建议，不在本轮执行）

当前 PG 没有 `content_type` 字段。建议：

1. **先离线**：JSON/CSV draft → 教师复核 → 冻结 JSON（带 sha256、规则版本、复核人）；
2. **再加列**：给 `textbook_block_annotations` 增 `content_type text`、`content_types jsonb`、`content_type_version text`；或新建 `textbook_content_types` 表（一 block 一行）以避免污染教师映射版本；
3. RLS/迁移/generated DDL 按 registry 流程走，不手改 generated；
4. 检索侧先做**软路由**（formula/definition/theorem 加权），验证后再变硬过滤；
5. 题目/解析块另定义 `question` / `solution`，不要混入教材块枚举。

## 7. 与检索的关系（下一步）

- 本方案只解决教材块的 `content_type`；
- 完成后 QueryPlan 可增加：
  - `object_type=formula` → content_type ∈ {formula, definition}；
  - `object_type=theorem` → {theorem, definition}；
  - `object_type=definition` → {definition}；
- 在 content_type 正式前，继续用当前 `question_scope`（question/knowledge）+ source_type 硬过滤，不提前加 content_type 硬过滤。

## 8. 命令与产物

```powershell
# 规则预标（写 var/，不改 PG）
.venv\Scripts\python.exe tools\classify_textbook_content_types.py

# 生成教师复核 Excel
python tools\export_content_type_review.py
```

- 规则工具：`tools/classify_textbook_content_types.py`
- 复核导出：`tools/export_content_type_review.py`
- Schema：`schemas/content_type.v0.schema.json`
- draft：`var/textbook_mapping/textbook_content_type_draft.json`（gitignored）
- 复核样本：`var/textbook_mapping/textbook_content_type_review_sample.json`（gitignored）
- 复核表：`review_sheets/samples/教材内容类型标注复核_2026-11-07.xlsx`（gitignored）

## 9. 边界

- 本方案不是冻结标注；draft 分布只说明规则现状，不是最终数据；
- 一个块多类型是常态，`primary` 是路由用的主标签，不能表达全部教学角色；
- 教材块不拆解析，所以没有 `solution`；题目/解析的 solution 类型后续单独设计；
- content_type 修好后，仍需同义词、零结果 UI、run 元数据（专家 P0 其余项）。
