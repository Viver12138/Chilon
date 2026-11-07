---
type: report
title: 教材块知识点标注 · 最终交接报告（冻结版）
updated: 2026-11-07
status: frozen
freeze: textbook-annotations-v8-frozen
---

# 教材块知识点标注 · 最终交接报告（冻结版）

> 范围：人教 A 版 5 册教材 **1797 个 OCR 块**的知识点（kp）标注。
> 架构不变：**PostgreSQL 是唯一事实源（SSOT）**，Obsidian `03_Textbooks` 是派生投影，Qdrant 是派生索引。
> 本报告冻结日期 **2026-11-07**；冻结标签 `textbook-annotations-v8-frozen`（指向包含本报告的提交）。

## 0. 一页结论

- 教材块标注 **1797/1797 全部教师复核**：`classification_source=teacher`、`review_status=reviewed`，PG 中 **model 行 0**。
- 最终状态：mapped **1595** / non_content **191** / vocab_gap **11**（vocab_gap = 教师确认内容、但词表无合适主考点，保留模块）。
- 自动映射引擎冻结在 **v8**；v8 在全部教师标签上 in-sample exact **1561/1590 = 98.2%**、module **1583/1590 = 99.6%**。
  - **重要**：1797 已全被教师标注，**没有 fresh holdout**；98.2% 是拟合值，**不是泛化准确率/对外承诺**。
  - 最诚实的 fresh 参考：第五批 671 全量终检时 v7 的 exact **500/564 = 88.7%**（该批在 v8 调参前）。
- Obsidian 5 册重投影：**1606 条**「知识点」行 = **1595 条 kp 链接**（全部 teacher 已核）+ **11 条待补（vocab_gap）**；non_content 191 块无链接。
- 校验：`check_all` **17/17**；链接目标 missing 0；删链接行后与写前投影 0 差异；二次 dry-run 0 变更；`knowledge_annotations` **9092 未变**。
- 本地冻结备份：`var/freeze/textbook_block_annotations_final_2026-11-07.json`（1797 行，sha256 `39d19847980c81c509d0c6771dc467ce61a2cfc37c560fdbf7e6c859080df804`）。

## 1. 最终数据状态（PG `textbook_block_annotations`）

| 项 | 值 |
| --- | --- |
| active 行 / 唯一 chunk | **1797 / 1797**（无 superseded 历史行） |
| classification_source | teacher **1797** / model **0** |
| review_status | reviewed **1797** |
| status | mapped **1595**、non_content **191**、vocab_gap **11** |
| teacher 版本（按批） | 360（`textbook-review-2026-11-06`）、288（`v4-round2`）、310（`v5-round3`）、168（`v6-round4`）、671（`v7-round5`） |
| `knowledge_annotations` active | **9092**（未变） |
| 教材 chunk 总数 | 1797（5 册：549 / 468 / 277 / 290 / 213） |

### 1.1 vocab_gap 11 条（验收清单，不是漏标）

| block | 模块 | 教师备注 |
| --- | --- | --- |
| TB-B1-0040-1 | kp_01_set_logic | 章小结综合，不宜单标量词 |
| TB-B1-0041-1 | kp_01_set_logic | 复习参考题综合，不宜单标量词 |
| TB-B1-0108-3 | kp_02_function | 函数性质综合，考点宜综合/留空 |
| TB-B1-0259-1 | kp_04_trig | 章小结综合，不宜单标同角关系 |
| TB-B1-0259-2 | kp_04_trig | 章小结综合，不宜单标任意角定义 |
| TB-B2-0063-1 | kp_04_trig | 数学文化/面积公式阅读，建议不硬塞 |
| TB-B2-0105-1 | kp_08_solid | 基本立体图形结构，词表缺对应 |
| TB-B2-0105-2 | kp_08_solid | 基本立体图形结构，词表缺对应 |
| TB-B2-0109-1 | kp_08_solid | 圆锥/圆台/球结构，词表缺对应 |
| TB-B2-0110-1 | kp_08_solid | 简单组合体结构，词表缺对应 |
| TB-B2-0229-1 | kp_10_prob_stat | 章小结综合，不宜单标数字特征 |

## 2. Obsidian 派生层（`03_Textbooks/**`）

