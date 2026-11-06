---
type: report
title: 教材块级知识点链接投影（03_Textbooks 块级 kp Wikilink，2026-11-06）
updated: 2026-11-06
---

# 教材块级知识点链接投影（03_Textbooks 块级 kp Wikilink）

> 返回 [[首页]] ｜ 相关 [[KB_SYNC_CONTRACT]] ｜ 工具 `tools/project_restricted_corpus.py` ｜
> 数据源 PG `textbook_block_annotations`（active 行）｜ 投影目标 `03_Textbooks/**`

## 0. 结论（task-3 dry-run + task-4 真实写入）

- 投影工具已支持：**每个教材块原文后输出该块的知识点 Wikilink 行**，数据取自 PostgreSQL
  `textbook_block_annotations` 的 active 行（`superseded_by IS NULL`），**PG 仍是唯一事实源（SSOT）**，
  Obsidian 只是派生投影。
- task-3（v3 数据）dry-run：**5 册 / 1797 块全部命中链接计数，删除链接行后与 vault 原文逐字节 0 差异，
  链接目标 missing 0，mock/gaokao 投影 0 改动，连续两次 dry-run 输出一致**。
- task-4（v4 数据）已真实写入：**5 册 1797 块，知识点链接 1737 条（teacher 331 = `teacher 已核`、
  model 1406 = `模型待复核`），`vocab_gap` 8 条「待补」，`non_content` 52 块无链接行**；
  写后原文 0 差异、目标 missing 0、二次 dry-run 0 变更（幂等）、高考卡 sha256 未变。详见 §8。
- v3 → v4 链接变化（工具无需改动，随 PG 自动更新）：mapped 1711 → **1737**（teacher 331 不变，
  model 1380 → 1406），vocab_gap 34 → **8**，non_content 52 不变。

## 1. 链接格式

每个教材块的渲染顺序固定为：`md_body(原文)` 段落 → 空行 → 链接行（`non_content` 无链接行）。
链接行紧跟块原文，其后**不再加空行**，因此删除所有 `> 知识点：` 行即可逐字节还原投影原文。

| 块类型 | 输出（逐字，含全角空格 `　` 与 `·`） |
| --- | --- |
| teacher 已核（mapped） | `> 知识点：[[kp_04_09_cosine|余弦定理]]　·　teacher 已核` |
| 模型待复核（mapped） | `> 知识点：[[kp_04_09_cosine|余弦定理]]　·　模型待复核` |
| 有 secondary 的 mapped | `> 知识点：[[kp_12_03_basic|基本不等式]]　·　模型待复核（兼 [[kp_02_03_range|值域与最值]]）` |
| vocab_gap（词表缺口） | `> 知识点：待补（vocab_gap）` |
| non_content（非正文） | （不输出链接行） |

规则细节：

- 显示名从 `corpus/eval/kp_vocab.md` 的表格行解析（``| `kp_xx_yy_slug` | 名称 | 定义 |``，共 120 条）；
  词表缺名时退化为裸链接 `[[kp_id]]`（不造名称、不造笔记）。
- `teacher` 来源 → `teacher 已核`；其余来源（model / rule）→ `模型待复核`（真人核验优先，机器标注待复核）。
- secondary 追加在**同一行尾部**，多个用 `、` 分隔。
- 前端（Obsidian）看到的是块级双链：`05_KnowledgePoints` 里任一 kp 笔记的反向链接面板会自动出现
  引用它的教材块位置，无需手工维护双向链接。

frontmatter 新增可审计计数（追加在 `chunk_count` 之后、`human_edited` 之前，不破坏既有字段与
`generated_at` 幂等比较）：

```yaml
chunk_count: 549
kp_link_count: 507
kp_link_teacher: 66
kp_link_model: 441
kp_link_vocab_gap: 27
human_edited: false
```

## 2. dry-run 计数（v3 PG，2026-11-06）

命令（默认 dry-run，不写文件）：

```powershell
.venv\Scripts\python.exe tools/project_restricted_corpus.py `
  --vault "<vault 路径>" --only textbook --force-generated
