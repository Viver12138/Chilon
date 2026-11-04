# Chilon 产品设计分册 D1：产品闭环协议

> **文档类型**：设计分册（Design Volume）
> **分册编号**：D1
> **整理日期**：2026-11-04
> **状态**：D1-01 ~ D1-10 **FROZEN FOR IMPLEMENTATION**；D1-11 初始目标（待基线校准）；D1-12 **DESIGNED**
> **上游基线**：`Chilon_Project_Design_Master_Document.md`（以下简称“主文档”）
> **用途**：补齐主文档 §28.8 的四条未完成设计项与“编辑—审批”边界，作为 D2–D6 各分册的输入。

[//]: # (toc:start)
## 目录

- [0. 本册定位](#0-本册定位)
- [1. 黄金路径的闭环骨架](#1-黄金路径的闭环骨架)
- [2. 冻结决策](#2-冻结决策)
- [3. 变更分级与审批边界](#3-变更分级与审批边界)
- [4. Draft 生命周期细则](#4-draft-生命周期细则)
- [5. 题源治理](#5-题源治理)
- [6. 黄金路径量化验收指标](#6-黄金路径量化验收指标)
- [7. 端到端固定样例规格](#7-端到端固定样例规格)
- [8. 本轮对主文档与 Schema 的修订](#8-本轮对主文档与-schema-的修订)
- [9. 交付给后续分册的输入](#9-交付给后续分册的输入)
- [附录 A：决策速查](#附录-a决策速查)
- [附录 B：本册引入的错误码（草案，供 D4/D5 对齐）](#附录-b本册引入的错误码草案供-d4d5-对齐)

[//]: # (toc:end)

---

## 0. 本册定位

### 0.1 本册解决什么

主文档 §28.8 列出四条“影响领域模型、API、前端和 Agent，必须先于大规模 DDL 与页面实现完成”的缺口。本册全部回答：

| 主文档缺口 | 本册回答 |
| --- | --- |
| 哪些操作必须重新审批 Plan，哪些局部修改只需重新执行质量检查 | §3（三级变更模型 + 机械判定表） |
| Draft 的自动保存、提交审核、撤回、放弃和恢复语义 | §4（Revision 分类 + 动作表） |
| 基准教学场景的可度量验收指标 | §6（18 项指标 + 门禁级别） |
| 端到端测试样例和固定评估数据集 | §7（fixture 规格与断言） |

同时冻结主文档未决的产品决策（§2），并登记本轮对主文档与 Schema 的修订（§8）。

### 0.2 本册不做什么

- 不定义 API 资源形状、Endpoint 命名与响应结构（D5）。
- 不定义页面布局、组件与视觉（D3）。
- 不定义数据库字段类型、约束与索引（Phase 1 Registry）。
- 不定义错误码的完整集合，只前向声明本册引入的 6 个（附录 B），供 D4/D5 对齐。

### 0.3 冲突处理约定

本册与主文档冲突时，以本册为准，并必须回写主文档对应章节（§8 给出本轮回写清单）。本册不改写主文档已有状态机定义；新增的状态迁移以“修订记录”形式标注。

------------------------------------------------------------------------

## 1. 黄金路径的闭环骨架

### 1.1 三个主体

| 主体 | 角色 | 权限边界 |
| --- | --- | --- |
| 教师 | 唯一人类操作者，唯一授权主体 | 批准计划、批准发布、确认来源权利、直接编辑 |
| Agent | 执行者 | 只能在已批准范围内检索、生成、修改；不得扩范围、不得伪造来源 |
| Chilon Control Plane | 判定者 | 门禁计算、状态迁移、幂等与审计；不做内容创作 |

### 1.2 七个门禁

门禁是“不通过与不推进”的强制检查点。每个门禁都有明确的持有主体与失败后果，实现时不得合并或跳过。

| 门禁 | 位置 | 判据 | 失败后果 | 归属 |
| --- | --- | --- | --- | --- |
| **G1 需求完整性** | Requirement 提交 | 年级、专题、内容类型、题量、题源构成齐全；课时/篇幅、难度、资料范围可省略（有默认值）；仅缺硬性项时进入澄清 | Task 停留 `draft` | K011 |
| **G2 计划可执行性** | Plan 提交 | 结构、DAG 无环、Capability 齐全、来源快照满足 `source_requirements` | Task → `needs_attention`，返回 `capability_gap` | K011 |
| **G3 计划授权** | 教师批准 | Approval 绑定 `plan_version_id` + `plan_hash` | 不创建 Execution | K011 |
| **G4 内容合法性** | Draft 每次保存与发布 | 主文档 §20.9 全部语义规则 + Citation 完整性 | 保存拒绝（`422`）或发布拒绝 | K012 |
| **G5 质量与数学门禁** | 提交审核前 | Gate 结论 ∈ {`passed`,`passed_with_warnings`}，且证据新鲜 | Draft → `changes_required` | K014 |
| **G6 发布授权** | 发布事务内 | Publication Approval 有效且未被消费，目标 Hash 一致 | 拒绝，Draft 保持 `approved` | K012 |
| **G7 导出范围** | 导出时 | Profile 投影 + `rights.status` + `distribution_scope` | 拒绝导出 | K012 |

### 1.3 闭环不变量

以下八条是 D2–D6 均不得破坏的性质。任何页面、接口或 Agent 行为如果违反其中一条，视为设计错误而不是取舍问题。

| 编号 | 不变量 | 强制点 |
| --- | --- | --- |
| I1 | 无来源不成原题：`workbook_example` / `gaokao_question` / `mock_question` / `textbook_example` 必须绑定可定位 Citation | G2、G4、G5 |
| I2 | 无新鲜证据不发布：检查结论必须绑定 Draft 当前 Revision 与 Content Hash | G5、G6 |
| I3 | 无授权不扩范围：Agent 不得自行扩大检索范围或新增题源 | G2、G3 |
| I4 | 学生版不泄漏：答案、解析、教师备注在 AST 层移除，而非样式隐藏 | G7 |
| I5 | 历史不改写：已发布 Material Version、已消费 Approval、已产生 Evidence 永不原地修改 | G6 |
| I6 | 超时不重试副作用：`outcome_unknown` 必须先对账 | 全部异步动作 |
| I7 | 状态只认 PostgreSQL：Celery/Redis/SSE 状态不作为业务事实 | 全部状态迁移 |
| I8 | AI 内容不得伪装来源：`ai_generated` 不得携带教材/教辅/高考/模拟来源标识 | G4、G5 |

------------------------------------------------------------------------

## 2. 冻结决策

### D1-01 无资料时不凭记忆生成原题

**决策**：教师没有可定位的已审核电子资料时，Agent 不得输出教辅例题、高考原题或模拟题。原题类内容一律标为 `unsupported`，讲义正文与 AI 自编题照常生成。

**降级阶梯**（自上而下，前一级不可用才进入下一级）：

| 级 | 条件 | 结果 |
| --- | --- | --- |
| L0 | 存在 `approved + indexed + not withdrawn` 且有 Citation 的资料 | 正常引用，`verbatim` / `excerpt` |
| L1 | 资料存在但 `rights.status = unverified` | 可生成与检查，发布与导出被 G6/G7 阻止 |
| L2 | 教师口述或自编资料 | 教师上传为 `teacher_authored` 后按 L0 处理 |
| L3 | 无任何可用资料 | 不出原题；AI 自编题显式标记；任务在 G2 返回 `capability_gap`，由教师三选一：补资料 / 降级接受 / 改要求 |

**为什么**：主文档 §1.6 与 §6.5#5 已要求“不得仅凭模型记忆复现”，但未规定无法满足时的行为。缺这一步，实现者会退化为“尽力生成”，直接破坏 I1。

**约束下游**：Plan 必须显式声明预计来源；G2 在生成前就判定能否满足，不允许“先生成再发现”。

**否决方案**：允许低置信度生成并打“仅供参考”标签。否决理由：标签无法阻止内容流入学生版，且违反 §1.6 对来源可辨识性的要求。

### D1-02 一个 Task 对应一个 Draft

**决策**：MVP 中一次 Task 的执行交付物恰好是一个 `document_kind = mixed` 的 Draft。需要多个 Material 时创建多个 Task，用 `parent_task_id` 保留派生关系。

**为什么**：主文档 §16.3 已确定 Material 只有一个主归属，§20.7 又允许 `mixed` 在同文档内包含讲义区与练习区。一对多会让 Task 的 `completed` 判据、Draft 的发布门禁和 `task_material_links` 三方纠缠。

**否决方案**：一 Task 多 Draft 并行交付。否决理由：Task 完成判据需要聚合多个 Draft 的检查状态，MVP 收益不足。

### D1-03 编辑与审批分权：教师编辑不重审 Plan

**决策**：教师对 Draft 的一切直接编辑和 Chat 局部修改**不需要重新审批 Plan**。Plan 审批只在“要求 Agent 重新执行且检索范围或交付物范围发生变化”时发生。

**为什么**：这是本册对主文档 §28.8 的核心回答。主文档 §7.2 明确 Plan Approval 保护的是“Agent 是否可以访问某位教师的私有资料”“当前任务是否允许生成新题”——被约束对象是 **Agent**，不是教师。教师本人就是自己的授权主体，要求教师为自己的人工编辑再走一次计划审批，是把 Agent 的安全机制错误地施加给了人类。

主文档 §6.5#8 的原文是“影响教案范围、题目来源或题量结构的变化，应按业务规则**重新进入计划确认或质量检查**”——本册选择“质量检查”这一支，并保留“计划确认”用于 Agent 侧的范围扩展。

**约束下游**：
- 安全性不再由“编辑时拦截”保证，而由 **G4 + G5 + G6 + G7 集中保证**。这是刻意的：门禁只有一处，才可审计、可测试。
- Agent 自主提议扩大范围时必须重新规划；教师明确指令不触发重新规划，但触发 §3 的分级判定。

**否决方案**：按编辑量或节点比例触发重新规划。否决理由：阈值无法解释给教师，且教师无法预判自己是否“改超了”。

### D1-04 Chat 修改默认是提议，且分三档分流

**决策**：

1. Chat 请求发出时记录 `base_revision_no`。Agent 产出修改提案后，服务端复核 Draft 指针。
2. 指针未变 → 在同一事务内应用、创建新 Revision、`change_origin = chat_revision`。
3. 指针已变 → 不自动应用，返回可见差异的 Patch/Proposal，由教师选择应用、重新生成或手动合并。
4. Chat 请求若要求新的检索或新的交付物结构（`E2`，见 §3），不进入当前 Draft 的修改流程，而是提示“此改动需要重新规划”并提供新建 Task 入口。

**为什么**：主文档 §21.7.3 已冻结 1–3 条，本册补第 4 条。缺第 4 条时，Chat 会成为绕过 G2/G3 的通道——教师一句“再加三道高考真题”，Agent 就会扩检索，这与 I3 冲突。

### D1-05 AI 自编题的来源与难度约束

**决策**：

| 约束 | 规则 |
| --- | --- |
| 来源标识 | `provenance.kind = ai_generated`、`basis = synthesis`、`citation_ids` 为空 |
| 禁止伪装 | 不得出现在标题或 `attribution_text` 含“真题/原题/教材”的题组中 |
| 难度 | 默认上限 `medium`；`advanced`/`challenge` 需 Requirement 显式 `allow_high_difficulty = true` |
| 计数 | 不得计入任何原题类的 `source_requirements` 数量（见 §5） |

**为什么**：`ai_generated` 是唯一无法被 Citation 校验兜底的来源类型，若不额外约束，它会成为“来源伪造”的默认通道。

### D1-06 公式编辑固化为 LaTeX 源码 + 实时预览

**决策**：MVP 的公式编辑只接受 LaTeX 源码输入 + 实时预览，不接受所见即所得面板。保存前必须通过 Renderer 命令白名单校验；`alt_text` 必填。

**为什么**：主文档 §20.9#13 已冻结白名单与复杂度限制。可视化面板会引入“面板生成不合法 LaTeX”的额外失败面，MVP 不值得。

**约束下游**：D3 的编辑器规格只提供“源码输入 + 预览 + 校验提示”三态，不设计公式工具栏。

### D1-07 导出 Profile 固定两种，不提供开关

**决策**：导出只有 `teacher` 与 `student` 两种 Profile。学生版**恒定**剔除答案、解析、教师备注与内部验证证据，不提供“是否导出教师备注”开关。

**为什么**：主文档 §20.10 已定义三投影（internal 不导出）。增加开关会让 Profile 配置产生组合爆炸，并使 G7 的“导出范围”判定出现未枚举分支。

### D1-08 变更分级：E0 / E1 / E2

**决策**：所有对 Draft 的变更按影响面分为三级，级别决定“是否需要重检”“是否需要额外确认”“能否靠编辑完成”。机械判定规则见 §3.2。

### D1-09 Draft 生命周期与 Revision 分类

**决策**：Draft Revision 分为 `checkpoint` 与 `autosave` 两类；只有 checkpoint 进入版本历史主视图；自动保存不改变 Draft 状态。完整语义见 §4。

### D1-10 题源治理结构

**决策**：Requirement Version 声明 `source_requirements`，Plan 必须回述覆盖矩阵，G2 与 G5 两处校验。守卫规则见 §5。

### D1-11 黄金路径量化验收指标

**决策**：采用 6 类共 18 项指标，其中 9 项为阻断级。指标表见 §6，标注为**初始目标**，需在 Phase 6 用真实基线校准。

### D1-12 端到端固定样例

**决策**：黄金路径的可复现样例以“输入 fixture + 断言集”形式固定，不依赖人工目测。规格见 §7。

------------------------------------------------------------------------

## 3. 变更分级与审批边界

### 3.1 三级定义

| 级别 | 名称 | 判定含义 | 能否靠编辑完成 | 发布前额外要求 |
| --- | --- | --- | --- | --- |
| **E0** | 内容编辑 | 不改变引用集合，不改变交付物类型 | 是 | G4 + G5 重检 |
| **E1** | 来源变更 | 改变了 AST 中引用的来源集合或来源类型 | 是 | G4 + G5 重检 + G6/G7 的来源权利校验 |
| **E2** | 范围扩展 | 无法靠编辑完成，需要 Agent 重新检索或重建结构 | 否 | 必须新建 Task + G2 + G3 |

**关键结论**：E1 **不引入新的审批实体**。新增来源天然被两道既有门禁拦住——K009 的教师审核与 `rights.status` 确认（§21.1.4），以及发布审批对 `citation_snapshot_hash` 的绑定（§21.9.1）。本册因此不新增任何数据表。

### 3.2 机械判定表

判定输入是结构化节点操作列表（稳定 Node ID + 局部操作），按“取最高级别”合并。

| # | 变更对象 | 具体字段 / 操作 | 级别 |
| --- | --- | --- | --- |
| 1 | 纯文本 | `paragraph`、`list`、`table` 文案，`heading`、`section.title` | E0 |
| 2 | 节点顺序 | 同一 `section` 内子节点重排 | E0 |
| 3 | 公式 | `formula.latex`、`formula.alt_text` | E0 |
| 4 | 定义与定理 | `definition.statement/conditions`、`theorem.assumptions/conclusion/proof` | E0 |
| 5 | 答案与解析 | `answer`、`solution`、`solution_step`、`hint` 的 `content` | E0 |
| 6 | 选项 | `exercise.options` 的 `content`、`label`、顺序 | E0 |
| 7 | 难度与能力维度 | `exercise.difficulty`、`ability_dimensions`、`exercise_group.difficulty` | E0 |
| 8 | 题量 | `exercise` / `exercise_group` 增删 | E0（越出 Requirement 区间产生 S2 警告，不阻断） |
| 9 | 章节骨架 | `section` 增删、`section.purpose`、章节顺序 | E0 |
| 10 | 可见性 | 节点 `visibility` 在合法组合内调整 | E0（违反 §20.9#5 则保存即拒绝） |
| 11 | 引用关系 | `provenance.kind/basis/change_note` 修改 | E1 |
| 12 | 引用集合 | `provenance.citation_ids` 增删 | E1 |
| 13 | 引用快照 | `citations[]` 增、删、改 | E1 |
| 14 | 来源补充 | Chat 要求“补充某份资料”且该资料已在知识库 | E1 |
| 15 | 新检索 | 要求检索知识库中尚未参与的资料来源 | E2 |
| 16 | 交付物变化 | 换专题、换课时、改为另一种 `document_kind` | E2 |
| 17 | 整体重做 | “重新生成整份讲义” | E2 |
| 18 | 恢复与导入 | `restore` 历史 Revision、`import` 外部文档 | 按内容重算：仅当结果引用集合变化时升为 E1，否则 E0 |

**合并规则**：一次保存或一次 Chat 应用若包含多类操作，取最高级别。级别只影响门禁要求，不拦截保存：**E1/E2 的编辑同样先保存成功**，由 G6 在发布时集中判定，避免编辑中断。

### 3.3 E2 的判定必须前置于执行

E2 不得在 Agent 已经扩检索之后才被发现。判定点是 Chat 请求解析后、Planner 启动前：

1. 解析请求意图，与当前 Plan 的“预计使用資料”和 Requirement 的 `source_requirements` 比对。
2. 命中 E2 → 不启动执行，返回提示并给出“新建 Task（继承当前 Draft 为参考）”入口。
3. 未命中 → 进入当前 Draft 的 Revision 流程。

### 3.4 教师可见的级别提示

| 级别 | 提示时机 | 提示内容要求 |
| --- | --- | --- |
| E0 | 不提示 | 保存成功即可，不增加确认步骤 |
| E1 | 保存后首次检出时 | “新增 N 处引用来自 M 份资料；发布前需确认这些资料的使用范围。”不阻断编辑 |
| E2 | Chat 请求解析后 | “该改动需要重新检索资料，无法在当前草稿中完成。”提供新建 Task 入口 |

**不变量**：任何确认步骤都不得以“是否放弃编辑”为代价；教师永远可以先改、后处理门禁。

### 3.5 与主文档状态机的对应

本册不新增 Draft 状态。E1 的来源权利问题由 G6/G7 在发布与导出时判定，对应主文档 §21.9.2 第 7–8 步与 §21.1.4 权利矩阵。E2 对应主文档 §21.5.1 的 `needs_attention → planning`。

------------------------------------------------------------------------

## 4. Draft 生命周期细则

### 4.1 Revision 的两类

| 类别 | 产生方式 | 是否进入版本历史主视图 | 是否可作为发布基线 |
| --- | --- | --- | --- |
| `checkpoint` | 手动保存、提交检查、审批、发布、恢复、rebase 完成、Chat 提案应用、放弃前自动快照 | 是 | 是 |
| `autosave` | 自动保存 | 否（仅在“恢复点”列表可见） | 否，除非已被引用后转为 `checkpoint` |

两类都是不可变 Revision，都参与 `content_hash`，都受“不得静默改变已存在 Revision Hash”约束（§21.7.2）。

### 4.2 自动保存规则

| 项 | 规则 |
| --- | --- |
| 触发条件 | 内容 Hash 发生变化 **且** 距上次写入 ≥ 2 秒（防抖） |
| 阻塞性 | 不阻塞教师输入；失败时前端重试，不弹窗 |
| 并发 | 必须携带 `If-Match`；不匹配返回 `409 REVISION_CONFLICT`，不覆盖 |
| 冲突重放 | 纯文本类操作可由前端基于新指针重放；结构性操作必须由教师处理，不得自动合并 |
| 状态影响 | **不改变** Draft 状态（不触发 `editing → checking`） |
| 检查影响 | 使既有检查与审批变为 `stale`（沿用主文档 §21.7.1 规则） |

### 4.3 显式动作表

| 动作 | 前置状态 | 目标状态 | 守卫 | 幂等依据 |
| --- | --- | --- | --- | --- |
| `save-revision` | `editing`/`checking`/`changes_required`/`awaiting_review`/`approved` | `editing` | `If-Match` 匹配；G4 通过 | `content_hash` |
| `submit-check` | `editing`/`changes_required`/`needs_attention` | `checking` | 当前 Revision 已过 G4 | `revision_no` |
| `cancel-check` | `checking` | `editing` | 关联 Run 已取消或从未启动 | `run_id` |
| `request-changes` | `awaiting_review` | `changes_required` | 无（教师自我打回） | `revision_no` |
| `approve` | `awaiting_review` | `approved` | G5 新鲜且结论允许；E1 引用权利已确认 | `gate_snapshot_hash` |
| `withdraw-approval` | `approved` | `awaiting_review`（仍新鲜）或 `editing`（已失效） | 无 | `state_version` |
| `publish` | `approved` | `published` | 主文档 §21.9.2 全部 15 步 | `Idempotency-Key` |
| `abandon` | 任一非终止态 | `abandoned` | 无 | `state_version` |
| `restore` | `editing`/`changes_required`/`needs_rebase` | `editing` | 目标 Revision 属于同一 Draft | 目标 `revision_no` + `content_hash` |
| `rebase` | `needs_rebase` | `editing` | `base_version_id` 未再变化（CAS） | `base_version_id` + `state_version` |

**`cancel-check` 是新增迁移**，需回写主文档 §21.7.1 状态表（见 §8）。理由是：没有它，一个卡住的检查只能靠“随便改一个字”来逃逸，这既反常也不可审计。

### 4.4 为什么不设“撤回提交”

提交检查不产生对外承诺，只启动一次内部巡检。教师若想中止，用 `cancel-check`；若想改内容，直接编辑（新 Revision 使旧检查 `stale`）；若已进入 `awaiting_review` 但不想发布，用 `request-changes`。三个动作已覆盖全部意图，额外的“撤回提交”只是同义重复。

### 4.5 Revision 保留策略

| 类别 | MVP 保留 | 后续 |
| --- | --- | --- |
| `checkpoint` | 永久保留 | 不变 |
| `autosave` | 永久保留，仅打 `retention_class = autosave` 标记 | 压缩为快照 + Patch，DEFERRED |
| 被引用过的 `autosave` | 转为 `checkpoint`，永久保留 | 不变 |

**MVP 不做压缩的理由**：主文档允许压缩自动保存 Revision，但任何压缩都会让“已存在的 Revision Hash 不变”这条不变量变得难以证明。MVP 优先正确性，用分区与归档解决数据量问题。

### 4.6 多 Draft 并存与 `needs_rebase`

1. 同一 Material 允许并存多个 Draft（沿用主文档 §16.5）。
2. 发布时以 Material 当前版本做 CAS（§21.9.2 第 9 步）；落败方进入 `needs_rebase`。
3. `needs_rebase` 下教师只有三种处置：放弃自己的修改（`abandon`）、rebase 到新 Base（`rebase`）、另存为新 Draft。不提供自动三方合并。
4. `rebase` 产生的 Revision 是 `change_origin = rebase` 的新 Revision，必须重检。

### 4.7 发布后修正

`published` 是终止态。修正必须新建 Draft，`base_version_id` 指向刚发布的 Material Version，`change_origin = teacher_edit`。已发布版本永不原地修改（I5）。

------------------------------------------------------------------------

## 5. 题源治理

### 5.1 `source_requirements` 概念结构

该结构属于 Requirement Version 的内容，不是数据库表定义；字段归属待 K011 Registry 核对。

```json
{
  "source_requirements": [
    { "source_kind": "workbook_example", "min": 2, "max": 3 },
    { "source_kind": "gaokao_question", "min": 3, "max": 5, "year_min": 2021 },
    { "source_kind": "mock_question", "min": 2, "max": 4, "year_min": 2023 },
    { "source_kind": "ai_generated", "min": 0, "max": 10 }
  ]
}
```

- `source_kind` 取值与 `provenance.kind` 一致：`workbook_example`、`gaokao_question`、`mock_question`、`textbook_example`、`teacher_authored`、`licensed_material`、`ai_generated`。
- `textbook_example` 仍可用，但不属于默认模板；教材书默认只提供知识依据。
- `mock_question` 的 `year_min` 体现“近期”，默认近 3 年（含当年）；`gaokao_question` 默认近 5 年。
- **难度不是默认维度**（2026-11-04 变更）：Requirements 不再要求难度，Agent 不按难度筛选或加权。`difficulty_max` 与 `allow_high_difficulty` 从结构中移除；教师显式要求难度时才写入，此时按普通过滤条件处理，不再作为守卫。
- 未声明的 `source_kind` 视为不允许出现，除非教师在执行后显式编辑加入（此时按 E1 处理）。

### 5.2 守卫规则

| 编号 | 规则 | 强制点 |
| --- | --- | --- |
| R1 | 计数按 `provenance.kind` 归集，`ai_generated` 不得计入任何其他 kind 的计数 | G2、G5 |
| R2 | 声明 `min` 而可用来源不足 → Plan 阶段返回 `capability_gap`，不进入执行 | G2 |
| R3 | ~~`ai_generated` 难度默认 ≤ `medium`~~ **已废止（2026-11-04）**：难度不再是默认维度，Agent 不按难度生成或筛选 | — |
| R4 | `ai_generated` 不得出现在题组标题或署名含“真题/原题/教材/教辅/模拟”的容器中 | G4 |
| R5 | `workbook_example` / `gaokao_question` / `mock_question` / `textbook_example` 必须绑定对应 `source_type` 的 Citation | G4（§20.9#8–#9） |
| R6 | `rights.status` 未达 `teacher_confirmed` / `licensed` 时阻止发布与导出 | G6、G7（已有 §21.1.4） |
| R7 | 实际数量超出 `max` 产生 S2 质量问题，不阻断发布 | G5 |

**R4 的判定口径**：主文档的 `section.purpose` 枚举中没有“真题区”这一类，因此 R4 不依赖 `purpose`，而是对容器标题与 `attribution_text` 做词表检查（“真题”“原题”“教材例”“教辅”“模拟”）。词表由 K014 规则版本管理，可调整而不改 Schema。

### 5.3 降级确认

G2 返回 `capability_gap` 时，教师三选一，选择结果写入 Plan 或 Requirement 的例外记录：

| 选项 | 后果 |
| --- | --- |
| 补充资料 | 上传并审核后重新规划，不降级 |
| 降级接受 | `source_requirements` 按实际可用来源下调，记录下调原因与确认人 |
| 修改要求 | 新建 Requirement Version，回到 `planning` |

### 5.4 两道门禁的分工

| 门禁 | 管什么 | 不管什么 |
| --- | --- | --- |
| G2（计划期） | 来源**是否存在**、是否够数 | 是否已获得使用授权 |
| G6/G7（发布/导出期） | 来源**是否被允许使用**、权利范围是否够 | 数量是否够 |

两类判定不能合并：前者是可行性问题，后者是合规问题，失败原因不同的教师处置路径也完全不同。

------------------------------------------------------------------------

## 6. 黄金路径量化验收指标

### 6.1 指标表

门禁级别：**阻断** = MVP 不达标不得发布；**观察** = 记录并进入基线校准，不阻断。

| # | 类别 | 指标 | 定义 / 测量方法 | 初始目标 | 级别 |
| --- | --- | --- | --- | --- | --- |
| M1 | 可追溯 | 引用可追溯率 | 原题类节点中能在 `citations[]` 找到且来源状态合法的比例 | 100% | 阻断 |
| M2 | 可追溯 | 来源定位可回读率 | Citation 的 `char_start/char_end` 能从原文档回读到一致 Excerpt 的比例 | 100% | 阻断 |
| M3 | 可追溯 | AI 内容误标率 | `ai_generated` 被标成其他 kind 的节点比例 | 0 | 阻断 |
| M4 | 数学 | 可判定节点验证覆盖率 | 通过 Validator 处理的公式/答案节点占比 | ≥ 90% | 阻断 |
| M5 | 数学 | 假通过数 | Validator 判 `validated` 而人工复核为错的条数 | 0 | 阻断 |
| M6 | 数学 | 基准集通过率 | 固定数据集上 `validated` 占比 | ≥ 95% | 观察 |
| M7 | 效率 | 生成时长 | G3 批准到 Draft 首次 `awaiting_review` 的耗时 | P50 ≤ 4 min，P95 ≤ 8 min | 观察 |
| M8 | 效率 | 端到端时长 | 创建 Task 到两个导出文件 `ready` 的耗时 | P50 ≤ 15 min | 观察 |
| M9 | 效率 | 首轮 Plan 一次通过率 | 教师首次即批准、无修改请求的比例 | ≥ 70% | 观察 |
| M10 | 教师成本 | 教师编辑节点占比 | 教师创建的 Revision 中变更节点数 / 总节点数 | ≤ 20% | 观察 |
| M11 | 教师成本 | 发布前重检轮次 | 从首次 `submit-check` 到 `published` 的检查轮数 | ≤ 2 | 观察 |
| M12 | 教师成本 | S1 阻断密度 | 每次交付的 S1 问题数 | ≤ 1 | 观察 |
| M13 | 导出安全 | 学生版泄漏数 | 学生版投影中出现答案/解析/教师备注的节点数 | 0 | 阻断 |
| M14 | 导出安全 | 必需署名缺失数 | 要求 Attribution 的来源在学生版中缺失署名的条数 | 0 | 阻断 |
| M15 | 可靠性 | 发布重复版本数 | 相同幂等键产生的 Material Version 数 | 1 | 阻断 |
| M16 | 可靠性 | 未对账重试数 | `outcome_unknown` 未经对账即重试的副作用调用次数 | 0 | 阻断 |
| M17 | 可靠性 | SSE 事件丢失数 | 断线重连后按 Sequence 回放与 PostgreSQL 投影不一致的事件数 | 0 | 阻断 |
| M18 | 可靠性 | 状态并发冲突正确率 | 并发动作中只允许一个 CAS 成功、其余返回 `409` 的比例 | 100% | 阻断 |

### 6.2 基线校准

M7–M12 为初始值，Phase 6 需用真实运行数据重新标定，并把校准后的目标回写本册。M1–M5、M13–M18 不参与校准，它们是正确性下限。

### 6.3 指标与门禁的映射

M1–M3、M13–M14 由 G4/G5/G7 自动断言；M4–M6 由 K014 Validator 与评估集产生；M15–M18 由 §21.12.3 的故障注入测试产生。指标不是仪表盘装饰，每一条都要有对应的可执行断言。

------------------------------------------------------------------------

## 7. 端到端固定样例规格

### 7.1 目标

让“三角函数讲义 + 教辅例题 + 高考真题 + 近期模拟题”这条路径成为可重放、可断言、可回归的固定样例，而不是每次人工目测。

### 7.2 fixture 目录

```text
fixtures/golden_path/
  requirement.v1.json              # 输入：教学要求 + source_requirements
  sources/
    workbook_a.page52.json         # 已审核教辅资料（含 locator 可回读的原文）
    gaokao_2024_1.q7.json          # 已审核高考资料
    mock_2026_p1.q12.json          # 已审核近期模拟题
  expected/
    ast_assertions.yaml            # 结构与来源断言
    gate_assertions.yaml           # 门禁结论断言
    export_assertions.yaml         # 导出文件断言
  README.md
```

### 7.3 输入 fixture 要求

| 项 | 要求 |
| --- | --- |
| `requirement` | 年级、专题、课时、`document_kind=mixed`、`source_requirements` 四项（教辅例题 2、高考真题 3、模拟题 2、AI 自编 2） |
| 教辅资料 | 至少 2 道例题的原文可回读，`rights.status = teacher_confirmed`，`distribution_scope = classroom` |
| 高考资料 | 至少 3 道真题，含年份/地区/试卷/题号，可回读 |
| 模拟资料 | 至少 2 道近期模拟题（近 3 年），含年份/地区/考试名称/题号，可回读 |
| 教师账号 | 单一 Owner，无跨 Project 引用 |

### 7.4 AST 断言

| # | 断言 |
| --- | --- |
| A1 | `document_kind = mixed` |
| A2 | `section` 数量 ≥ 3，且至少各有一个 `purpose` 为 `worked_examples` 与 `exercises` |
| A3 | `provenance.kind = workbook_example` 的 `worked_example` ≥ 2，每个 ≥ 1 个 `workbook` Citation |
| A4 | `provenance.kind = gaokao_question` 的 `exercise` ≥ 3，每个 ≥ 1 个 `gaokao_paper` Citation |
| A5 | `provenance.kind = ai_generated` 的题目 ≥ 2，且 `difficulty ∈ {basic, medium}` |
| A6 | 所有 `answer`/`solution`/`solution_step`/`hint` 的 `visibility ≠ student` |
| A7 | 所有选题题的 `options` ≥ 2，`answer_node_ids` 指向后代 `answer` |
| A8 | 节点 ID 全局唯一；`list_item` 仅在 `list.items` 内 |
| A9 | `provenance.kind = mock_question` 的 `exercise` ≥ 1，每个 ≥ 1 个 `mock_exam` Citation |

### 7.5 Citation 断言

| # | 断言 |
| --- | --- |
| C1 | 每个 `citation_id` 唯一，且至少被一个节点使用 |
| C2 | `usage.rights.status ∈ {teacher_confirmed, licensed}`，`distribution_scope ∈ {classroom, private_teacher}` |
| C3 | `integrity.excerpt_hash = sha256(excerpt.text)`，`char_end > char_start` |
| C4 | `locator.page_number` 与 `locator_kind` 匹配 |
| C5 | `retrieval.retrieval_run_id` 指向一次真实检索，且 `rank ≥ 1` |

### 7.6 门禁断言

| # | 断言 |
| --- | --- |
| E1 | `quality_check_runs.gate_result ∈ {passed, passed_with_warnings}` |
| E2 | `math_validation_runs.validation_result = validated` |
| E3 | 检查目标 Revision 与发布 Revision 一致；无 `stale` 证据 |
| E4 | 任一 S0 问题存在时发布被拒绝 |
| E5 | 相同幂等键二次发布返回同一 Material Version |

### 7.7 导出断言

| # | 断言 |
| --- | --- |
| X1 | 教师版包含全部 `student` 与 `teacher` 节点，不含 `internal` |
| X2 | 学生版节点集中 `answer`/`solution`/`solution_step`/`hint` 数量 = 0 |
| X3 | 学生版保留必需的 Attribution 文本 |
| X4 | 两个文件均生成，文件 Hash 稳定可复现 |
| X5 | 导出记录的 `source_document_hash` 与 Material Version 一致 |

### 7.8 状态序列断言

正常路径必须与主文档 §21.11.1 完全一致：

```text
Task:      draft -> planning -> awaiting_plan_approval -> ready -> running -> completed
Plan:      draft -> awaiting_approval -> approved
Execution: queued -> starting -> running -> succeeded
Draft:     editing -> checking -> awaiting_review -> approved -> published
Export:    queued -> rendering -> uploading -> ready
```

### 7.9 与现有样例的关系

`schemas/trigonometry_golden_path.v1.example.json` 是**结构样例**，用于验证 Schema 与 §20.9 语义规则，不是黄金路径 fixture：它只有 1 道题、1 个题组、2 条 Citation，不满足 §7.4 的数量断言。两者分工如下：

| 文件 | 用途 | 维护方 |
| --- | --- | --- |
| `schemas/trigonometry_golden_path.v1.example.json` | Schema 与语义规则的回归样例 | 本册 |
| `fixtures/golden_path/` | 端到端验收 fixture | D6 |

结构样例现在由 `design/check_golden_path.py` 做语义校验（覆盖 §20.9 中 JSON Schema 无法表达的规则），可独立运行。

------------------------------------------------------------------------

## 8. 本轮对主文档与 Schema 的修订

| # | 位置 | 修订 | 原因 |
| --- | --- | --- | --- |
| 1 | `schemas/trigonometry_golden_path.v1.example.json` | 选择题补齐 A/B/C/D 四个选项 | 违反 §20.9#4（选择题 ≥ 2 个选项） |
| 2 | 同上 | 拆为三个 `section`，`purpose` 分别为 `overview` / `worked_examples` / `exercises` | 单 section 承载全部内容，与新增的 §20.9#18 冲突 |
| 3 | 主文档 §20.9 | 新增规则 18：`section.purpose` 必须与直接子节点类型一致 | 防止“练习塞进 overview”这类语义漂移 |
| 4 | 主文档 §21.5.1 | 补充：Task `completed` 所绑定的检查证据只证明初轮交付，不构成发布门禁证据 | 原文易被误读为发布时可复用该证据 |
| 5 | 主文档 §21.7.1 | 新增迁移：`checking` + `cancel-check` → `editing` | 缺少中止手段 |
| 6 | 主文档 §0 | 新增 §0.3 分册索引 | 分册体系的入口 |
| 7 | 主文档 §28.8 | 四条缺口标记完成并指向本册 | 保持基线同步 |

------------------------------------------------------------------------

## 9. 交付给后续分册的输入

| 分册 | 从本册拿到的输入 |
| --- | --- |
| D2 信息架构 | 七个门禁的落点、E1/E2 提示位置、Draft 动作清单 → 导航须覆盖的门禁节点 |
| D3 页面规格 | 每个状态的教师可见动作集（§4.3）、公式编辑三态（D1-06）、E1/E2 提示文案要求（§3.4） |
| D4 状态文案 | 动作名、状态名、错误码骨架（附录 B）、级别提示语 |
| D5 API/SSE | `save-revision`/`submit-check`/`cancel-check`/`approve`/`publish` 等动作接口；`change_impact` 响应字段（返回本次变更的 E 级）；`409 REVISION_CONFLICT` 语义 |
| D6 验收测试 | §6 的 18 项指标、§7 的断言集、§3.2 的判定表（可表驱动） |

### 9.1 本册遗留的开放问题

| # | 问题 | 归属 |
| --- | --- | --- |
| O1 | E1 的“来源权利确认”在 UI 上是逐份确认还是一次性批量确认 | D3 |
| O2 | `change_impact` 由服务端计算后返回还是由客户端预判（服务端为准） | D5 |
| O3 | `source_requirements` 落在 Requirement 的 JSONB 还是独立子表 | Phase 1 Registry |
| O4 | 自动保存与 Chat 提案并发时的合并展示形态 | D3 |
| O5 | 检查规则词表（R4 的“真题/原题”词表）的维护流程 | K014 |

------------------------------------------------------------------------

## 附录 A：决策速查

| 编号 | 决策 | 一句话 |
| --- | --- | --- |
| D1-01 | 无资料不凭记忆生成 | 没资料就标 `unsupported`，不出原题 |
| D1-02 | 一 Task 一 Draft | 多材料就多 Task |
| D1-03 | 教师编辑不重审 Plan | Plan 只约束 Agent |
| D1-04 | Chat 修改默认提议制 | 指针变了就只给 Patch；E2 直接拦在规划前 |
| D1-05 | AI 自编题硬约束 | 无 citation、不伪装、难度默认 ≤ medium |
| D1-06 | 公式只走 LaTeX 源码 | 无 WYSIWYG |
| D1-07 | 导出只有两种 Profile | 学生版恒定剔除答案 |
| D1-08 | 变更分 E0/E1/E2 | 级别决定门禁，不拦截保存 |
| D1-09 | Revision 分 checkpoint/autosave | 自动保存不改状态 |
| D1-10 | 题源治理四规则 | 数量、难度、命名、权利各管一段 |
| D1-11 | 18 项验收指标 | 9 项阻断，9 项待校准 |
| D1-12 | fixture + 断言集 | 样例可重放，不靠目测 |

## 附录 B：本册引入的错误码（草案，供 D4/D5 对齐）

| 错误码 | HTTP | 触发条件 |
| --- | --- | --- |
| `REVISION_CONFLICT` | 409 | `If-Match` / `expected_revision_no` 不匹配 |
| `STATE_CONFLICT` | 409 | 动作与当前状态不匹配或 `state_version` 不匹配 |
| `STALE_GATE` | 409 | 检查证据或审批已失效 |
| `SOURCE_NOT_AUTHORIZED` | 409 | 引用的来源未通过审核或权利未确认 |
| `CAPABILITY_GAP` | 409 | `source_requirements` 无法满足，需教师决策 |
| `SCOPE_EXPANSION_REQUIRED` | 409 | 请求命中 E2，必须先重新规划 |
| `AST_INVALID` | 422 | Schema 或 §20.9 语义规则不通过 |

------------------------------------------------------------------------

**分册结束**

本册为 D2–D6 的输入基线。后续修订必须同时更新：本册对应条目、主文档回写清单（§8）与附录 A 速查表。