| 文件 | 链接行 | sha256 |
| --- | ---: | --- |
| 必修第一册.md | 487 | `0788d6aa18545494c435a5bbb747b39dd226a0d53abc3e4fea5306cff8787390` |
| 必修第二册.md | 420 | `a37b086f0f9538b1d2a0f170aad29705746f3a77b280caad0252fa44a93a66e8` |
| 选择性必修第一册.md | 248 | `67e34164bcf4e62d8287a7a5d28216d89b53660e08201a9d91c60c4971e9a897` |
| 选择性必修第二册.md | 188 | `339c16b111c230e36a99f3248ba6e2e762bbf01d43f88d9a13246d7cf04017dd` |
| 选择性必修第三册.md | 263 | `fc483dc4f0fba66bd34b848e59b46a189b18e3eb5a15a779c6af89087c74359f` |
| **合计** | **1606** | — |

- 每块渲染：原文 → 空行 → `> 知识点：[[kp_id|名称]]　·　teacher 已核`；vocab_gap 为 `> 知识点：待补（vocab_gap）`；
- 删除所有 `> 知识点：` 行即可逐字节还原原文投影（本轮实测 5/5 册 0 差异）；
- 重建方式：`tools/project_restricted_corpus.py --apply --only textbook --force-generated`；`human_edited: true` 永远跳过。

## 3. 阶段历程（本轮会话）

| 阶段 | 内容 | 关键数字 | 记录 |
| --- | --- | --- | --- |
| D.104 | PG draft 表 + 1797 写入（teacher 360/model 1437） | — | `1d43eda` |
| D.105 | v4 规则修 360 复核 74 条 | 360 exact 253→327 | `6fb81cc` |
| D.106 | Obsidian 块级 kp 链接 | 1737 链接 | 同上 |
| D.107 | 第二批 288 回填 | v4 84.8%，v3 74.1% | `0b56037` |
| D.108 | v5 修 5 条 + 第三批 310 表 | 648 94.0% | `b7d2cd4` |
| D.109 | 第三批 310 回填 | teacher 958、链接 1714 | `5a5e3bf` |
| D.110 | v6 修 8 条 + 第四批 168 表 | 958 96.0% | `4759b39` |
| D.111 | 第四批 168 回填（fresh） | v6 85.3% | `42c967a` |
| D.112 | v7 修 23 条 | 1026 集 96.9% | `b3e30dc` |
| D.113 | 剩余 671 全量终检表 | 671 行 | `344d6c4` |
| D.114 | 671 全量回填：teacher 100% | v7 fresh 88.7%；全量 93.7% | `00b98dc` |
| D.115 | v8 修终检 64 条（in-sample） | 1561/1590 = 98.2% | `2400320` |
| D.116 | **冻结 + 交接** | — | tag `textbook-annotations-v8-frozen` |

## 4. 质量口径与证据

### 4.1 准确率（教师标签为准）

| 集合 | 分母 | v7 exact | v8 exact |
| --- | ---: | ---: | ---: |
| 360 第一批 | 327 | 327 | 327 |
| 288 第二批 | 270 | 238 | **241**（+3 同向顺带） |
| 310 第三批 | 273 | 273 | 273 |
| 168 第四批 | 156 | 156 | 156 |
| 671 第五批 | 564 | 500 | **564** |
| **合计** | **1590** | **1494 = 94.0%** | **1561 = 98.2%** |

- 1595 口径（把 5 条“model 判 non_content、教师给内容标签”计入）为 1561/1595 = 97.9%；
- 第五批全量终检在 v8 调参前是 **500/564 = 88.7%**，这是最后一次不受调参污染的 fresh 估计；
- **无 fresh holdout**：1797 全部进入已标注集，v8 98.2% 是 in-sample 拟合，不能对外当准确率。

### 4.2 校验证据

- `python tools/check_all.py` → **17/17**；
- PG：active 1797/unique 1797；teacher 1797/model 0；status 1595/191/11；`knowledge_annotations` 9092；重复 apply dry-run 0 变更；
- vault：链接 1595 + 待补 11；missing 0；原文 0 差异；二次 dry-run 0 变更；高考卡 6324 张 sha256 未变；
- 冻结 dump sha256：`39d19847980c81c509d0c6771dc467ce61a2cfc37c560fdbf7e6c859080df804`。

## 5. 产物清单

### 5.1 已提交（git）

- 规则引擎：`tools/kb_textbook_map_v3.py` … `v8.py`（v8 冻结版）；
- 数据工具：`tools/kb_textbook_pg_draft.py`、`tools/project_restricted_corpus.py`、`tools/kb_textbook_review_round3_apply.py`（通用回填解析）、`tools/kb_textbook_sample_review.py`、`tools/kb_textbook_sample_v5_combined.py`；
- 报告：`docs/textbook_map_*.md`、`docs/textbook_review_*.md`、`docs/textbook_sample_*.md`、本交接报告；
- 设计总文档 D.104–D.116、`README.md`、`docs/KB_SYNC_CONTRACT.md`（§11 投影契约）。

