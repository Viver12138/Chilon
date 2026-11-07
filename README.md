# Chilon

面向高中数学教师（高考）的 AI 教学工作台。设计与契约已冻结；核心业务闭环（需求 → 方案审批 → 执行 → 发布 → 导出）、数据库、服务端教师界面与知识库摄入/检索均已有实现与对应测试。**尚未做真实教师验收**，检索质量与知识库标注仍是已知欠账（见文末）。

![contracts](https://github.com/Viver12138/Chilon/actions/workflows/check.yml/badge.svg)

## 定位（2026-11-06）

项目分两层，当前重点是下面这层：

- **知识库（底座，当前建设重点）**：教材、高考真题、模拟题、结构化题目、知识点与检索。技术设计见 [高中数学知识库系统技术设计文档 V1.2](docs/高中数学知识库系统技术设计文档_V1.2.md)，它是知识库层的权威文档。
- **旧工作台（未来上层）**：任务 → 方案审批 → 执行 → 发布 → 导出。**保留、不删除、暂不扩张**，等知识库完整后再套上；D1–D6 仍是这一层的设计基线。

数据权威：**PostgreSQL 是唯一事实源（SSOT）**；Obsidian 只做知识编辑与人工审校，改动经同步程序回写 PG；Qdrant 是派生索引，可从 PG 重建。决策记录见 [D.87](Chilon_Project_Design_Master_Document.md#d87-2026-11-06-定位决策知识库是底座pg-是唯一事实源)。

## 文档

- [Chilon 使用说明（教师版）](docs/Chilon-用户功能说明.md) —— 面向老师的用法说明，不含技术细节
- 设计基线：`Chilon_Project_Design_Master_Document.md`（技术向）

## 这个仓库里有什么

```text
Chilon_Project_Design_Master_Document.md   设计与契约基线（139 个章节、AD 记录 D.1–D.104）
docs/                                       教师版说明、V1.2 知识库技术设计（知识库层权威）、KB 同步契约
docs/mock_ocr_backlog_2026-11-06.md         模拟题 39 题 OCR 需求清单（只统计，未调用）
design/                                     设计分册 D1–D6、K09 字段设计、走查包、校验器
schemas/                                    机器可读契约（状态机、动作、接口、导航、测试矩阵）
database/registry/                          表结构权威：6 个模块、82 张表
database/generator/                         校验器与确定性 DDL 生成器
database/generated/                         生成产物（勿手改）
database/tests/                             容器冒烟、迁移闭环、覆盖校验
backend/                                    Alembic 基线 + 应用骨架
corpus/                                     平台语料（2012–2026 高考真题、模拟卷、教材 PDF）与 corpus/eval 检索评测/基线
requirements-ai.txt                         混合检索原型（Qwen3 CPU）额外依赖
tools/check_all.py                          17 项检查的唯一入口
tools/kb_mock_*.py                          模拟题题干修复流水线（校验/探针/修复/重投影）
tools/project_restricted_corpus.py          受限资料投影（PG → Obsidian 内部审校区）
```

## 核心原则

**Registry 是表结构的唯一权威。** 手写只发生在 `database/registry/`；SQL、迁移、测试期望值全部由它派生。契约变更后重新生成，CI 会拦截不一致。

**能机械校验的就不靠人记。** 13 个业务聚合必须落到真实存在的表（`check_aggregate_coverage.py`）；136 条状态迁移必须各有测试用例（`check_test_plan.py`）；DDL 必须与 Registry 逐字节一致（`generate_ddl.py --check`）。

## 本地环境

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.12+ | 所有检查与生成器只用标准库 |
| Docker | 任意近期版本 | 容器冒烟与迁移测试需要 |
| PowerShell | **7.x 推荐** | CI 使用 PowerShell 7；Windows 内置的 5.1 行为不同，是本地/CI 差异的常见来源 |

Windows 上安装 PowerShell 7（免管理员，便携版）：

```powershell
winget install --id Microsoft.PowerShell -e
# 或下载 PowerShell-<版本>-win-x64.zip 解压到 %LOCALAPPDATA%\Microsoft\PowerShell\7 并加入 PATH
```

## 常用命令

```bash
# 全部检查（CI 的 check job 就是这一条）
python tools/check_all.py

# 改完 Registry 之后
python database/generator/validate_registry.py --selftest
python database/generator/generate_ddl.py
python database/generator/generate_ddl.py --check     # 漂移检测

# 新增迁移
python database/generator/gen_migration.py --id 0002_xxx --slug "something" --down 0001_baseline
```

```powershell
# 真实 PostgreSQL 17 上验证 DDL
pwsh -NoProfile -File database/tests/run_container_test.ps1

# 迁移 upgrade → 验证 → downgrade → 验证回滚
pwsh -NoProfile -File database/tests/run_migration_test.ps1

# 行级安全：一个教师读不到、改不了、也伪造不了另一个教师的数据
pwsh -NoProfile -File database/tests/run_rls_test.ps1

# Outbox：原子写入、至少一次投递、死信、消费者幂等
pwsh -NoProfile -File database/tests/run_outbox_test.ps1

# 身份：密码不落明文、会话只存 hash、撤销与停用生效
pwsh -NoProfile -File database/tests/run_identity_test.ps1

# 任务生命周期：契约里每条迁移都能走通，每个非法组合都被拒绝
pwsh -NoProfile -File database/tests/run_task_test.ps1
# 方案审批：单次消费、内容 Hash 绑定、过期失效
pwsh -NoProfile -File database/tests/run_plan_test.ps1

# 执行：消费审批、契约迁移、围栏令牌拒绝过期 Worker
pwsh -NoProfile -File database/tests/run_exec_test.ps1

# 步骤 DAG：不可执行的计划在创建时被拒，按依赖调度
pwsh -NoProfile -File database/tests/run_step_test.ps1

# 工具调用：能力/审批闸门、幂等键、参数键序无关
pwsh -NoProfile -File database/tests/run_tool_test.ps1

# 运行映射与未知结果对账：超时不等于失败，对账从不重试
pwsh -NoProfile -File database/tests/run_run_test.ps1

# HTTP 层：冻结端点与错误码、真实 RLS（非超级用户角色）
pwsh -NoProfile -File database/tests/run_api_test.ps1

# Agent 回合：需求 → 校验过的方案（模板规划器；有 key 时跑 DeepSeek）
pwsh -NoProfile -File database/tests/run_agent_test.ps1

# 端到端：方案真的跑出题目、引用与检查报告
pwsh -NoProfile -File database/tests/run_executor_test.ps1

# 材料：一份 AST、两个投影；学生版序列化后不含任何答案
pwsh -NoProfile -File database/tests/run_material_test.ps1

# 发布与导出：审批单次消费、版本不可变、学生版 DOCX 解压后搜不到答案
pwsh -NoProfile -File database/tests/run_publish_export_test.ps1

所有测试套件均以非超级用户角色运行（见 backend/tests/support.py）；
平台知识的播种走管理员会话，租户数据走 owner 会话。

# 认证：注册 → 登录拿 token → 用它建任务 → 登出立即失效
pwsh -NoProfile -File database/tests/run_auth_test.ps1

# 教师界面：注册 → 一句话 → 批准执行 → 发布 → 下载两份 DOCX
pwsh -NoProfile -File database/tests/run_ui_test.ps1

# SSE：Last-Event-ID 回放、实时跟随、空闲心跳
pwsh -NoProfile -File database/tests/run_sse_test.ps1

# 密码重置：管理员端点 + 运维脚本，重置即吊销全部会话
pwsh -NoProfile -File database/tests/run_password_reset_test.ps1

# 忘记密码（运维）：
# $env:CHILON_DATABASE_URL='postgresql+psycopg://...'; python tools/reset_password.py --username teacher_demo

# PDF 导出与教师上传（上传在 RLS 下运行，非超级用户）
pwsh -NoProfile -File database/tests/run_pdf_upload_test.ps1

# 知识库摄入：上传即解析、题目与块通过 locator 关联、仅所有者可检索
pwsh -NoProfile -File database/tests/run_ingestion_test.ps1

# OCR：默认关闭；开启后扫描件可解析，低置信度进 pending_review 不可检索
pwsh -NoProfile -File database/tests/run_ocr_test.ps1

# 复核闭环：补录缺失题 → 转正 → 可检索
pwsh -NoProfile -File database/tests/run_review_closure_test.ps1
```

## 配置与模型

真实模型走 DeepSeek 的 OpenAI 兼容端点。密钥只放在本机的 `.env`（不进版本库）：

```powershell
Copy-Item .env.example .env
# 编辑 .env，填入 CHILON_DEEPSEEK_API_KEY=sk-...
python backend/tests/check_llm.py
```

`check_llm.py` 会打印掩码后的 key、base URL 与模型名，并做一次最小调用。
401 / 402 / 404 各有独立提示，避免把"密钥错""没余额""模型名错"混成一个错误。

时间变量（`.env` 里）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CHILON_DEEPSEEK_API_KEY` | 空 | 必填，形如 `sk-...` |
| `CHILON_DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 不要带 `/v1` |
| `CHILON_DEEPSEEK_MODEL` | `deepseek-chat` | 或 `deepseek-reasoner` |
| `CHILON_PLANNER` | `deepseek` | 设为 `template` 可离线跑测试 |

### Qwen / 阿里云百炼（检索 embedding + rerank）

2026-11-07 决策：**质量优先，embedding 与 rerank 都走 Qwen API**——`qwen3.7-text-embedding`（1024 维）+ `qwen3.7-text-rerank`；本地 Qwen3-Embedding/Reranker 只保留为离线回退。密钥只放在本机 `.env`（不进版本库）：

```powershell
# 编辑 .env，填入百炼控制台申请的 API-KEY
CHILON_QWEN_API_KEY=sk-...

# 填完后自测 embedding + rerank 是否都连通
.venv\Scripts\python.exe backend\tests\check_qwen.py
```

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CHILON_QWEN_API_KEY` | 空 | 必填；也兼容官方环境变量 `DASHSCOPE_API_KEY` |
| `CHILON_QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/api/v1` | DashScope 原生 API，**固定中国区（北京）**；控制台请在「华北2（北京）」创建 key |
| `CHILON_QWEN_REGION` | `cn-beijing` | 中国区（北京），不切国际区 |
| `CHILON_QWEN_TIMEOUT_SECONDS` | `30` | 单次请求超时 |
| `CHILON_QWEN_EMBEDDING_MODEL` | `qwen3.7-text-embedding` | 质量优先；降本备选 `qwen3.7-text-embedding-flash` |
| `CHILON_QWEN_EMBEDDING_DIM` | `1024` | 与现有 Qdrant 集合维度一致 |
| `CHILON_QWEN_RERANK_MODEL` | `qwen3.7-text-rerank` | API 重排，替代本地 Qwen3-Reranker-0.6B |
| `CHILON_QWEN_RERANK_TOP_N` | `40` | 送入 rerank 的候选数，与本地评测一致 |

当前 `.env.example` 已给出占位；检索/评测工具切换到 API 时读取这些变量。密钥不要提交到仓库，也不要写进文档。

## 设计与契约的状态

设计已完成并冻结：分册 D1（产品闭环与门禁）、D2（信息架构）、D3（页面规格）、D4（动作与错误码）、D5（接口与 SSE）、D6（验收与测试矩阵）、K09（知识库字段设计）。

契约以 JSON 形式版本化，均有对应校验器且带自测（注入缺陷必须被检出）。

## 已知欠账

- **真实教师验收仍未做**：D3 冻结时只有场景 A 一次线框图走查；**场景 B（编辑不重审 Plan）、C（G3 自动批准）、D（纸质资料/知识库价值）仍未真实验收**。验收方案（A–E 场景、4–6 位分层教师、通过门槛）与检索扩样本方案已设计、未执行：`docs/acceptance_and_retrieval_eval_design_2026-11-07.md`（D.117）。
- **知识库标注只到参考级，不得当验收**：6050 道高考真题的考点标注已全部处理（primary 6045，5 道判无归属）。第三轮“97%（修正后 99%）”是 AI 对 AI 标注的自洽复核，不是真人验收；第四轮真人抽检 100 题模块层一致 **94.0%（94/100，95% CI 87.5%–97.2%）**，只作参考级依据，用户告知填写人为高三资深教师（教龄/独立性未说明，未独立核实）。考点层尚未抽检，`annotation.status` 整体仍为 `needs_review`，不批量升级。
- **标注已进 PG，但仍是“双表示”迁移态**：6050 题导入 `knowledge_annotations` 8007 条 active（primary 6045）；`current_knowledge_points` 仍是旧工作台的中文模块名缓存（4748/6050 非空），不是新事实源。迁移完成前 hybrid 检索只读 `knowledge_annotations`；旧基线 Recall@8 26.7% 已复现，同步契约见 `docs/KB_SYNC_CONTRACT.md`（D.88）。
- **检索质量：混合原型 93.3%，但还不是产品效果**：15 条真人问题、混合检索（pg_trgm + Qdrant + RRF，无 rerank）Recall@8 **93.3%（14/15）**、MRR 0.836、空结果 0%；旧引擎 26.7% 仅作历史对照。样本只有 15 条、判定为 lenient 片段匹配、无 strict target；reranker 无 Recall 增益且 CPU 约 82.7s/query，未默认启用（2026-11-07 决策：评测/生产改用 `qwen3.7-text-rerank` API，本地 reranker 仅离线回退，待 v2 评测验证）。**93.3% 不是产品最终效果**，详见 `corpus/eval/HYBRID_BASELINE_2026-11-06.md`（D.89）；旧 55%/0.451/32% 不可比、不可引用。问题集仍缺 11–15、类别不全，待补采后重测；扩样本设计（初期 15→60 条、其中 30 条 strict；长期 ≥100 条 strict 覆盖定义/定理/公式/完整题目；发布门槛 Recall@8 ≥85% + Strict Recall@8 ≥70%，MRR@8/Strict@1/Strict-all@8 为诊断；双人核验、五组对照、Wilson CI）见 D.117。**2026-11-07 已切 Qwen API 并实测**：API 索引 12,973 points / 16.3 min / ¥1.17；15 条原始 Recall 14/15、MRR 0.702（API 重排 0.714）；**稀有词 rescue 后 15/15、MRR 0.780/0.723**（Q08 的“近五年 + 递推”过滤冲突已修，rescue 会绕过年份过滤，产品需提示“年份不符”）；本地基线 MRR 0.836/0.818，重排默认开关等 v2 strict 集，详见 `corpus/eval/QWEN_API_EVAL_2026-11-07.md`。v2.0 数据集已冻结：`corpus/eval/teacher_questions.v2.json`（60 条 / 20 strict：定义9/定理6/公式5，A/B 核验后 `strict_verified=true`）+ gold/manifest；仍少于模板的 30 strict（B01 焦点弦无独立教材公式块、题目类暂不纳入），建议二轮抽检 2 个修改项（详见 D.117）。**v2.0 首轮五组评测（修订 v2.0.3）**：HR 重排 Recall **60/60=100%**、strict 19/20=95.0%、strict MRR 0.887；H 混合 58/60=96.7%、strict 17/20=85.0%；v2.0.2 给 5 条“找一道…”类补 `question_type` 子句；v2.0.3 按二轮确认 B 把 Q-B-02 改为组合 gold（p73+p64），但三组仍 miss（检索召回问题，非 gold 语义），strict 不变；H/HR 均过第一阶段门槛，HR 本轮同时优于 H 但仅 60 条/单次/无 CI，默认开关待 CI 复核，详见 `corpus/eval/V2_EVAL_2026-11-07.md`。

- **QueryPlan P0 已验证（2026-11-07）**：QueryPlan v0 + 结构化硬过滤 + Filter Compliance Rate；同一 60 条上 HR **60/60=100%、strict 20/20=100%**，H/V 60/60、strict 19/20；V/H/HR 过滤遵守率 100%，T 70.9%（16 条硬过滤下 0 结果）。Q-B-02 切线公式、Q-B-09/E-09 解析几何找题被硬过滤修复；明确条件不再静默回退。下一步 content_type 分池、零结果分组 UI、run 元数据；详见 `docs/query_plan_p0_2026-11-07.md`（D.117）。

- **H/HR 默认模式决策（2026-11-07）**：采用“默认 H + HR 精确增强”，用 QueryPlan 路由：formula/knowledge/mixed 定义区别 → HR，其余 → H。60 条上 H 60/60 strict 19/20 MRR .573（约 2.9s）；HR 59/60 strict 20/20 MRR .904（约 37.5s）；**路由 60/60 strict 20/20 MRR .904，仅 24/60 走 HR（约 17s 估算）**。bootstrap CI：H strict [.828,1]、HR/路由 strict [1,1]，H 的 CI 与 HR 重叠，60 条样本不足以说统计确定。旧文档 H 96.7%/HR 88.3% 是 v2.0.0 数据；**未切生产默认**，待 holdout/API 灰度。详见 `docs/h_vs_hr_decision_2026-11-07.md`（D.117）。

- **中文文本 LLM 处理统一用 qwen-plus（2026-11-07）**：content_type 预标、QueryPlan 语义辅助、中文判定/摘要等需要模型处理汉字的任务统一 `qwen-plus`；配置 `CHILON_QWEN_CHAT_MODEL`（默认 qwen-plus）+ `CHILON_QWEN_CHAT_BASE_URL`（DashScope 兼容模式）。embedding/rerank 仍用 `qwen3.7-text-embedding` / `qwen3.7-text-rerank`；qwen-max/turbo 仅对照实验。工具：`tools/qwen_api.py` 的 `chat_model()` / `chat_base_url()`。

- **holdout120 + API 灰度（2026-11-07，phase 1）**：120 条未参与 v2 的教师问题；期望词已复核，strict 候选回填 6 条（strict_count=6）。lenient：H 106/120（MRR .848）、HR 101/120（.761）、路由 107/120（.827）；strict pilot：H 6/6（MRR .525）、HR 5/6（.833）、**路由 6/6（.742，Recall 最高）**。路由方向初步支持，但 strict n=6/CI 宽，**不能宣布样本外成立、不能开 `on`**；下一步扩 strict 到 20+，先 shadow。API 新增 `POST /retrieval/route` / `GET /retrieval/router`（flag off/shadow/on + percent），只做路由决策，不在请求链路检索。详见 `docs/holdout120_gray_2026-11-07.md`（D.117）。

- **content_type 标注 + 全量 LLM 预标（2026-11-07）**：1797 个教师已复核教材块按 `definition/theorem/formula/example/exercise/catalog/reading/other` 规则预标；教师复核 120 条 rule-v0 **84/120 = 70.0%**（低于 80% 门槛）。全量 qwen-plus 预标完成（1797/1797，92 requests，83.1 万+8.1 万 tokens，**¥0.827**，439s，0 失败）：rule==LLM 一致 **755/1797 = 42.0%**，该子集在 120 条复核中 **60/60 = 100%**；但 formula 仅 9 条高置信，**不启用 content_type 硬过滤、不冻结全量**，一致子集只做高精度软信号，1042 条分歧 `needs_review`。软路由试验（60 条 QP 基线）：正向 boost H strict 19→18，仅抑制 catalog/reading 与基线持平（H19/HR20），无收益，暂不启用。产物 `corpus/textbook/content_type_ensemble_summary_2026-11-07.json` / `content_type_ensemble_high_confidence_2026-11-07.json`；报告 `docs/content_type_llm_batch_2026-11-07.md`（D.117）。
- **受限资料已投影但没审完**：模拟题 67 套/931 题 + 教材 5 册/1797 块已从 PG 单向投影到 vault（`restricted`/`classroom`，仅内部审校，1005 个文件），但**答案/解析未入库**（题卡只指向同目录答案 PDF）、教材 OCR 待审且**无章节结构**、311 题 `question_type` 为空、legacy 中文模块名标“未核验”；高考卡 6324 张投影前后 0 改动。模拟题题干已本地修复 894/931；**39 题已全部有题干（33 阿里云试卷切题 OCR + 6 人工转录，每题来源可追溯）**（清单 `docs/mock_ocr_backlog_2026-11-06.md`；桌面临时文件夹已在校验 sha256 后删除，审计副本在 `var/`）；索引 12973 不变（mock 1002 / linked 931），15 条基线 93.3% 不变。工具 `tools/project_restricted_corpus.py`、`tools/kb_mock_*.py`、`tools/ocr_mock_backlog.py` 与 `tools/kb_manual_mock_import.py`，规则见 `docs/KB_SYNC_CONTRACT.md`（D.90–D.94）。
- **模拟题标注：931/931 全部有 primary，197 题经教师复核**：teacher **197**（93 随机抽样 + 104 高风险定向）/ model **734**；secondary **154**、空 primary **0**。一致率：93 题抽样 模块 81.7%/考点 54.8%；104 题定向 模块 45.2%/考点 13.5%（高风险子集，两组不可混用）。卡片 931/931 非空、931 卡 + 67 set note 与高考卡 sha256 未变；**734 条 model 标注仍未抽检，整体仍 `needs_review`**；未调 OCR、Qdrant 12973 与 15 条基线 93.3% 均不变（D.97）。
- **教材块标注阶段已冻结：teacher 1797/1797、引擎 v8、PG/vault 稳定**：`textbook_block_annotations` active **1797**，全部 teacher、reviewed；status mapped **1595** / non_content **191** / vocab_gap **11**；teacher 五批版本保留；`knowledge_annotations` 9092 未变。自动映射引擎冻结在 **v8**（in-sample exact 1561/1590 = 98.2%、module 1583/1590；**无 fresh holdout，不是泛化准确率**）；vault 5 册 **1606 行**（1595 kp 链接 + 11 待补），原文 0 差异、missing 0、可重建。冻结快照 `var/freeze/textbook_block_annotations_final_2026-11-07.json`（sha256 `39d19847…df804`），git tag `textbook-annotations-v8-frozen`；交接报告 [docs/textbook_annotation_handover_2026-11-07.md](docs/textbook_annotation_handover_2026-11-07.md)（含复现、校验、未决项、交接清单；D.104–D.116）。
- **答案解析仍有缺口**：修复错位后 4311/6050（71.3%）有答案，其余约三成是语料本身缺答案，不是解析漏读（D.84）。
- **草稿编辑还没有界面**：对话改、直接改目前只在服务端留有版本记录，界面上还不能改草稿。
- **`created_by` 一类字段暂无外键**：它们常由系统 Worker 写入，而 Worker 不是用户。需要先设计"系统主体"概念。
- **`0001_baseline` 仍是可重建基线**：一旦有环境部署过就必须冻结，之后只能新增 revision。

## 用 docker compose 跑起来

```bash
cp .env.example .env          # 填入 CHILON_DB_PASSWORD（本地开发可用默认值）
docker compose up -d --build
```

打开 http://127.0.0.1:8000/ 注册一个账号，然后写一句话、批准方案、下载教师版和学生版。

容器启动时会依次做三件事，**每次启动都做，不只是第一次**：

1. 等数据库可连接（用 psycopg 探测，不用 pg_isready——它不在这个镜像里）；
2. alembic upgrade head（已是当前版本时是无操作）；
3. 应用 database/seed/platform_tools.sql（ON CONFLICT DO NOTHING，幂等）。

任何一步失败，服务器都不会启动——不会留下一个半死不活的进程。

> **数据库密码只在数据卷第一次初始化时生效。** 之后改 CHILON_DB_PASSWORD 不会
> 修改已有库的密码，应用会一直报 password authentication failed。要么使用同一个
> 值，要么 docker compose down -v 重建（**会删除数据**）。

/healthz 只回报进程存活，**不查数据库**：依赖故障不应该让进程看起来也死了，否则编排器会去重启一个本身正常的服务。

导出与上传文件存放在 chilon-data 卷的 /data 下（CHILON_EXPORT_DIR / CHILON_UPLOAD_DIR），**重新部署不会删掉教师已经下载过的文件**。

### 云 OCR（阿里云试卷切题）

默认关闭。开启需要显式提供凭据：

```bash
CHILON_OCR_PROVIDER=aliyun
CHILON_OCR_ALIYUN_KEY_ID=...
CHILON_OCR_ALIYUN_KEY_SECRET=...
CHILON_OCR_ALIYUN_IMAGE_TYPE=scan     # scan | photo
CHILON_OCR_ALIYUN_SUBJECT=Math
```

**开启即视为一次数据出境决策**：整页图片会上传到阿里云。开通服务与计费见
[教育场景识别](https://help.aliyun.com/zh/ocr/product-overview/education-scenario-recognition-1)。
该接口不支持 PDF，服务会先把每页栅格化为 PNG 再上传。

#### 拿到凭据后的第一步：联调探测

```bash
export CHILON_OCR_ALIYUN_KEY_ID=...
export CHILON_OCR_ALIYUN_KEY_SECRET=...
python tools/aliyun_ocr_smoke.py 试卷.pdf --page 1 --dump /tmp/aliyun.json
```

它会真实调用一次 `RecognizeEduPaperCut`，打印返回结构与解析出的题目。
**如果解析器认不出结构，它会带上实际键名报错**——照着输出调整
`app/services/aliyun_ocr.py` 里的 `TEXT_KEYS` / `OPTION_KEYS` 即可，通常只改键名。
它不写数据库：先确认 vendor，再跑上传路径。

当前只接入了**试卷切题**（RecognizeEduPaperCut）。整页识别与精细版结构化评估后暂缓：前者与我们自己的切分重复，后者多给的标签多数可由关键词法推出。