```

| 册 | 块数 | 链接（mapped） | teacher | model | vocab_gap | non_content |
| --- | --- | --- | --- | --- | --- | --- |
| 必修第一册 | 549 | 507 | 66 | 441 | 27 | 15 |
| 必修第二册 | 468 | 449 | 64 | 385 | 7 | 12 |
| 选择性必修第一册 | 277 | 269 | 67 | 202 | 0 | 8 |
| 选择性必修第三册 | 290 | 281 | 67 | 214 | 0 | 9 |
| 选择性必修第二册 | 213 | 205 | 67 | 138 | 0 | 8 |
| **合计** | **1797** | **1711** | **331** | **1380** | **34** | **52** |

PG active 行对账（`textbook_block_annotations WHERE superseded_by IS NULL`）：

```
status/classification_source/review_status
mapped / teacher / reviewed      331
mapped / model   / needs_review 1380
non_content / teacher / reviewed 29
non_content / model / needs_review 23
vocab_gap / model / needs_review  34
总计 1797
```

- 链接行 1711 = PG `status='mapped'` 1711 ✔（teacher 331 / model 1380 完全一致）
- `vocab_gap` 行 34 = PG 34 ✔；`non_content` 52 块无链接行 ✔
- 块数 1797 = 5 册 `chunk_count` 之和 ✔（1797 = 1711 + 34 + 52）
- 不同 kp_id 84 个，Wikilink 出现 1717 次（1711 主链接 + 6 个 secondary）
- **链接目标 missing 0**：84 个 kp_id 全部能在 `05_KnowledgePoints/**/kp_*.md`（133 个笔记）找到；
  词表缺名 0（所有链接都带中文别名）

## 3. 原文 0 差异证据

验收脚本 `var/vault_backup/verify_textbook_links.py`（不写 vault）：把生成内容里的
`> 知识点：` 行全部删掉后，与现有 vault 文件比较（忽略 `generated_at`/`updated` 与**新增审计计数行**；
计数本身单独与 PG 对账），0 差异：

```
[OK] 必修第一册/必修第一册.md: 块 549，链接 507（teacher 66 / model 441），vocab_gap 27，non_content 15，
     删链接行后原文 0 差异；默认状态=skip_conflict，--force-generated=write
[OK] 必修第二册/必修第二册.md: 块 468，链接 449（teacher 64 / model 385），vocab_gap 7，non_content 12，
     删链接行后原文 0 差异；...
[OK] 选择性必修/选择性必修第一册/选择性必修第一册.md: 块 277，链接 269（teacher 67 / model 202），
     vocab_gap 0，non_content 8，删除链接行后原文 0 差异；...
[OK] 选择性必修/选择性必修第三册/选择性必修第三册.md: 块 290，链接 281（teacher 67 / model 214），
     vocab_gap 0，non_content 9，删除链接行后原文 0 差异；...
[OK] 选择性必修/选择性必修第二册/选择性必修第二册.md: 块 213，链接 205（teacher 67 / model 138），
     vocab_gap 0，non_content 8，删除链接行后原文 0 差异；...
[PASS] 全部验收项通过
```

同时校验：

- 每个链接行上一行必为空行、且位于某个 `## 第 N 页` 之下（链接紧跟对应块）；
- **每页链接行数 = 该页 PG mapped+vocab_gap 块数**，且 primary kp 顺序与 PG 查询顺序一致（位置正确）；
- 含 secondary 的链接行 5 条 / secondary 链接 6 个 = PG `jsonb_array_length(kp_secondary)` 汇总；
- 5 册 `chunk_count` 与投影前一致（549/468/277/290/213），frontmatter 计数与 PG 逐册一致。

## 4. mock / gaokao 回归（不得有变化）

- `git diff` 只改动 `tools/project_restricted_corpus.py` 的：教材查询（`fetch_data` + 新增
  `textbook_rows_sql`）、教材渲染（`build_textbooks` + 新增 3 个纯函数）、以及 additive 的
  console/计数行；mock 分支代码未动。
- 用 `git show HEAD` 的原版工具对照（同一 PG、同一输出路径）：
  - mock 生成文件 998 个**逐字节相同 998**，mock stats 相同，2 个总览索引**逐字节相同**；
  - mock+index 写入状态**完全一致（差异 0）**；
  - 原版工具对 5 册教材生成结果仍是 `unchanged`（证明差异全部来自本次新增链接行/计数行）；
  - 新工具 `--only mock` dry-run：`write=0 unchanged=998`（mock 输出无变化）。
- `--only textbook` 路径不触碰 `10_Indexes/**`、`08_Review/迁移记录` 等状态文档。

## 5. 幂等与写入安全

- 连续两次 dry-run（同一命令、间隔 1.1s）：stdout **完全一致**；manifest 去掉
  `generated_at` 与内容 sha（sha 含时间戳）后**完全一致**，`planned_write=5`、计数相同。