### 5.2 本地（`var/`，gitignored，交接时需归档）

- 冻结 dump：`var/freeze/textbook_block_annotations_final_2026-11-07.json` + `.sha256`；
- reviewed 映射：`var/textbook_mapping/mapped_1797_reviewed_round5.json`、`mapped_1797_reviewed_v8.json`；
- 回填解析：`var/textbook_mapping/review_round2/3/4/5_parsed.json`；
- PG 备份：`var/textbook_mapping/backup_pg_draft_before_{round3,round4,round5,v6,v7,v8}_*.json`；
- 每批 5 册投影备份：`var/vault_backup/textbooks_before_round{3,4,5,5}_*`；
- **注意**：`var/` 不入库，PG 是 SSOT；移交时请把 `var/freeze/` 与 `var/vault_backup/` 一并归档。

## 6. 复现 / 重建

```powershell
# 1) 全量静态检查
python tools/check_all.py                 # 17/17

# 2) PG 计数（口令从容器读，勿写死）
docker exec chilon-pg-corpus printenv POSTGRES_PASSWORD
# SQL：SELECT count(*) FROM textbook_block_annotations WHERE superseded_by IS NULL;  -- 1797

# 3) 重建 Obsidian 教材投影（先 dry-run，再 --apply）
$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe tools/project_restricted_corpus.py `
  --vault "<vault 路径>" --only textbook --force-generated
# 二次 dry-run 应为 write=0 unchanged=5

# 4) 规则重跑（需要 var/textbook_mapping 中间件；不在 git）
python tools/kb_textbook_map_v8.py --stage map
python tools/kb_textbook_map_v8.py --stage eval

# 5) PG 回填（dry-run → apply；本阶段已冻结，除必要修复外不要 apply）
.venv\Scripts\python.exe tools/kb_textbook_pg_draft.py `
  --reviewed var/textbook_mapping/mapped_1797_reviewed_v8.json `
  --model-version textbook-map-v8-2026-11-07 `
  --backup var/textbook_mapping/backup_pg_draft_before_v8_2026-11-07.json
```

## 7. 未决项 / 后续建议

1. **29 条历史仍错**（非 v8 的 64 目标，分布在 288 等旧批）与 **5 条“教师给内容、model 判 non_content”的标签**：另立任务逐条诊断，不要为了刷分再改规则。
2. **11 条 vocab_gap**：若未来词表新增“空间几何体结构 / 复数三角表示”等条目，可回填这 11 条；否则保持待补。
3. **191 条 non_content**：含章导引/阅读/数学建模/词汇索引，建议作为“非内容标注验收清单”抽查。
4. **`model_version` 语义变化**：现在存的是 teacher 批次版本（无 model 行）；未来 schema 可考虑拆 `teacher_version`/`engine_version` 两列。
5. **DB 迁移历史**：现有库由旧 schema 初始化，未跑全量 `alembic upgrade`；新库请用 `0001_baseline + 0002` 重建（D.104 已记录）。
6. **仓库未 push**：本地 `main` 领先 `origin/main`；冻结提交后请按流程推送/打远端 tag。
7. **未来新块**：必须冻结 v8 + 用新增块做 fresh holdout，再谈准确率；禁止在 1797 上继续调参后自称泛化。

## 8. 交接清单（给下一位维护者）

1. 先读本报告 + `Chilon_Project_Design_Master_Document.md` D.104–D.116 + `docs/KB_SYNC_CONTRACT.md` §11；
2. 记住三条铁律：**PG 是 SSOT**；**Obsidian 只读投影/人工编辑走同步契约**；**不要直接改 vault 再当事实**；
3. 改数据流程：改 PG/标注 → 重投影 → 用 `check_all` + 本报告 §4.2 的校验清单回归；
4. 改规则流程：新工具版本（v9…）+ fresh holdout + 保留本冻结快照，不做破坏性覆盖；
5. 归档 `var/freeze/`、`var/vault_backup/`、PG 备份；远端 tag 与 commit 对齐后再对外交付。

---

> 冻结标签：`textbook-annotations-v8-frozen`（`git rev-list -n1 textbook-annotations-v8-frozen` 获取提交）。
> 引擎版本：v8；教师标注：1797/1797；PG active 1797；vault 1606 行（1595 kp + 11 待补）。
