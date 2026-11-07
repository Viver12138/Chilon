# 真实教师问题集 v2 · 收集与 strict 金标指南

> 对应设计：`docs/acceptance_and_retrieval_eval_design_2026-11-07.md` B2/B4/B10（D.117）。
> 目标：**v2.0 初期验收集 60 条**（五类各 12），其中 **30 条带 strict 金标**（定义 8 / 定理 6 / 公式 6 / 完整题目 10）；
> 长期 **v2.1 ≥100 条 strict**，覆盖定义/定理/公式/完整题目。

## 1. 文件

| 文件 | 作用 |
| --- | --- |
| `corpus/eval/teacher_questions.v2.schema.json` | 结构定义（JSON Schema 2020-12）：`expect.strict` 是 **chunk_id 集合**，不是片段 |
| `corpus/eval/teacher_questions.v2.template.json` | 60 槽位空白模板；30 个槽位已标 `strict_plan`（8/6/6/10） |
| `tools/check_teacher_questions_v2.py` | 结构 + 配额 + 完整性校验（模板 / 数据集两种模式） |
| `corpus/eval/teacher_questions.v2.json`（待生成） | 填好的 v2.0 数据集；**不要覆盖模板** |
| `corpus/eval/teacher_questions.v2.manifest.json`（冻结时） | sha256、DB counts、commit、日期 |
| `corpus/eval/teacher_questions.v2.draft.json` | 首批 60 条 draft（问题来自问题收集1.txt；20 条 strict SQL 候选，`strict_verified=false`） |
| `corpus/eval/teacher_questions.v2.draft.gold.json` | 20 条 strict 的 23 个 gold chunk 明细（摘录/位置/rationale） |
| `review_sheets/samples/教师问题v2_strict金标核验_2026-11-07.xlsx` | 两位核验人逐条确认 strict gold 的核验表（含下拉） |
| `review_sheets/samples/教师问题收集_v2.0_2026-11-07.xlsx` | 教师直接填写的 Excel（说明/填写表/示例/strict 金标说明，含下拉） |
| `review_sheets/samples/教师问题收集_v2.0_2026-11-07.csv` | 同一内容的纯文本版（UTF-8 BOM，Excel 可直接打开） |
| `tools/export_teacher_questions_v2.py` | 从 JSON 模板重新生成上面的 Excel + CSV |

v1 文件（`teacher_questions.schema.json` / `teacher_questions.json`）保留，**不要混改**。

## 2. v1 → v2 的关键变化

| 项 | v1 | v2 |
| --- | --- | --- |
| `expect.strict` | 单个文本 clause | **`chunk_ids` 数组 + `object_type` + `rationale` + `verified_by`** |
| strict 分母 | 有 strict 的条目 | 同左；**strict 目标 30 条（v2.0）** |
| 规模 | 20–40 条 | **60 条**（v2.0），长期 ≥100 |
| 核验 | SQL 核验片段 | **两位核验人独立核验 chunk_id + κ ≥0.70** |
| 训练/调参 | 未明确 | 冻结后不调参；另建 20 条 dev 集 |

`expect.any` 仍然保留：它是 lenient 对照，v2 不会只用 strict。

## 3. 配额

| 类别 | v2.0 条数 | 其中 strict 建议 |
| --- | ---: | ---: |
| 主题词 | 12 | 8（定理 2 / 公式 4 / 题目 2） |
| 题型+知识点 | 12 | 10（公式 2 / 题目 8） |
| 教材概念 | 12 | 12（定义 8 / 定理 4） |
| 年份+卷别 | 12 | 0（any-only） |
| 自然语言要求 | 12 | 0（any-only） |
| **合计** | **60** | **30**（定义 8 / 定理 6 / 公式 6 / 题目 10） |

- strict 只给**唯一确定对象**；多目标/模糊需求只填 `expect.any`，不硬凑 strict；
- 模板的 `strict_plan` 是建议槽位，实际可按教师真实问题调整，但总量要满足 30 条与类型配额。

## 4. 收集流程

1. **选教师**：2–3 位真实高中数学教师，按年级/教龄分层（至少 1 位 >15 年教龄）；不选“技术爱好者”作为全部样本。
2. **收集问题**：在不知道检索实现的前提下，请教师说/写出真正会提的需求；**逐字记录**，不改写成系统友好关键词；一条一个意图，多要求拆条；**不要只收答得对的问题**。
3. **匿名**：用 `T01/T02…` + 年级/教龄段/是否用过 AI；不记录姓名、学校、联系方式。
4. **填模板**：复制 `teacher_questions.v2.template.json` 为 `teacher_questions.v2.json`；填写 `text/contributor/collected_at/intent`；模板字段 `fill_hint/strict_plan` 可在提交前删除（可选）。
5. **核验 expect.any**：第二位核验人在**冻结 DB 快照**上用 SQL 确认片段存在；`expect_verified=true`。
6. **核验 strict 金标**：从 DB 导出精确对象的 `knowledge_chunks.id`，填 `chunk_ids/object_type/rationale/verified_by`；两人独立核验后 `strict_verified=true`。
7. **整份检查**：跑 checker；通过后把 `provenance.status` 改为 `real_teacher`、`real_teacher_confirmed=true`。
8. **冻结**：计算 sha256、记录 DB counts 与 git commit，写 manifest；**冻结后不再调参**。