- 现行安全策略：已有文件带 `generated_from: postgres` + `human_edited: false` 且内容变化时，
  默认判为 `skip_conflict`（**不静默覆盖**），dry-run 显示 `safe={'skip_conflict': 5}`；
  加 `--force-generated` 才转为 `write=5`（本工具生成物的既有刷新开关）。
  5 册当前均 `human_edited: false`，`skip_human=0`。
  因此 task-4 真实写入必须带 `--force-generated`（不改默认安全语义，避免误覆盖）。
- `human_edited: true` 的文件永远 `skip_human`，不会被覆盖。
- 标注表缺失/不可读时安全回落：用 `to_regclass` 判断 + try/except，查询改为 NULL 列占位；
  实测 `textbook_rows_sql(False)` = 1797 行 / 12 列 / 标注列全 NULL，且渲染输出
  **0 条链接行、与原文基线一致 5/5、计数全 0**——新库/空库照常可投影。
- 投影报告/manifest 仍写 `var/projection/`（gitignored），不写 vault。

## 6. 可重建性与 KB_SYNC_CONTRACT 边界

- **可重建**：`03_Textbooks/**` 是 PG 的派生投影（`generated_from: postgres`），任何时候都可用
  `tools/project_restricted_corpus.py --apply --only textbook --force-generated` 从 PG 重生成；
  PG 数据变化（如 v3 → v4 映射修订）后重跑即可刷新链接与计数，无需手工改 vault。
- **单向**：投影不把 Obsidian 的改动回写 PG；人工改投影会在下次投影被覆盖。要修正知识点归属，
  应改 PG/标注流程后重跑投影（与契约 §3.2「方向 B：只投影，不产生新事实」一致）。
- **双向链接是 Obsidian 自动行为**：块级 Wikilink 让 kp 笔记的反向链接面板自动列出教材出处，
  不需要在 `05_KnowledgePoints` 反向写链接；本任务未改 `05_KnowledgePoints`。
- 契约文件 `docs/KB_SYNC_CONTRACT.md` **未改**（由 Lead 统一更新；建议在其「§11 受限资料投影」
  和「§10 待办/进度」中补充"教材块级 kp 链接"条目与本次验收结论）。
- 设计总文档 / README / 其他 vault 目录均未改；未 commit。

## 7. 数据版本说明与风险

- §2 的计数是 **v3 映射的历史 dry-run**（teacher 331 / model 1380 / vocab_gap 34 / non_content 52）；
  task-4 已经在 **v4 映射**（teacher 331 / model 1406 / vocab_gap 8 / non_content 52）上真实写入，
  真实数字见 §8。工具本身不写死任何映射数字，链接与 frontmatter 计数完全由 PG 决定。
- `--force-generated` 是 task-4 写入的必要开关（见 §5）；若误对 mock/全量使用该开关，会同时刷新
  mock 生成物——task-4 严格限定 `--only textbook`，写入后面板 mtime 显示只有 5 册教材 md 变化。
- 链接显示名依赖 `corpus/eval/kp_vocab.md`；v4 数据中 80 个 kp_id 全部有中文名（缺名 0），若后续
  引入新 kp_id 而词表缺名，链接会退化为裸 `[[kp_id]]`（不报错、不造笔记），报告会统计"缺别名"数量。
- OCR 原文中若出现行首 `> 知识点：` 的字面内容，会被"删链接行"的对比口径误判；当前 1797 块
  实测 0 例（v4 删除行数 1745 = 链接行 1737 + vocab_gap 行 8）。

## 8. 真实写入结果（v4）

### 8.1 前置（PG v4，task-2 完成态）

```
active 行 1797 / unique chunk 1797
status：mapped 1737（teacher 331 + model 1406）、non_content 52、vocab_gap 8
model 行 model_version = textbook-map-v4-2026-11-06；teacher 行 model_version = textbook-review-2026-11-06
```

### 8.2 备份（写前 v3 无链接投影，可回滚）

