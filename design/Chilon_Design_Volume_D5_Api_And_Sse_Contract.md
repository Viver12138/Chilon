# Chilon 产品设计分册 D5：API 与 SSE 契约

> **文档类型**：设计分册（Design Volume）
> **分册编号**：D5
> **整理日期**：2026-11-04
> **状态**：**FROZEN FOR IMPLEMENTATION**
> **上游基线**：分册 D4（动作与错误码）、`schemas/actions.v1.json`、`schemas/state_machines.v1.json`
> **用途**：确定接口形状、并发协议与实时事件契约，作为 D3（页面）、D6（契约测试）与后端实现的输入。

[//]: # (toc:start)
## 目录

- [0. 本册定位](#0-本册定位)
- [1. 通用约定](#1-通用约定)
- [2. 动作接口](#2-动作接口)
- [3. 资源接口](#3-资源接口)
- [4. 错误与状态码](#4-错误与状态码)
- [5. 并发控制](#5-并发控制)
- [6. SSE 契约](#6-sse-契约)
- [7. 上传与下载](#7-上传与下载)
- [8. 交付给 D3 与 D6](#8-交付给-d3-与-d6)
- [9. 第二批接口（明确押后）](#9-第二批接口明确押后)
- [附录 A：接口命名规则](#附录-a接口命名规则)
- [附录 B：本册与 D4 的映射](#附录-b本册与-d4-的映射)

[//]: # (toc:end)

---

## 0. 本册定位

### 0.1 本册解决什么

D4 确定了 23 个教师动作、23 组必须在单事务完成的复合命令、18 个错误码。本册把它们落成接口：

| 问题 | 本册回答 |
| --- | --- |
| 一个动作对应哪个接口？ | §2 动作接口（23 个，与动作一一对应） |
| 读数据怎么拿？ | §3 资源接口（40 个） |
| 并发冲突怎么表达？ | §5 ETag / state_version / Idempotency-Key |
| 实时进度怎么推？ | §6 SSE 契约（含断线回放） |
| 文件怎么传？ | §7 签名 URL |

### 0.2 本册不做什么

- 不定义数据库字段类型（Phase 1 Registry）。
- 不定义页面布局（D3）。
- 不定义 OpenAPI 文件的字段级 schema——留给实现阶段从本册与 Registry 生成。

### 0.3 机器可读副本

[schemas/api_surface.v1.json](../schemas/api_surface.v1.json)，由 `design/check_api_surface.py` 校验：每个教师动作恰好对应一个接口，路径参数与聚合匹配，错误码必须是 Registry 中已定义的。

------------------------------------------------------------------------

## 1. 通用约定

| 项 | 规定 |
| --- | --- |
| 版本 | 路径前缀 `/api/v1`；破坏性变更升 `/api/v2`，不原地改语义 |
| 认证 | 会话 Cookie 或 Bearer，二选一 |
| 资源归属 | 跨 Owner 访问一律返回 `404`，不返回 `403`（不泄露对象是否存在） |
| 幂等 | 所有 `POST` 接受 `Idempotency-Key`；相同键重放返回首次结果 `200`，不报错 |
| 乐观锁 | 草稿保存用 `If-Match: "<revision_no>-<content_hash_prefix>"` |
| 状态并发 | 动作接口必须带 `expected_state_version`，不匹配返回 `STATE_CONFLICT` |
| 分页 | 仅 cursor：`?limit=&cursor=`，响应带 `next_cursor`；不提供 offset |
| 错误 | 结构见 D4 §5.3，必须包含 `allowed_actions` |
| 时间 | 全部 RFC 3339 带时区，UTC |
| ID | UUIDv7 字符串 |

### 1.1 三个必须遵守的形状约束

1. **动作接口只做动作，不兼职读。** `POST /drafts/{id}/actions/approve` 不接受内容编辑；编辑走 `PUT /drafts/{id}/revision`。
2. **不存在 `PATCH {status}`。** 状态只能由 §2 的接口改变（SM-R01）。
3. **复合命令是一个接口，不是三个。** `approve-plan` 一次写 Task、Plan Version、Plan Approval 三个聚合。

------------------------------------------------------------------------

## 2. 动作接口

23 个，与 D4 的教师动作一一对应。全部 `POST`，全部要求 `Idempotency-Key` 与 `expected_state_version`。

| 方法 | 路径 | 动作 | 事务内影响 | 返回 | 失败错误码 |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/tasks/{task_id}/actions/submit-requirement` | `task.submit_requirement` | `submit_requirement` | `requirement_version_id` | `STATE_CONFLICT`、`REVISION_CONFLICT` |
| `POST` | `/tasks/{task_id}/actions/approve-plan` | `task.approve_plan` | `approve_plan` | `plan_approval_id`、`plan_version_id` | `STATE_CONFLICT`、`PLAN_NOT_APPROVED` |
| `POST` | `/tasks/{task_id}/actions/request-plan-revision` | `task.request_plan_revision` | `request_plan_revision` | 状态快照 | `STATE_CONFLICT` |
| `POST` | `/tasks/{task_id}/actions/cancel` | `task.cancel` | `cancel_task_immediate` | 状态快照 | `STATE_CONFLICT`、`TERMINAL_STATE` |
| `POST` | `/tasks/{task_id}/actions/replan` | `task.replan` | `replan_task` | `requirement_version_id` | `STATE_CONFLICT` |
| `POST` | `/tasks/{task_id}/actions/retry` | `task.retry` | `retry_task` | 状态快照 | `STATE_CONFLICT`、`PLAN_NOT_APPROVED` |
| `POST` | `/tasks/{task_id}/actions/request-cancel` | `task.request_cancel` | `cancel_task` | 状态快照 | `STATE_CONFLICT` |
| `POST` | `/requirement-versions/{requirement_version_id}/actions/abandon` | `requirement_version.abandon` | `abandon_requirement` | 状态快照 | `STATE_CONFLICT`、`TERMINAL_STATE` |
| `POST` | `/plan-versions/{plan_version_id}/actions/reject` | `plan_version.reject` | `reject_plan` | 状态快照 | `STATE_CONFLICT`、`TERMINAL_STATE` |
| `POST` | `/plan-approvals/{plan_approval_id}/actions/revoke` | `plan_approval.revoke` | `revoke_plan_approval` | 状态快照 | `STATE_CONFLICT`、`PLAN_NOT_APPROVED` |
| `POST` | `/executions/{execution_id}/actions/request-pause` | `execution.request_pause` | `pause_execution` | 状态快照 | `STATE_CONFLICT` |
| `POST` | `/executions/{execution_id}/actions/resume` | `execution.resume` | `resume_execution` | 状态快照 | `STATE_CONFLICT` |
| `POST` | `/drafts/{draft_id}/actions/submit-check` | `draft.submit_check` | `submit_check` | `quality_check_run_id`、`math_validation_run_id` | `STATE_CONFLICT`、`CHECK_IN_PROGRESS`、`AST_INVALID` |
| `POST` | `/drafts/{draft_id}/actions/cancel-check` | `draft.cancel_check` | `cancel_check` | 状态快照 | `STATE_CONFLICT` |
| `POST` | `/drafts/{draft_id}/actions/approve` | `draft.approve` | `approve_draft` | `publication_approval_id`、`gate_snapshot_hash` | `STATE_CONFLICT`、`STALE_GATE` |
| `POST` | `/drafts/{draft_id}/actions/request-changes` | `draft.request_changes` | `request_changes` | 状态快照 | `STATE_CONFLICT` |
| `POST` | `/drafts/{draft_id}/actions/withdraw-approval` | `draft.withdraw_approval` | `withdraw_draft_approval` | 状态快照 | `STATE_CONFLICT`、`STALE_GATE` |
| `POST` | `/drafts/{draft_id}/actions/publish` | `draft.publish` | `publish_material` | `material_version_id` | `STATE_CONFLICT`、`STALE_GATE`、`APPROVAL_CONSUMED`、`AST_INVALID`、`CITATION_INVALID`、`RIGHTS_BLOCKED`、`SOURCE_NOT_AUTHORIZED` |
| `POST` | `/drafts/{draft_id}/actions/abandon` | `draft.abandon` | `abandon_draft` | 状态快照 | `STATE_CONFLICT`、`TERMINAL_STATE` |
| `POST` | `/drafts/{draft_id}/actions/rebase` | `draft.rebase` | `rebase_draft` | `draft_revision_id` | `STATE_CONFLICT`、`REVISION_CONFLICT` |
| `POST` | `/drafts/{draft_id}/actions/retry-check` | `draft.retry_check` | `retry_check` | `quality_check_run_id` | `STATE_CONFLICT`、`CHECK_IN_PROGRESS` |
| `POST` | `/drafts/{draft_id}/actions/resolve-issue` | `draft.resolve_issue` | `resolve_issue` | 状态快照 | `STATE_CONFLICT` |
| `POST` | `/exports/{export_id}/actions/cancel` | `export.cancel` | `cancel_export` | 状态快照 | `STATE_CONFLICT`、`TERMINAL_STATE` |

### 2.1 统一响应结构

所有动作接口返回同一种信封，“状态快照”指其中的 `aggregate` 段：

```json
{
  "data": {
    "aggregate": "draft",
    "id": "0190...",
    "status": "approved",
    "state_version": 8,
    "state_changed_at": "2026-11-04T02:15:00Z",
    "status_reason_code": null,
    "allowed_actions": ["draft.publish", "draft.withdraw_approval", "draft.abandon"],
    "result": {
      "publication_approval_id": "0190...",
      "gate_snapshot_hash": "sha256:..."
    }
  },
  "events": [
    { "seq": 1023, "type": "draft.approved", "occurred_at": "2026-11-04T02:15:00Z" }
  ]
}
```

`allowed_actions` 是必需字段：前端不应该自己推导“当前状态能点什么”，而应直接渲染服务端给出的集合。这样 D3 的按钮显隐逻辑与 D4 的动作表天然一致，不会出现两处各写一份状态判断。

### 2.2 两个容易设计错的接口

**`approve-plan` 返回两个 ID。** 它同时创建 Plan Approval 并推进 Plan Version，两个新状态都需要回给前端刷新对应面板。

**`submit-check` 返回两条 Run 的 ID，而不是“检查结果”。** 检查是异步的：接口只负责把状态推进到 `checking` 并给出可轮询/可订阅的 Run 标识。结果通过 `GET /quality-runs/{run_id}` 或 SSE 获取。

------------------------------------------------------------------------

## 3. 资源接口

41 个接口：32 个黄金路径读写 + 8 个知识库题目级接口 + 1 个导出预览。`并发/分页` 列表示该接口的并发控制方式。

| 方法 | 路径 | 用途 | 并发/分页 |
| --- | --- | --- | --- |
| `GET` | `/me` | 当前账号与权限 | none |
| `GET` | `/projects` | 项目列表 | cursor |
| `POST` | `/projects` | 创建项目 | none |
| `GET` | `/projects/{project_id}` | 项目详情 | none |
| `PATCH` | `/projects/{project_id}` | 修改项目 | none |
| `GET` | `/projects/{project_id}/materials` | 项目下的材料 | cursor |
| `GET` | `/materials` | 材料库（含 Personal Library） | cursor |
| `GET` | `/materials/{material_id}` | 材料详情与当前版本 | none |
| `GET` | `/materials/{material_id}/versions` | 正式版本列表 | cursor |
| `GET` | `/materials/{material_id}/versions/{version_id}` | 不可变版本内容 | immutable |
| `POST` | `/materials/{material_id}/drafts` | 新建草稿 | idempotency |
| `GET` | `/drafts/{draft_id}` | 草稿内容与 ETag | etag |
| `PUT` | `/drafts/{draft_id}/revision` | 保存草稿修订 | etag |
| `GET` | `/drafts/{draft_id}/revisions` | 草稿版本历史 | cursor |
| `GET` | `/drafts/{draft_id}/quality-runs` | 该草稿的检查记录 | cursor |
| `GET` | `/quality-runs/{run_id}` | 检查结果与证据 | none |
| `GET` | `/drafts/{draft_id}/math-runs` | 该草稿的数学验证记录 | cursor |
| `GET` | `/tasks` | 任务列表 | cursor |
| `POST` | `/tasks` | 创建任务 | idempotency |
| `GET` | `/tasks/{task_id}` | 任务详情与允许动作 | none |
| `GET` | `/tasks/{task_id}/plan` | 当前计划版本与审批状态 | none |
| `GET` | `/executions/{execution_id}` | 执行详情 | none |
| `GET` | `/conversations/{conversation_id}/messages` | 会话消息 | cursor |
| `POST` | `/conversations/{conversation_id}/messages` | 发送教师消息 | idempotency |
| `GET` | `/knowledge/search` | 检索已审核资料 | cursor |
| `GET` | `/knowledge/sources` | 资料来源列表 | cursor |
| `POST` | `/knowledge/upload-intents` | 申请上传地址 | idempotency |
| `GET` | `/knowledge/sources/{source_id}` | 资料与解析、审核状态 | none |
| `POST` | `/materials/{material_id}/exports` | 请求导出 | idempotency |
| `GET` | `/exports/{export_id}` | 导出状态 | none |
| `GET` | `/exports/{export_id}/download-url` | 获取短时效下载地址 | none |
| `GET` | `/exports/{export_id}/preview-url` | 浏览器内预览（与下载同一渲染产物） | none |
| `GET` | `/activity` | 教师可见的 Activity 流 | cursor |

**未纳入本册的接口**：账户设置、知识审核队列的审批动作、管理员接口、批量操作。它们不参与黄金路径，押后到第二批（§9）。

### 3.1 知识库题目级接口

知识库的检索与引用单元是**题目**，不是文档。以下 8 个接口对应 K009 的题目级改造（D.13/D.14）。

| 方法 | 路径 | 用途 | 并发/分页 |
| --- | --- | --- | --- |
| `GET` | `/knowledge/questions` | 题目级检索，按分类、卷面题型、年份过滤 | cursor |
| `GET` | `/knowledge/questions/{question_id}` | 题目详情、切分位置与派生标注 | none |
| `GET` | `/knowledge/sources/{source_id}/questions` | 某张试卷的切分结果 | cursor |
| `POST` | `/knowledge/questions/{question_id}/segments` | 提交切分修正（合并 / 拆分 / 改题号） | idempotency |
| `POST` | `/knowledge/questions/{question_id}/annotations` | 提交标注修正（题型 / 知识点） | idempotency |
| `GET` | `/knowledge/categories` | 分类列表（平台分类 + 我的私有分类） | cursor |
| `POST` | `/knowledge/categories` | 新建教师私有分类 | idempotency |
| `POST` | `/knowledge/sources` | 提交上传后的资料进入审核 | idempotency |

**三条约定：**

1. **检索单位是题，不是卷。** `source_requirements` 的计数与 G2 的可用性判断都按题计；`GET /knowledge/search` 保留为文档级粗检索，不用于选题。
2. **切分修正与标注修正不用 `/actions/` 路径。** D5 附录 A 规定 `/actions/` 只用于 D4 教师动作；这两个是知识库的编辑操作，不进状态机。
3. **标注修正不改变原文。** 修正结果写入 `knowledge_annotations` 的新版本，原标注保留；题干与定位区间不可通过这两个接口修改。

**检索参数**（`GET /knowledge/questions`）：

| 参数 | 说明 |
| --- | --- |
| `category_id` | 分类过滤；教师的私有分类与平台分类可混用 |
| `paper_question_type` | `single_choice` / `multiple_choice` / `fill_blank` / `free_response` |
| `year_min` / `year_max` | “近期”通过它表达，默认近 3 年（模拟题）、近 5 年（高考题） |
| `q` | 关键词，命中题干或知识点 |
| `scope` | `platform` / `teacher` / 两者（默认两者） |
| `only_approved` | 默认 `true`，只返回已审核且已索引的题目 |


------------------------------------------------------------------------

## 4. 错误与状态码

| HTTP | 使用场景 |
| --- | --- |
| `200` | 读取成功；动作成功；幂等重放 |
| `201` | 创建成功（项目、任务、草稿、上传意图） |
| `202` | 请求已被接受、结果异步（创建导出） |
| `403` | 权限不足且对象可见（管理员场景） |
| `404` | 对象不存在或不属于当前 Owner |
| `409` | 状态、版本或门禁冲突（D4 中除 `AST_INVALID`/`CITATION_INVALID` 外的全部码） |
| `422` | 内容本身不合法（`AST_INVALID`、`CITATION_INVALID`） |
| `429` | 触发限流，响应带 `Retry-After` |

错误响应必须包含 `current_status`、`state_version` 与 `allowed_actions`，让前端能在出错后直接渲染可恢复的下一步。

------------------------------------------------------------------------

## 5. 并发控制

### 5.1 三种锁，各管一段

| 机制 | 保护对象 | 冲突返回 |
| --- | --- | --- |
| `expected_state_version` | 聚合状态机的并发推进 | `409 STATE_CONFLICT` |
| `If-Match`（ETag） | 草稿内容的并发编辑 | `409 REVISION_CONFLICT` |
| `Idempotency-Key` | 重复提交的副作用 | 返回首次结果，不报错 |

三者不能互相替代：状态版本正确不代表内容没被改过，内容 ETag 正确也不代表状态还能推进。

### 5.2 草稿保存

```http
PUT /api/v1/drafts/{draft_id}/revision
If-Match: "7-sha256:ab12cd34"
Idempotency-Key: 0190...

{ "document_schema_version": "1.0.0", "operations": [ ... ] }
```

- `If-Match` 由 `GET /drafts/{draft_id}` 的 `ETag` 头给出。
- 保存成功返回新 ETag 与 `revision_no`。
- 冲突时**不得**自动重试为最后写入者胜出；前端按 D1 §4.2 的规则重放纯文本操作，结构性冲突交教师处理。

### 5.3 幂等键规则

- 作用域：`(owner_id, route, idempotency_key)`。
- 有效期：24 小时；过期后同键视为新请求。
- 同键不同请求体：返回 `409`，防止误用。

------------------------------------------------------------------------

## 6. SSE 契约

### 6.1 端点

```http
GET /api/v1/conversations/{conversation_id}/events
Last-Event-ID: 1022
Accept: text/event-stream
```

### 6.2 事件信封

```text
id: 1023
event: execution.progress
data: {"seq":1023,"type":"execution.progress","aggregate":"execution","aggregate_id":"0190...","occurred_at":"2026-11-04T02:15:00Z","payload":{"step":"knowledge_retrieval","done":3,"total":7}}
```

| 字段 | 说明 |
| --- | --- |
| `id` | Event Sequence，单调递增，与 PostgreSQL `conversation_events` 一致 |
| `event` | `conversation.event`、`activity.updated`、`execution.progress`、`approval.requested` |
| `data.seq` | 与 `id` 相同，重复给出便于客户端解析 |
| `data.aggregate` / `aggregate_id` | 事件归属，便于客户端只刷新相关面板 |

### 6.3 断线恢复

```text
连接 → 服务端记录当前高水位
     → 回放 (Last-Event-ID, 高水位] 的历史事件
     → 消费高水位之后的实时通知
     → 按 seq 去重
```

- 客户端重连必须带 `Last-Event-ID`；不带则从当前高水位开始，**不回放全量**。
- 心跳：每 15 秒发一个注释行（`: ping`），防止中间层断连。
- 重连退避：1、2、5、10、30 秒。
- 事件丢失的兜底：客户端可定期调用 `GET /activity` 对账，不依赖 SSE 完整性。

**事实来源仍是 PostgreSQL。** SSE 只是通知通道，Redis Pub/Sub 只用于扇出；断线重连后状态以数据库为准（SM-R06）。

------------------------------------------------------------------------

## 7. 上传与下载

### 7.1 上传

```text
POST /knowledge/upload-intents
  → { upload_url, storage_key, expires_at }
PUT {upload_url}                       # 直传对象存储，不经过 API
POST /knowledge/sources                # 提交审核（§3.1）
```

- 上传意图 15 分钟有效。
- 服务端只保存 `storage_key` 与校验值，不接收文件二进制。
- 上传完成不等于入库；必须经过扫描、解析、教师审核（K009 生命周期）。

### 7.2 下载

```text
GET /exports/{export_id}/download-url
  → { url, expires_at }        # 10 分钟有效
```

- 不暴露 `storage_key`。
- 过期后重新申请，不延长旧链接。
- `ready` 状态不等于永久可用（D4 §6 Export）。

------------------------------------------------------------------------

## 8. 交付给 D3 与 D6

| 分册 | 从本册拿到什么 |
| --- | --- |
| D3 页面规格 | 每个页面需要调用的读接口；`allowed_actions` 驱动按钮显隐；错误码驱动引导文案 |
| D6 契约测试 | 63 个端点（23 动作 + 40 资源）的路径与状态组合；幂等重放、ETag 冲突、SSE 回放三类必测场景 |

### 8.1 页面与接口的对应（供 D3 直接引用）

| 页面 | 主要读接口 | 主要动作接口 |
| --- | --- | --- |
| Material Editor | `GET /drafts/{id}`、`GET /drafts/{id}/revisions` | `PUT /drafts/{id}/revision`、`draft.submit_check` |
| Plan Review | `GET /tasks/{id}/plan` | `task.approve_plan`、`task.request_plan_revision`、`plan_version.reject` |
| Quality Report | `GET /quality-runs/{id}`、`GET /drafts/{id}/quality-runs` | `draft.retry_check`、`draft.resolve_issue` |
| Publish Review | `GET /drafts/{id}`、`GET /quality-runs/{id}` | `draft.approve`、`draft.publish`、`draft.request_changes` |
| Export Center | `GET /exports/{id}`、`GET /exports/{id}/download-url` | `POST /materials/{id}/exports`、`export.cancel` |

------------------------------------------------------------------------

## 9. 第二批接口（明确押后）

| 领域 | 说明 |
| --- | --- |
| 账户与偏好 | 注册、登录、改密、MFA、通知设置 |
| 知识审核队列 | 审核通过/拒绝、权利确认、撤回（**切分与标注修正已在 §3.1 纳入**，这里只剩审批与撤回） |
| 管理员接口 | 安全事件、操作审批、执行审计 |
| 批量操作 | 批量放弃草稿、批量导出 |
| 共享与协作 | 跨 Project 引用管理、多人协作 |

押后理由：这些接口不参与黄金路径，且其形状依赖尚未冻结的模块设计（K002 Identity、K021 Admin）。提前设计会锁定错误假设。

------------------------------------------------------------------------

## 附录 A：接口命名规则

1. 动作接口固定形状：`/{资源}/{id}/actions/{kebab-case 动作名}`。
2. 动作名直接来自 D4 的 `trigger`，只做 kebab-case 转换，不改语义——保证动作表与接口表可机械化对照。
3. 读接口用名词复数；不使用动词路径（`/getTask` 之类）。
4. 子资源用嵌套路径，深度不超过三层。

## 附录 B：本册与 D4 的映射

| D4 概念 | D5 落地 |
| --- | --- |
| 23 个教师动作 | 23 个 `POST .../actions/...` |
| 23 组复合命令 | 每组一个接口；`compound` 字段直接标注 |
| 18 个错误码 | 409 / 422 映射见 §4 |
| `allowed_actions` | 每个动作响应与错误响应都返回 |
| Activity 聚合 | `GET /activity` + `activity.updated` SSE 事件 |

------------------------------------------------------------------------

**分册结束**

本册冻结接口形状。修改任何动作名、路径或错误码时，必须同步更新 [schemas/api_surface.v1.json](../schemas/api_surface.v1.json) 并通过 `design/check_api_surface.py`。