### 4.1 strict 金标怎么取

```sql
-- 例：某道高考题的题干块
SELECT c.id::text, left(c.text_content, 80)
FROM knowledge_chunks c
JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
JOIN knowledge_sources s ON s.id = dv.source_id
WHERE s.title LIKE '%2024%' AND c.text_content LIKE '%<题干片段>%';
```

- `object_type=question`：填**题干块**；解析/答案块默认不算 gold（除非标注明确说明该题必须含解析块）；
- `object_type=definition/theorem/formula`：填教材对应定义/定理/公式所在块；
- 一个对象被切成多块时，`chunk_ids` 填**全部必要块**；Strict Recall@8 命中任意一块算命中，Strict-all@8 要求全部入 top-8；
- **禁止**用“片段猜测”填 chunk_id；必须来自 DB 实际 id。

### 4.2 判定与一致性

- 两位核验人独立标 hit/no-hit（top-8 是否含 gold），记录分歧；
- 目标 Cohen's κ ≥ **0.70**；低于阈值先对齐规范再继续；
- 分歧由第三人裁决，保留裁决记录；
- `expect.strict.chunk_ids` 不存在 / 拼写错 = 直接 fail。

## 5. 校验

```powershell
# 生成教师填写用的 Excel/CSV（review_sheets/samples/，gitignored）
python tools/export_teacher_questions_v2.py

# 生成 strict 金标核验表（draft gold -> xlsx/csv）
python tools/export_v2_gold_review.py

# 模板结构 + 配额
python tools/check_teacher_questions_v2.py

# 填好的数据集（结构 + 完整性 + strict 配额）
python tools/check_teacher_questions_v2.py --input corpus/eval/teacher_questions.v2.json

# 可选：加 DB 存在性检查（需要 psycopg；.venv 没有 jsonschema，默认用系统 python）
python tools/check_teacher_questions_v2.py --input ... --database-url "postgresql+psycopg://..."
```

- 模板模式检查：60 槽位、五类各 12、strict_plan = 8/6/6/10；
- 数据集模式检查：text 非空、`expect.any` ≥1、`expect_verified` 全 true、provenance=real_teacher、strict ≥30、strict_verified/rationale/verified_by 齐全、chunk_id 为 UUID；
- 退出码：0 通过；2 结构错误；3 完整性错误；4 DB 检查失败。

## 6. 冻结 manifest（建议字段）

```json
{
  "dataset": "teacher_questions.v2.json",
  "sha256": "<sha256>",
  "db": {"sources": 346, "chunks": 12973, "questions": 6981},
  "git_commit": "<commit>",
  "frozen_at": "2026-11-??",
  "counts": {"total": 60, "strict": 30,
             "definition": 8, "theorem": 6, "formula": 6, "question": 10},
  "kappa_hit_no_hit": 0.0,
  "note": "冻结后不调参；调参用独立 20 条 dev 集"
}
```

## 7. 示例（一条 strict 查询）

```json
{
  "id": "Q-C-01",
  "category": "教材概念",
  "text": "补集的定义是什么？",
  "origin": "teacher",
  "contributor": "T01/高一/教龄 3 年/未用过系统",
  "collected_at": "2026-11-08",
  "object_type": "chunk",
  "intent": "find_concept",
  "expect": {
    "any": ["补集"],
    "strict": {
      "chunk_ids": ["00000000-0000-0000-0000-000000000000"],
      "object_type": "definition",
      "rationale": "教材中补集定义的正文块；该定义只占一块。",
      "verified_by": ["V01", "V02"],
      "verified_at": "2026-11-08"
    }
  },
  "expect_verified": true,
  "strict_verified": true,
  "notes": "示例只用占位 UUID；真实填写必须来自 DB。"
}
```

## 8. v2.0 与 v2.1

| 版本 | 规模 | 用途 |
| --- | --- | --- |
| v2.0 | 60 条 / 30 strict | 阶段 6 初期验收；strict ≥70% 只作初期信号 |
| v2.1 | ≥100 strict（定义 25/定理 20/公式 20/题 35） | 长期回归/发布门禁；strict 门槛建议 ≥80%（待定） |

v2.0 冻结后不调参；v2.1 单独冻结，不覆盖 v2.0。每季度或语料大版本增补 ≥20 条。

**首批 draft 状态（2026-11-07）**：60 条来自 `问题收集1.txt`（T01/T02/T03）；20 条 strict 为 SQL 候选（定义 9 / 定理 6 / 公式 5），`strict_verified=false`，待两位人工核验。偏差：B01 焦点弦长无独立教材公式块，按“不硬凑 strict”降为 any-only；B02 切线方程以“导数几何意义=切线斜率”段为 canonical strict；题目类 strict 暂不纳入。核验表：`review_sheets/samples/教师问题v2_strict金标核验_2026-11-07.xlsx`。

## 9. 禁止事项

- 把模拟候选写成 `origin=teacher`；
- 只收集系统答得对的问题；
- 用片段/记忆填 chunk_id，不查 DB；
- 冻结后按评测结果调检索参数；
- 把 v2.0 的 70% 与 v2.1 的 80% 混读。