目录：`D:\Chilon\var\vault_backup\textbooks_before_links_2026-11-06\`（相对 `03_Textbooks/**`
保留路径；`SHA256SUMS.txt` 写前、`AFTER_APPLY_SHA256SUMS.txt` 写后；复制时逐文件 sha256 校验一致）。
备份的是**v3 无链接投影**，可用于完整回滚。

| 册 | 写前 sha256（备份，回滚校验用） | 写后 sha256（vault） | 行数 前→后 |
| --- | --- | --- | --- |
| 必修第一册 | `7b51638e149b80ccc27c116d535ca941a61d79515686fcdb5a6af496f2fa37f2` | `688c34bc3c53ecdb27248a2995647c4892b5c28abf2b5d950254c8df4f37415a` | 1669 → 2207 |
| 必修第二册 | `2cdfb5507bcd4862b25df90f5bd165a0038c70dee9013c4e4512aa6da25b73fd` | `52fec326ebd4a45a9b873b9fd768320c71425771043d6386757ba80d2f0183f1` | 1525 → 1985 |
| 选择性必修第一册 | `3e1e940e37f3fa7633ff3f8434e9ecac8b5b6a7f2964287481d47c0470711152` | `035b7433be7c30fff9c4269639482f875c32d46e035a62403c9699a7206c0cba` | 895 → 1168 |
| 选择性必修第二册 | `ad22f4a5c1ea3d499f7025b9e15b72f3e8231e103fcc34c3d630c54d7565e7ad` | `736d05cebd43569bf3d3b70a8b101ceacb76cfef5174507cd1fffaf3bda84bcd` | 685 → 894 |
| 选择性必修第三册 | `7b47d7f67d5a2f76fdfeda3f6edc8bc0d8cd9667591e7e6d83665f2d752950cb` | `b2d02358d1a7ed9d3bb25e393ec1bc0cf444e5306377a4bec7da2af005c21cd5` | 923 → 1208 |

行数增加合计 1765 = 1745 条链接行（1737 知识点 + 8 待补）+ 20 行 frontmatter 计数（4×5 册）。

### 8.3 dry-run → apply

```powershell
# 写前 dry-run（v4）
.venv\Scripts\python.exe tools/project_restricted_corpus.py `
  --vault "<vault 路径>" --only textbook --force-generated
```

```
[计划] 文件：write=5 unchanged=0 skip_human=0 skip_foreign=0 skip_conflict=0
        教材：5 册 / 1797 块
        教材块级链接：teacher=331 model=1406 （链接合计 1737）；vocab_gap=8 non_content=52
        无标注=0 缺主标注=0
```

确认后真实写入（同一命令加 `--apply`）：

```
[写入] 新写 5 个文件；幂等不变 0；跳过 0
[高考卡] 6324 张，聚合 sha256 87f6a569fc955f9a… → 6324 张，sha256 87f6a569fc955f9a… ✅ 未变
```

- 写入范围：只有 5 个教材 md 变化（写后 25 分钟内 vault 内被修改的 md 仅这 5 个；`04_Exams`、
  `05_KnowledgePoints`、`10_Indexes`、`08_Review` 等目录最新 mtime 均早于本次写入）。
- `--only textbook`：未投影 mock、未改 `10_Indexes/**`、未改 `08_Review/迁移记录`。

### 8.4 写后计数（frontmatter 与真实链接行对账）

| 册 | chunk_count | kp_link_count | teacher | model | vocab_gap | non_content | 实际链接行 | 实际待补行 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 必修第一册 | 549 | 526 | 66 | 460 | 8 | 15 | 534 | 8 |
| 必修第二册 | 468 | 456 | 64 | 392 | 0 | 12 | 456 | 0 |
| 选择性必修第一册 | 277 | 269 | 67 | 202 | 0 | 8 | 269 | 0 |
| 选择性必修第二册 | 213 | 205 | 67 | 138 | 0 | 8 | 205 | 0 |
| 选择性必修第三册 | 290 | 281 | 67 | 214 | 0 | 9 | 281 | 0 |
| **合计** | **1797** | **1737** | **331** | **1406** | **8** | **52** | **1745** | **8** |

对账：1737 = teacher 331 + model 1406 = PG active mapped ✔；1745 条 `> 知识点：` 行 =
1737 链接 + 8 待补 ✔；1797 = 1737 + 8 + 52 ✔；5 册 `chunk_count` 与写前备份完全一致
（549/468/277/213/290）✔；`human_edited: false` 保持 ✔。

### 8.5 原文 0 差异 / 目标 / 幂等（写后复验）

验收脚本（对比**写前备份**，忽略 `generated_at`/`updated` 与新增 `kp_link_*` 计数行）：

```
[OK] 必修第一册/必修第一册.md: 块 549，链接 526（teacher 66 / model 460），vocab_gap 8，non_content 15，
     删链接行后原文 0 差异
[OK] 必修第二册/必修第二册.md: 块 468，链接 456（teacher 64 / model 392），vocab_gap 0，non_content 12，
     删链接行后原文 0 差异
[OK] 选择性必修/选择性必修第一册/选择性必修第一册.md: 块 277，链接 269（teacher 67 / model 202），
     vocab_gap 0，non_content 8，删链接行后原文 0 差异
[OK] 选择性必修/选择性必修第三册/选择性必修第三册.md: 块 290，链接 281（teacher 67 / model 214），
     vocab_gap 0，non_content 9，删链接行后原文 0 差异
[OK] 选择性必修/选择性必修第二册/选择性必修第二册.md: 块 213，链接 205（teacher 67 / model 138），
     vocab_gap 0，non_content 8，删链接行后原文 0 差异
[PASS] 全部验收项通过
```

- 链接目标：80 个不同 kp_id、1743 次 Wikilink（1737 主 + 6 secondary），
  **全部存在于 `05_KnowledgePoints/**/kp_*.md`（missing=0）**，缺别名 0。
- 位置：每页 `> 知识点：` 行数 = 该页 PG mapped+vocab_gap 块数；primary kp 顺序 = PG 顺序。
- 幂等：写后再次 dry-run（默认安全模式，无 `--force-generated`）：
  `write=0 unchanged=5 skip_human=0 skip_conflict=0` → **0 变更**。
- mock 回归：998 个 mock 投影文件与 vault 逐字节一致（差异 0）。

### 8.6 抽样（每册 teacher/model，另含 vocab_gap；链接紧跟对应块原文）

```
[必修第一册 · teacher] 原文: 第一章 集合与常用逻辑用语 我们知道，方程 x ^ { 2 } = 2 在有理数范围内无解…
    > 知识点：[[kp_01_01_concept|集合的概念与表示]]　·　teacher 已核
