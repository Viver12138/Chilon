# Chilon 产品设计分册 D4：动作、错误码与教师可见文案

> **文档类型**：设计分册（Design Volume）
> **分册编号**：D4
> **整理日期**：2026-11-04
> **状态**：**FROZEN FOR IMPLEMENTATION**
> **上游基线**：`Chilon_Project_Design_Master_Document.md` §21；分册 D1；`schemas/state_machines.v1.json`
> **用途**：把状态机翻译成动作、错误码与教师能看懂的话，作为 D3（页面）、D5（API）、D6（测试）的共同输入。

[//]: # (toc:start)
## 目录

- [0. 本册定位](#0-本册定位)
- [1. 动作模型](#1-动作模型)
- [2. 教师可执行动作](#2-教师可执行动作)
- [3. 复合命令](#3-复合命令)
- [4. 系统与 Worker 动作](#4-系统与-worker-动作)
- [5. 错误码](#5-错误码)
- [6. 教师可见状态文案](#6-教师可见状态文案)
- [7. 内部状态与 Activity 聚合](#7-内部状态与-activity-聚合)
- [8. 交付给后续分册的输入](#8-交付给后续分册的输入)
- [附录 A：文案规则](#附录-a文案规则)
- [附录 B：动作到复合命令速查](#附录-b动作到复合命令速查)

[//]: # (toc:end)

---

## 0. 本册定位

### 0.1 本册解决什么

主文档 §21 定义了 136 条状态迁移和 101 个状态，但这些都是**系统视角**的描述。教师界面需要的是另外三样东西：

| 问题 | 本册回答 |
| --- | --- |
| 老师能点什么？ | §2 教师可执行动作（23 条） |
| 一次点击要改几个聚合？ | §3 复合命令（23 组，单事务） |
| 点完之后老师看到什么？ | §6 教师可见状态文案（74 个状态） |
| 点失败了告诉他什么？ | §5 错误码（18 个） |

### 0.2 本册不做什么

- 不定义 HTTP Endpoint 路径、请求/响应字段（D5）。
- 不定义页面布局、按钮位置、组件（D3）。
- 不定义错误页视觉。

### 0.3 机器可读副本

本册的动作与错误码同时以 [schemas/actions.v1.json](../schemas/actions.v1.json) 维护，格式见 [schemas/actions.v1.schema.json](../schemas/actions.v1.schema.json)，由 `design/check_actions.py` 校验。

**关键约束**：每个 `(aggregate, trigger)` 在 Registry 中恰好出现一次，每条状态迁移恰好被一个动作认领。动作清单与状态机不可能各说一套——少了会报错，多了也会报错。

------------------------------------------------------------------------

## 1. 动作模型

### 1.1 三类 actor

| actor | 谁触发 | 是否暴露给教师 | 数量 |
| --- | --- | --- | --- |
| `teacher` | 教师在界面上点击或确认 | 是，有中文标签 | 23 |
| `system` | 业务规则、对账、其他模块事件 | 否 | 80 |
| `worker` | Celery Worker 或 Validator 进程 | 否 | 19 |

后两类合计 99 条，全部 `ui: hidden`，只有一句描述供日志和 Activity 使用。

### 1.2 可见性四档

| `ui` | 含义 | 呈现要求 |
| --- | --- | --- |
| `primary` | 当前状态下教师的主操作 | 主按钮，一屏最多一个 |
| `secondary` | 备选或辅助操作 | 次要按钮或菜单项 |
| `danger` | 不可逆或会丢弃工作 | 需要二次确认，文案必须说明后果 |
| `hidden` | 不对教师暴露 | 只出现在 Activity 与审计日志 |

### 1.3 复合命令

一轮教师操作往往要同时改多个聚合。例如“批准执行计划”必须一次性写成三件事：

```text
task.approve_plan        awaiting_plan_approval → ready
plan_version.approve     awaiting_approval → approved
plan_approval.approve    pending → approved
```

如果只成功一半，就会出现“Task 说已批准、但 Approval 仍是 pending”的分裂状态。因此本册引入**复合命令**：同一 `compound` 组的动作必须在**同一个 PostgreSQL 事务**内完成，任一失败全部回滚。

23 组复合命令见 §3。D5 的接口设计必须让一个命令对应一个 Endpoint，而不是三个。

### 1.4 动作合法性判定顺序

服务端处理任何教师动作时，按固定顺序判定，任一不通过即返回对应错误码：

1. **身份与归属**：登录态、Owner、Project 权限 → `FORBIDDEN` / `NOT_FOUND`
2. **状态匹配**：当前 `status` 是否为该动作的 `from` 状态 → `STATE_CONFLICT`
3. **版本匹配**：`state_version` / `If-Match` / `expected_revision_no` → `STATE_CONFLICT` / `REVISION_CONFLICT`
4. **终止态保护**：目标是否已终止 → `TERMINAL_STATE`
5. **业务守卫**：动作专属前置条件（新鲜度、审批、权利、AST）→ 各自错误码
6. **副作用与事件**：同事务更新状态、写业务事件、写 Outbox

**禁止**：客户端通过 `PATCH {status: ...}` 直接改状态（SM-R01）。所有状态只能经由本册列出的动作改变。

------------------------------------------------------------------------

## 2. 教师可执行动作

23 条，全部有中文标签。表格中的“可用状态”来自状态机 Registry，不是手写。

| 动作 | 标签 | 归属 | 可用状态 → 结果 | 失败错误码 |
| --- | --- | --- | --- | --- |
| `task.submit_requirement` | 提交教学要求 | K011 | `draft` → `planning` | `STATE_CONFLICT`、`REVISION_CONFLICT` |
| `task.approve_plan` | 批准执行计划 | K011 | `awaiting_plan_approval` → `ready` | `STATE_CONFLICT`、`PLAN_NOT_APPROVED` |
| `task.request_plan_revision` | 要求修改计划 | K011 | `awaiting_plan_approval` → `planning` | `STATE_CONFLICT` |
| `task.cancel` | 取消任务 | K011 | `draft` / `planning` / `awaiting_plan_approval` / `ready` / `needs_attention` → `cancelled` | `STATE_CONFLICT`、`TERMINAL_STATE` |
| `task.replan` | 重新规划 | K011 | `needs_attention` → `planning` | `STATE_CONFLICT` |
| `task.retry` | 重试执行 | K011 | `needs_attention` → `ready` | `STATE_CONFLICT`、`PLAN_NOT_APPROVED` |
| `task.request_cancel` | 请求取消任务 | K011 | `running` → `cancelling` | `STATE_CONFLICT` |
| `requirement_version.abandon` | 放弃该要求版本 | K011 | `draft` → `abandoned` | `STATE_CONFLICT`、`TERMINAL_STATE` |
| `plan_version.reject` | 拒绝该计划 | K011 | `awaiting_approval` → `rejected` | `STATE_CONFLICT`、`TERMINAL_STATE` |
| `plan_approval.revoke` | 撤回计划批准 | K011 | `approved` → `revoked` | `STATE_CONFLICT`、`PLAN_NOT_APPROVED` |
| `execution.request_pause` | 暂停执行 | K011 | `running` → `pause_requested` | `STATE_CONFLICT` |
| `execution.resume` | 继续执行 | K011 | `paused` → `queued` | `STATE_CONFLICT` |
| `draft.submit_check` | 提交检查 | K012 | `editing` / `changes_required` → `checking` | `STATE_CONFLICT`、`CHECK_IN_PROGRESS`、`AST_INVALID` |
| `draft.cancel_check` | 中止检查 | K012 | `checking` → `editing` | `STATE_CONFLICT` |
| `draft.approve` | 批准草稿 | K012 | `awaiting_review` → `approved` | `STATE_CONFLICT`、`STALE_GATE` |
| `draft.request_changes` | 要求修改 | K012 | `awaiting_review` → `changes_required` | `STATE_CONFLICT` |
| `draft.withdraw_approval` | 撤回发布批准 | K012 | `approved` → `awaiting_review` | `STATE_CONFLICT`、`STALE_GATE` |
| `draft.publish` | 发布为正式版本 | K012 | `approved` → `published` | `STATE_CONFLICT`、`STALE_GATE`、`APPROVAL_CONSUMED`、`AST_INVALID`、`CITATION_INVALID`、`RIGHTS_BLOCKED`、`SOURCE_NOT_AUTHORIZED` |
| `draft.abandon` | 放弃草稿 | K012 | `editing` / `checking` / `changes_required` / `awaiting_review` / `approved` / `needs_attention` / `needs_rebase` → `abandoned` | `STATE_CONFLICT`、`TERMINAL_STATE` |
| `draft.rebase` | 合并到最新版本 | K012 | `needs_rebase` → `editing` | `STATE_CONFLICT`、`REVISION_CONFLICT` |
| `draft.retry_check` | 重试检查 | K012 | `needs_attention` → `checking` | `STATE_CONFLICT`、`CHECK_IN_PROGRESS` |
| `draft.resolve_issue` | 恢复编辑 | K012 | `needs_attention` → `editing` | `STATE_CONFLICT` |
| `export.cancel` | 取消导出 | K012 | `queued` / `rendering` / `uploading` → `cancelled` | `STATE_CONFLICT`、`TERMINAL_STATE` |

### 2.1 三条容易误读的边界

**① 计划批准挂在 Task 上，不挂在 Plan Version 上。** `task.approve_plan` 是复合命令的入口，同一事务里会把 Plan Version 和 Plan Approval 一起推进。计划面板上显示按钮，但动作归属是 Task。Plan Version 自己只有“拒绝”一个教师动作。

**② 发布批准没有独立按钮。** `publication_approval` 的 `approved` 由 `draft.approve` 在同一事务写入（主文档 §21.9.1 明确要求），`consumed` 由 `draft.publish` 写入。教师界面上不存在“批准发布审批”这个按钮——批准草稿即批准发布。

**③ 导出重试不是状态迁移。** 主文档 §21.10 规定“重试创建新 Export 记录”。所以 `export.failed` 状态没有 `retry` 动作，重试是一次**创建**请求，不是对旧记录的状态变更。

------------------------------------------------------------------------

## 3. 复合命令

`transaction: single` 表示组内动作必须原子完成。

| 命令 | 成员动作 | 说明 |
| --- | --- | --- |
| `submit_requirement` | `task.submit_requirement`、`requirement_version.submit` | 提交要求的同时冻结版本并计算 Hash |
| `approve_plan` | `task.approve_plan`、`plan_version.approve`、`plan_approval.approve` | 一次批准同时推进三个聚合 |
| `reject_plan` | `plan_version.reject`、`plan_approval.reject` | 拒绝计划与其审批记录 |
| `request_plan_revision` | `task.request_plan_revision`、`plan_version.supersede` | 旧计划标记 superseded |
| `revoke_plan_approval` | `plan_approval.revoke` | 仅在 Execution 尚未启动时允许 |
| `retry_task` | `task.retry` | 复用仍有效的 Plan/Approval，旧 Attempt 保留 |
| `replan_task` | `task.replan` | 创建新的 Requirement/Plan 版本 |
| `cancel_task` | `task.request_cancel`、`execution.request_cancel` | 运行中取消走协调流程 |
| `cancel_task_immediate` | `task.cancel`、`execution.cancel` | 未启动时直接终止 |
| `abandon_requirement` | `requirement_version.abandon` | 放弃未提交的要求草稿 |
| `pause_execution` | `execution.request_pause` | 等待安全断点 |
| `resume_execution` | `execution.resume` | 复用同一 Execution ID，创建新 Run |
| `submit_check` | `draft.submit_check` | 固定当前 Revision 与 Content Hash |
| `cancel_check` | `draft.cancel_check` | 中止巡检并回到编辑 |
| `approve_draft` | `draft.approve`、`publication_approval.approve` | 批准草稿即批准发布 |
| `request_changes` | `draft.request_changes` | 教师自我打回 |
| `withdraw_draft_approval` | `draft.withdraw_approval`、`publication_approval.invalidate` | 撤回批准同时作废发布审批 |
| `publish_material` | `draft.publish`、`publication_approval.publish` | 发布事务：创建不可变版本 + 消费审批 |
| `abandon_draft` | `draft.abandon` | 不可逆 |
| `rebase_draft` | `draft.rebase` | 产生 rebase Revision，需重检 |
| `retry_check` | `draft.retry_check` | 目标 Revision 未变时重跑同一检查 |
| `resolve_issue` | `draft.resolve_issue` | 处理完非内容性问题后恢复编辑 |
| `cancel_export` | `export.cancel` | 终止排队或渲染中的导出 |

### 3.1 为什么必须是单事务

以 `approve_plan` 为例，如果三次更新不在一个事务里：

- 只更新了 Task：`ready`，但 Approval 还是 `pending` → 执行前的复核会失败，任务卡死。
- 只更新了 Approval：教师以为批了，Task 还停在 `awaiting_plan_approval` → 界面显示“等待批准”，教师重复点击。

这两种分裂状态都无法靠重试自愈。因此复合命令的原子性是硬约束，不是优化。

------------------------------------------------------------------------

## 4. 系统与 Worker 动作

99 条不对教师暴露，按聚合分布（总数 = 教师动作 + 隐藏动作）：

| 聚合 | 动作总数 | 其中教师动作 | 隐藏动作 |
| --- | --- | --- | --- |
| Task | 18 | 7 | 11 |
| Requirement Version | 3 | 1 | 2 |
| Plan Version | 6 | 1 | 5 |
| Plan Approval | 5 | 1 | 4 |
| Execution | 22 | 2 | 20 |
| Agent Run | 6 | 0 | 6 |
| Step Execution | 10 | 0 | 10 |
| Tool Execution | 9 | 0 | 9 |
| Draft | 18 | 10 | 8 |
| Quality Check Run | 5 | 0 | 5 |
| Math Validation Run | 5 | 0 | 5 |
| Publication Approval | 5 | 0 | 5 |
| Export | 10 | 1 | 9 |
| **合计** | **122** | **23** | **99** |

上表数字由 `design/check_actions.py` 从 Registry 统计得出，不是手工维护。注意：动作数少于迁移数（122 < 136），因为同一 `trigger` 的多条迁移会合并成一个动作——例如 `task.cancel` 一个动作覆盖 3 条迁移，`draft.abandon` 覆盖 4 条。

**不以“教师也能理解”为理由暴露内部动作。** 主文档 SM-R10 明确禁止把内部执行细节映射成业务状态。教师看到的是 §6 的文案与 §7 的 Activity 聚合，不是 `lease_lost` 或 `tool_timeout`。

------------------------------------------------------------------------

## 5. 错误码

### 5.1 总表

| 错误码 | HTTP | 触发条件 |
| --- | --- | --- |
| `STATE_CONFLICT` | 409 | 当前状态不允许该动作，或 `state_version` 不匹配 |
| `TERMINAL_STATE` | 409 | 目标已处于终止态，不能再次变更 |
| `REVISION_CONFLICT` | 409 | `If-Match` / `expected_revision_no` 与当前 Revision 不一致 |
| `PLAN_NOT_APPROVED` | 409 | Plan 或 Approval 已失效、被撤销，或 Hash 不匹配 |
| `STALE_GATE` | 409 | 质量或数学证据已过期，不再是当前 Revision 的有效证据 |
| `APPROVAL_CONSUMED` | 409 | 发布审批已被消费，不能重复使用 |
| `CHECK_IN_PROGRESS` | 409 | 该 Draft 已有检查在运行 |
| `AST_INVALID` | 422 | Teaching Document Schema 或 §20.9 语义规则不通过 |
| `CITATION_INVALID` | 422 | Citation 完整性、定位或 Hash 校验失败 |
| `SOURCE_NOT_AUTHORIZED` | 409 | 引用的来源未通过审核或不在已授权范围 |
| `RIGHTS_BLOCKED` | 409 | 来源权利范围不满足目标导出 Profile |
| `CAPABILITY_GAP` | 409 | `source_requirements` 无法被现有资料满足 |
| `SCOPE_EXPANSION_REQUIRED` | 409 | 请求命中 E2 范围扩展，必须先重新规划 |
| `EXPORT_NOT_READY` | 409 | 导出文件尚未生成或已过期 |
| `WORKER_LEASE_LOST` | 409 | 执行租约或 Fencing Token 已失效 |
| `OUTCOME_UNKNOWN` | 409 | 上一次副作用结果未对账，禁止重试 |
| `FORBIDDEN` | 403 | 身份、Owner 或 Project 权限不足 |
| `NOT_FOUND` | 404 | 对象不存在或不属于当前 Owner |

### 5.2 两条映射原则

1. **409 是“你再试一次也一样”，422 是“内容本身不合法”。** 前者可以通过改变状态或修正并发冲突解决，后者必须改内容。
2. **不要用一个泛化错误码兜底。** 每个守卫失败都有专属码，前端据此决定引导动作：`STALE_GATE` 引导“重新检查”，`CAPABILITY_GAP` 引导“补充资料”，`SCOPE_EXPANSION_REQUIRED` 引导“新建任务”。

### 5.3 错误响应结构

```json
{
  "error": {
    "code": "STALE_GATE",
    "message": "检查结果已过期，请重新提交检查。",
    "request_id": "0190...",
    "aggregate": "draft",
    "aggregate_id": "0190...",
    "current_status": "awaiting_review",
    "state_version": 7,
    "allowed_actions": ["draft.submit_check", "draft.abandon"],
    "details": {}
  }
}
```

`allowed_actions` 是让前端能自愈的关键字段：出错后前端不需要猜下一步能做什么，服务端直接告诉它。

------------------------------------------------------------------------

## 6. 教师可见状态文案

74 个状态，每个给一句“老师看到什么”和“能点什么”。文案规则见附录 A。

### Task

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `draft` | 正在整理教学要求，还没有生成执行计划。 | 提交教学要求、取消任务 |
| `planning` | 正在检索你的资料并生成执行计划。 | 取消任务 |
| `awaiting_plan_approval` | 执行计划已生成，等你确认后才会开始生成内容。 | 批准执行计划、要求修改计划、取消任务 |
| `ready` | 计划已批准，即将开始生成。 | 取消任务 |
| `running` | 正在按计划生成教学内容。 | 请求取消任务 |
| `completed` | 内容已生成并写入材料草稿，可以开始编辑。 | （无可执行动作） |
| `needs_attention` | 生成中断，需要你处理。原因见任务详情。 | 重新规划、重试执行、取消任务 |
| `cancelling` | 正在停止执行并清理临时资源。 | （无可执行动作） |
| `cancelled` | 任务已取消，未完成的内容不会被当作正式材料。 | （无可执行动作） |

### Requirement Version

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `draft` | 要求草稿，尚未提交。 | 放弃该要求版本 |
| `active` | 已提交，作为本次任务的冻结输入。 | （无可执行动作） |
| `superseded` | 已被更新的要求版本替代。 | （无可执行动作） |
| `abandoned` | 该要求版本已放弃。 | （无可执行动作） |

### Plan Version

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `draft` | 计划正在生成与校验。 | （无可执行动作） |
| `awaiting_approval` | 计划已就绪，等待你批准。 | 拒绝该计划 |
| `approved` | 计划已批准，可以作为执行依据。 | （无可执行动作） |
| `rejected` | 该计划版本已被拒绝。 | （无可执行动作） |
| `expired` | 该计划版本已超过有效期。 | （无可执行动作） |
| `invalidated` | 该计划版本已失效（输入或来源发生变化）。 | （无可执行动作） |
| `superseded` | 该计划版本已被新版本替代。 | （无可执行动作） |

### Plan Approval

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `pending` | 等待你批准计划。 | （无可执行动作） |
| `approved` | 你已批准该计划。 | 撤回计划批准 |
| `rejected` | 你已拒绝该计划。 | （无可执行动作） |
| `revoked` | 批准已撤回，执行不会使用该计划。 | （无可执行动作） |
| `invalidated` | 批准已失效（计划内容或来源发生变化）。 | （无可执行动作） |
| `expired` | 批准已过期。 | （无可执行动作） |

### Execution

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `queued` | 已排队，等待执行资源。 | （无可执行动作） |
| `starting` | 正在建立执行环境。 | （无可执行动作） |
| `running` | 正在执行当前计划。 | 暂停执行 |
| `pause_requested` | 正在暂停，等待安全断点。 | （无可执行动作） |
| `paused` | 已暂停，可以继续。 | 继续执行 |
| `cancel_requested` | 正在取消，等待执行确认停止。 | （无可执行动作） |
| `cancelling` | 正在终止工具调用并清理临时资源。 | （无可执行动作） |
| `outcome_unknown` | 执行结果暂时无法确认，正在核对，请不要重复提交。 | （无可执行动作） |
| `succeeded` | 本次执行已完成。 | （无可执行动作） |
| `failed` | 本次执行失败，可以查看原因后重试。 | （无可执行动作） |
| `cancelled` | 本次执行已取消。 | （无可执行动作） |
| `superseded` | 本次执行已被新的执行替代。 | （无可执行动作） |

### Draft

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `editing` | 草稿可编辑，也可以继续用对话修改。 | 提交检查、放弃草稿 |
| `checking` | 正在检查内容结构与数学正确性。 | 中止检查、放弃草稿 |
| `changes_required` | 检查发现问题，需要修改后才能发布。 | 提交检查、放弃草稿 |
| `awaiting_review` | 检查已通过（或无阻断问题），等待你审核发布。 | 批准草稿、要求修改、放弃草稿 |
| `approved` | 已批准，可以发布为正式版本。 | 发布为正式版本、撤回发布批准、放弃草稿 |
| `needs_rebase` | 材料已有更新的正式版本，需要先合并再发布。 | 合并到最新版本、放弃草稿 |
| `needs_attention` | 检查未能正常完成（基础设施或来源问题），需要你处理。 | 恢复编辑、重试检查、放弃草稿 |
| `published` | 已发布为正式版本，后续修改需新建草稿。 | （无可执行动作） |
| `abandoned` | 草稿已放弃。 | （无可执行动作） |
| `superseded` | 草稿已被另一个草稿替代。 | （无可执行动作） |

### Quality Check Run

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `queued` | 检查已排队。 | （无可执行动作） |
| `running` | 检查中。 | （无可执行动作） |
| `succeeded` | 检查已完成。 | （无可执行动作） |
| `failed` | 检查程序本身执行失败，这不是内容问题。 | （无可执行动作） |
| `cancelled` | 检查已中止。 | （无可执行动作） |
| `outcome_unknown` | 检查结果未能确认，正在核对。 | （无可执行动作） |

### Math Validation Run

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `queued` | 数学验证已排队。 | （无可执行动作） |
| `running` | 数学验证中。 | （无可执行动作） |
| `succeeded` | 数学验证已完成。 | （无可执行动作） |
| `failed` | 验证程序本身执行失败，这不是题目错误。 | （无可执行动作） |
| `cancelled` | 数学验证已中止。 | （无可执行动作） |
| `outcome_unknown` | 数学验证结果未能确认，正在核对。 | （无可执行动作） |

### Publication Approval

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `pending` | 等待发布审核。 | （无可执行动作） |
| `approved` | 你已批准发布，执行发布后生效。 | （无可执行动作） |
| `rejected` | 发布审核被拒绝。 | （无可执行动作） |
| `invalidated` | 发布批准已失效（草稿或质量结果已变化）。 | （无可执行动作） |
| `expired` | 发布批准已过期。 | （无可执行动作） |
| `consumed` | 发布已完成，该批准只能使用一次。 | （无可执行动作） |

### Export

| 状态 | 教师看到 | 可执行动作 |
| --- | --- | --- |
| `queued` | 导出已排队。 | 取消导出 |
| `rendering` | 正在生成文件。 | 取消导出 |
| `uploading` | 正在保存文件。 | 取消导出 |
| `ready` | 导出文件已生成，可以下载（链接有时效）。 | （无可执行动作） |
| `failed` | 导出失败，可以重试（会生成新的导出记录）。 | （无可执行动作） |
| `cancelled` | 导出已取消。 | （无可执行动作） |
| `outcome_unknown` | 文件状态无法确认，正在核对。 | （无可执行动作） |
| `expired` | 导出文件已过期，请重新导出。 | （无可执行动作） |

------------------------------------------------------------------------

## 7. 内部状态与 Activity 聚合

27 个内部状态不对教师逐条显示，只以聚合进度呈现：

| 聚合 | 状态数 | 教师看到什么 |
| --- | --- | --- |
| Agent Run | 7 | 不单独显示；`starting`/`running` 归入 Execution 的“正在生成”，`lost` 归入“正在核对” |
| Step Execution | 10 | 显示为步骤进度（如“3/7 步完成”），`blocked` 显示为“等待上游步骤” |
| Tool Execution | 9 | 显示为动作短语（“正在检索资料”“正在检查公式”），不显示 `authorizing` 等技术状态 |

**Activity 聚合规则**：

1. 一个 Execution 同时最多有一条进行中的 Activity。
2. Activity 文案从 Step/Tool 映射到教师可理解的短语，不使用内部状态名。
3. Execution 结束（任何终态）时 Activity 归档，不修改历史 Activity 的内容。
4. `outcome_unknown` 必须在 Activity 上明确提示“不要重复提交”，这是唯一需要教师改变行为的内部状态。

------------------------------------------------------------------------

## 8. 交付给后续分册的输入

| 分册 | 从本册拿到什么 |
| --- | --- |
| D2 信息架构 | 23 条教师动作的落点；哪些动作属于 Task 面板、哪些属于 Draft 面板 |
| D3 页面规格 | 74 条状态文案（§6）、按钮层级（§1.2）、危险操作确认要求（§1.2 `danger`） |
| D5 API/SSE | 23 组复合命令 → 23 个动作接口；18 个错误码 → 错误响应；`allowed_actions` 字段 |
| D6 测试矩阵 | 每个动作的合法/非法状态组合可直接从 Registry 生成；错误码断言 |

### 8.1 本册遗留的开放问题

| # | 问题 | 归属 |
| --- | --- | --- |
| O1 | `task.cancel` 在 `running` 时不可用（要走 `request_cancel`），前端是否需要合并成一个“取消”按钮并按状态分派 | D3 |
| O2 | 错误响应中的 `details` 结构按错误码分别定义 | D5 |
| O3 | 是否需要“批量动作”（如一次放弃多个 Draft） | D3 |
| O4 | Activity 短语表是硬编码还是规则化生成 | D3 |

------------------------------------------------------------------------

## 附录 A：文案规则

1. **说状态，不说实现。** “正在核对”而不是“outcome_unknown 对账中”。
2. **一句话讲清三件事**：现在在干什么、为什么停、你要不要动手。不需要动手的就不提“等待”。
3. **不承诺结果。** 质量检查写“检查完成”，不写“内容正确”。
4. **区分技术失败与内容失败。** 检查程序崩了要明确说“这不是内容问题”，否则教师会去改内容。
5. **危险操作写后果。** “放弃草稿”必须说明已完成的修改不再可用。
6. **不复述状态名。** 文案里不出现 `needs_rebase` 这类标识符。

## 附录 B：动作到复合命令速查

| 命令 | 入口动作 | 影响聚合 |
| --- | --- | --- |
| `submit_requirement` | `task.submit_requirement` | Task、Requirement Version |
| `approve_plan` | `task.approve_plan` | Task、Plan Version、Plan Approval |
| `reject_plan` | `plan_version.reject` | Plan Version、Plan Approval |
| `publish_material` | `draft.publish` | Draft、Publication Approval |
| `approve_draft` | `draft.approve` | Draft、Publication Approval |
| `cancel_task` | `task.request_cancel` | Task、Execution |
| `cancel_task_immediate` | `task.cancel` | Task、Execution |

其余命令只影响单一聚合，见 §3。

------------------------------------------------------------------------

**分册结束**

本册为 D3、D5、D6 的输入基线。修改动作、错误码或文案时，必须同时更新 [schemas/actions.v1.json](../schemas/actions.v1.json) 并通过 `design/check_actions.py`。