[必修第一册 · model]   原文: 1.1 集合的概念 在小学和初中，我们已经接触过一些集合…
    > 知识点：[[kp_01_01_concept|集合的概念与表示]]　·　模型待复核
[必修第一册 · vocab_gap] 原文: 例2 海水受日月的引力，在一定的时候发生涨落的现象叫潮…
    > 知识点：待补（vocab_gap）

[必修第二册 · teacher] 原文: \overrightarrow { M C } = \frac { 1 } { 2 } \overrightarrow { A C } = …
    > 知识点：[[kp_05_01_concept|向量概念与线性运算]]　·　teacher 已核
[必修第二册 · model]   原文: 第六章 平面向量及其应用 在现实生活中，我们会遇到很多量…
    > 知识点：[[kp_05_01_concept|向量概念与线性运算]]　·　模型待复核

[选择性必修第一册 · teacher] 原文: 第一章 空间向量与立体几何 通过“平面向量及其应用”的学习…
    > 知识点：[[kp_08_07_vector|空间向量法]]　·　teacher 已核
[选择性必修第一册 · model]   原文: 1.1 空间向量及其运算 章前图展示的是一个做滑翔伞运动的场景…
    > 知识点：[[kp_08_07_vector|空间向量法]]　·　模型待复核

[选择性必修第二册 · teacher] 原文: - \frac { 1 } { 2 } ， \frac { 1 } { 4 } ， - \frac { 1 } { 8 } …
    > 知识点：[[kp_07_01_concept|数列的概念与通项]]　·　teacher 已核
[选择性必修第二册 · model]   原文: 第四章 数 列 对数列的研究源于现实生产、生活的需要…
    > 知识点：[[kp_07_08_induction|数学归纳法]]　·　模型待复核

[选择性必修第三册 · teacher] 原文: 第3类方案是从第 3层取1本体育书，有2种方法。根据分类加法计数原理…
    > 知识点：[[kp_11_01_principle|两个计数原理]]　·　teacher 已核
[选择性必修第三册 · model]   原文: 第六章 计数原理 汽车号牌的序号一般是从26个英文字母、10个阿拉伯数字…
    > 知识点：[[kp_11_01_principle|两个计数原理]]　·　模型待复核
```

### 8.7 回滚

备份可直接回滚（写前 v3 无链接投影）：

```powershell
Copy-Item -Recurse -Force `
  "D:\Chilon\var\vault_backup\textbooks_before_links_2026-11-06\*" `
  "<vault 路径>\03_Textbooks\"
# 回滚后用 SHA256SUMS.txt 校验
```

或直接用 PG 重投影（`--force-generated`）重建当前派生层；两种方式都不影响 PG 事实源。


