# Chilon 项目设计总文档

> **文档类型**：项目总体设计与实施路线图\
> **整理日期**：2026-11-03\
> **最后更新**：2026-11-04（新增 §0.3 分册索引与分册 D1；回写 §20.9、§21.5.1、§21.7.1、§28.8）\
> **状态**：设计汇总稿（Living Design Document）\
> **用途**：作为 Chilon 后续产品设计、工程实施、Schema
> Registry、API、前端和测试工作的统一基线。

[//]: # (toc:start)
## 目录

- [0. 文档说明与状态约定](#0-文档说明与状态约定)
- [第一部分：产品定义与战略范围](#第一部分产品定义与战略范围)
  - [1. 产品定位](#1-产品定位)
  - [2. MVP 功能范围](#2-mvp-功能范围)
  - [3. 产品交互与信息架构](#3-产品交互与信息架构)
- [第二部分：总体技术架构](#第二部分总体技术架构)
  - [4. 推荐技术栈](#4-推荐技术栈)
  - [5. 总体架构](#5-总体架构)
- [第三部分：Agent 与 Harness 设计](#第三部分agent-与-harness-设计)
  - [6. Agent 总体设计](#6-agent-总体设计)
  - [7. DeepSeek Harness 复用策略](#7-deepseek-harness-复用策略)
- [第四部分：数据库总体设计](#第四部分数据库总体设计)
  - [8. 数据库核心决策](#8-数据库核心决策)
  - [9. Schema Registry 与 DDL 工程](#9-schema-registry-与-ddl-工程)
  - [10. 全局安全与 RLS](#10-全局安全与-rls)
  - [11. Index、事务与可靠性](#11-index事务与可靠性)
- [第五部分：业务模块设计](#第五部分业务模块设计)
  - [12. 模块总览与完整性状态](#12-模块总览与完整性状态)
  - [13. K002 — Identity & Account Management](#13-k002--identity--account-management)
  - [14. K009 — Knowledge Base](#14-k009--knowledge-base)
  - [15. K011 — Task & Agent Orchestration](#15-k011--task--agent-orchestration)
  - [16. K012 — Project & Material Management](#16-k012--project--material-management)
  - [17. K013 — Conversation & Activity](#17-k013--conversation--activity)
  - [18. K014 — Quality & Evaluation](#18-k014--quality--evaluation)
  - [19. K021 — Administrative Security](#19-k021--administrative-security)
- [第六部分：文档模型与端到端工作流](#第六部分文档模型与端到端工作流)
  - [20. Structured Teaching Document Model](#20-structured-teaching-document-model)
  - [21. K009 → K012 → K014 端到端内容链路](#21-k009--k012--k014-端到端内容链路)
- [第七部分：API、前端与用户体验](#第七部分api前端与用户体验)
  - [22. API 设计状态](#22-api-设计状态)
  - [23. UI/UX 与前端实现状态](#23-uiux-与前端实现状态)
- [第八部分：安全、隐私、质量与运维](#第八部分安全隐私质量与运维)
  - [24. 安全与隐私](#24-安全与隐私)
  - [25. 可观测性与运维](#25-可观测性与运维)
- [第九部分：数据库字段 Registry 专项规范](#第九部分数据库字段-registry-专项规范)
  - [26. Global Field Registry](#26-global-field-registry)
- [第十部分：当前设计进度与未完成事项](#第十部分当前设计进度与未完成事项)
  - [27. 已完成的设计工作](#27-已完成的设计工作)
  - [28. 尚未完成的关键设计工作](#28-尚未完成的关键设计工作)
- [第十一部分：建议实施路线图](#第十一部分建议实施路线图)
  - [29. 推荐阶段顺序](#29-推荐阶段顺序)
- [第十二部分：关键架构决策记录（ADR 摘要）](#第十二部分关键架构决策记录adr-摘要)
  - [30. 已确认决策](#30-已确认决策)
  - [31. 仍需冻结的决策](#31-仍需冻结的决策)
- [附录 A：重要共享实体唯一归属](#附录-a重要共享实体唯一归属)
- [附录 B：重要数据流边界](#附录-b重要数据流边界)
  - [B.1 三种历史记录](#b1-三种历史记录)
  - [B.2 关键事实来源](#b2-关键事实来源)
- [附录 C：项目完成定义（Definition of Done）](#附录-c项目完成定义definition-of-done)
- [附录 D：设计评审记录](#附录-d设计评审记录)
  - [D.1 2026-11-03 第一轮设计收敛](#d1-2026-11-03-第一轮设计收敛)
  - [D.2 2026-11-03 状态机设计收敛](#d2-2026-11-03-状态机设计收敛)
  - [D.3 2026-11-03 Teaching Document 与 Citation 契约冻结](#d3-2026-11-03-teaching-document-与-citation-契约冻结)
  - [D.4 2026-11-04 产品闭环协议（D1）](#d4-2026-11-04-产品闭环协议d1)
  - [D.5 2026-11-04 文档排版规范化](#d5-2026-11-04-文档排版规范化)
  - [D.6 2026-11-04 状态机机器可读化](#d6-2026-11-04-状态机机器可读化)
  - [D.7 2026-11-04 动作层（分册 D4）](#d7-2026-11-04-动作层分册-d4)
  - [D.8 2026-11-04 接口层（分册 D5）](#d8-2026-11-04-接口层分册-d5)
  - [D.9 2026-11-04 信息架构与门禁参数化（分册 D2）](#d9-2026-11-04-信息架构与门禁参数化分册-d2)
  - [D.10 2026-11-04 教师走查包](#d10-2026-11-04-教师走查包)
  - [D.11 2026-11-04 默认教学内容变更（取代 D.1 第 2–3 条、D.3 的节点覆盖描述）](#d11-2026-11-04-默认教学内容变更取代-d1-第-23-条d3-的节点覆盖描述)
  - [D.12 2026-11-04 需求门槛放宽与知识库分层](#d12-2026-11-04-需求门槛放宽与知识库分层)
  - [D.13 2026-11-04 题目级知识单元与派生标注](#d13-2026-11-04-题目级知识单元与派生标注)
  - [D.14 2026-11-04 题型分类只存卷面层](#d14-2026-11-04-题型分类只存卷面层)
  - [D.15 2026-11-04 Citation 定位支持跨段](#d15-2026-11-04-citation-定位支持跨段)
  - [D.16 2026-11-04 知识库接口补齐（D5 §3.1）](#d16-2026-11-04-知识库接口补齐d5-31)
  - [D.17 2026-11-04 平台权利策略三档化与未决看板](#d17-2026-11-04-平台权利策略三档化与未决看板)
  - [D.18 2026-11-04 授权结论 A 档与走查状态](#d18-2026-11-04-授权结论-a-档与走查状态)
  - [D.19 2026-11-04 教师走查结果与导出预览](#d19-2026-11-04-教师走查结果与导出预览)
  - [D.20 2026-11-04 页面级规格（分册 D3）](#d20-2026-11-04-页面级规格分册-d3)
  - [D.21 2026-11-04 K009 字段级设计（模块分册 K09）](#d21-2026-11-04-k009-字段级设计模块分册-k09)
  - [D.22 2026-11-04 验收与测试矩阵（分册 D6）](#d22-2026-11-04-验收与测试矩阵分册-d6)
  - [D.23 2026-11-04 Registry 与工程骨架](#d23-2026-11-04-registry-与工程骨架)
  - [D.24 2026-11-04 Alembic 基线与迁移闭环](#d24-2026-11-04-alembic-基线与迁移闭环)
  - [D.25 2026-11-04 K012 入库与流水线复用验证](#d25-2026-11-04-k012-入库与流水线复用验证)
  - [D.26 2026-11-04 K014 入库](#d26-2026-11-04-k014-入库)
  - [D.27 2026-11-04 K011 入库：用契约推导替代表清单恢复](#d27-2026-11-04-k011-入库用契约推导替代表清单恢复)
  - [D.28 2026-11-04 K013 + K021 入库：Phase 1 Registry 完成](#d28-2026-11-04-k013--k021-入库phase-1-registry-完成)
  - [D.29 2026-11-04 K002 入库与 owner_id 外键回填](#d29-2026-11-04-k002-入库与-owner_id-外键回填)
  - [D.30 2026-11-04 接入 GitHub 与 CI 首次联调](#d30-2026-11-04-接入-github-与-ci-首次联调)
  - [D.31 2026-11-04 行级安全上下文与隔离证明](#d31-2026-11-04-行级安全上下文与隔离证明)
  - [D.32 2026-11-04 CI 间歇性失败的真实原因：探活没探到正确的实例](#d32-2026-11-04-ci-间歇性失败的真实原因探活没探到正确的实例)
  - [D.33 2026-11-04 Outbox 派发器与投递契约](#d33-2026-11-04-outbox-派发器与投递契约)
  - [D.34 2026-11-04 身份服务与 RLS 的一个明确例外](#d34-2026-11-04-身份服务与-rls-的一个明确例外)
  - [D.35 2026-11-04 状态枚举漂移：8 个聚合的 `status` 与契约不符](#d35-2026-11-04-状态枚举漂移8-个聚合的-status-与契约不符)
  - [D.36 2026-11-04 契约驱动的 Task 服务，与契约里 5 条重复边](#d36-2026-11-04-契约驱动的-task-服务与契约里-5-条重复边)
  - [D.37 2026-11-04 方案审批服务，与一条永远无法满足的约束](#d37-2026-11-04-方案审批服务与一条永远无法满足的约束)
  - [D.38 2026-11-04 执行服务：消费审批、围栏令牌](#d38-2026-11-04-执行服务消费审批围栏令牌)
  - [D.39 2026-11-04 步骤 DAG，以及一次自己造成的 CI 反复](#d39-2026-11-04-步骤-dag以及一次自己造成的-ci-反复)
  - [D.40 2026-11-04 工具层：五道闸里归数据层的两道，与幂等键](#d40-2026-11-04-工具层五道闸里归数据层的两道与幂等键)
  - [D.41 2026-11-04 运行映射与未知结果对账，Phase 3 服务完成](#d41-2026-11-04-运行映射与未知结果对账phase-3-服务完成)
  - [D.42 2026-11-04 HTTP 层接入，与一次几乎被掩盖的隔离失效](#d42-2026-11-04-http-层接入与一次几乎被掩盖的隔离失效)
  - [D.43 2026-11-04 Agent 回合：一句需求变成一个可审批的方案](#d43-2026-11-04-agent-回合一句需求变成一个可审批的方案)
  - [D.44 2026-11-04 工具实现与执行器：一句话到题目](#d44-2026-11-04-工具实现与执行器一句话到题目)
  - [D.45 2026-11-04 材料投影与草稿：学生版是真的没有答案](#d45-2026-11-04-材料投影与草稿学生版是真的没有答案)
  - [D.46 2026-11-04 发布与导出：黄金路径闭合](#d46-2026-11-04-发布与导出黄金路径闭合)
  - [D.47 2026-11-04 认证端点：把系统交给一个真实的人](#d47-2026-11-04-认证端点把系统交给一个真实的人)
  - [D.48 2026-11-04 事件流：教师能看见“正在做什么”](#d48-2026-11-04-事件流教师能看见正在做什么)
  - [D.49 2026-11-04 PDF 导出、教师上传，与第五次 RLS 写入失效](#d49-2026-11-04-pdf-导出教师上传与第五次-rls-写入失效)
  - [D.50 2026-11-04 策略覆盖补齐：82/82，以及没做完的那一半](#d50-2026-11-04-策略覆盖补齐8282以及没做完的那一半)
  - [D.51 2026-11-04 谓词其实是对的，错的是播种用的会话](#d51-2026-11-04-谓词其实是对的错的是播种用的会话)
  - [D.52 2026-11-04 全部 16 个套件以非超级用户运行](#d52-2026-11-04-全部-16-个套件以非超级用户运行)
  - [D.53 2026-11-04 教师界面：从只能 curl 到一个教师能用的页面](#d53-2026-11-04-教师界面从只能-curl-到一个教师能用的页面)
  - [D.54 2026-11-04 部署：一条命令，以及只有真跑才看得见的三个问题](#d54-2026-11-04-部署一条命令以及只有真跑才看得见的三个问题)
  - [D.55 2026-11-04 阶段收束：现在的真实状态](#d55-2026-11-04-阶段收束现在的真实状态)
  - [D.56 2026-11-05 知识库摄入：上传的卷子终于能被检索到](#d56-2026-11-05-知识库摄入上传的卷子终于能被检索到)
  - [D.57 2026-11-05 答案提取：让答案来自卷子，而不是模型现编](#d57-2026-11-05-答案提取让答案来自卷子而不是模型现编)
  - [D.58 2026-11-05 题型识别：能判就说，判不了就 NULL](#d58-2026-11-05-题型识别能判就说判不了就-null)
  - [D.59 2026-11-05 PDF 摄入：有文字层就读，扫描件明说读不了](#d59-2026-11-05-pdf-摄入有文字层就读扫描件明说读不了)
  - [D.60 2026-11-05 知识点标签：让“出一道三角函数题”真的按考点去找](#d60-2026-11-05-知识点标签让出一道三角函数题真的按考点去找)
  - [D.61 2026-11-05 密码找回：没有邮件通道时，重置只能是一次管理操作](#d61-2026-11-05-密码找回没有邮件通道时重置只能是一次管理操作)
  - [D.62 2026-11-05 `must_change_password`：从占位列变成真正的闸](#d62-2026-11-05-must_change_password从占位列变成真正的闸)
  - [D.63 2026-11-05 OCR：一个接缝，三种引擎，默认关闭](#d63-2026-11-05-ocr一个接缝三种引擎默认关闭)
  - [D.64 2026-11-05 阿里云试卷切题：请求是真的，响应形状我没拿到](#d64-2026-11-05-阿里云试卷切题请求是真的响应形状我没拿到)
  - [D.65 2026-11-05 选哪个教育接口：切题优先，整页兜底，精细版暂缓](#d65-2026-11-05-选哪个教育接口切题优先整页兜底精细版暂缓)
  - [D.66 2026-11-05 收敛：只留试卷切题，删掉用不到的开关](#d66-2026-11-05-收敛只留试卷切题删掉用不到的开关)
  - [D.67 2026-11-05 阿里云联调：真实试卷跑通，以及它暴露的五个问题](#d67-2026-11-05-阿里云联调真实试卷跑通以及它暴露的五个问题)
  - [D.68 2026-11-05 19 题拿到 16 题：分辨率、碎片与缺口](#d68-2026-11-05-19-题拿到-16-题分辨率碎片与缺口)
  - [D.69 2026-11-05 用解析版校准：题干被污染，以及厂商在解析页失效](#d69-2026-11-05-用解析版校准题干被污染以及厂商在解析页失效)
  - [D.70 2026-11-05 迁移到 D 盘：C 盘被 Docker 塞满了](#d70-2026-11-05-迁移到-d-盘c-盘被-docker-塞满了)
  - [D.71 2026-11-05 环境恢复后补验：25 个套件 + 真实端到端](#d71-2026-11-05-环境恢复后补验25-个套件--真实端到端)
  - [D.72 2026-11-05 `pending_review` 说明原因，界面能看到并处理](#d72-2026-11-05-pending_review-说明原因界面能看到并处理)
  - [D.73 2026-11-05 复核闭环：补上缺的那道题，然后真的能被检索到](#d73-2026-11-05-复核闭环补上缺的那道题然后真的能被检索到)
  - [D.74 2026-11-05 界面上的复核闭环：缺题能补，补完能启用](#d74-2026-11-05-界面上的复核闭环缺题能补补完能启用)
  - [D.75 2026-11-05 改与删：切错的题终于能被修正](#d75-2026-11-05-改与删切错的题终于能被修正)
  - [D.76 2026-11-05 收尾：撤销、改题号，以及被数据推翻的解析版判据](#d76-2026-11-05-收尾撤销改题号以及被数据推翻的解析版判据)
  - [D.77 2026-11-05 JPG 上传：把“拍照/导出图片”这条最常见的输入接上](#d77-2026-11-05-jpg-上传把拍照导出图片这条最常见的输入接上)
  - [D.78 2026-11-05 范围澄清：平台语料是 P0，教师上传是 P1](#d78-2026-11-05-范围澄清平台语料是-p0教师上传是-p1)
  - [D.79 2026-11-05 真的把语料导进去了：34 道题、3 个来源](#d79-2026-11-05-真的把语料导进去了34-道题3-个来源)
  - [D.80 2026-11-05 语料到齐：6050 道真题，公式精确，六成有答案](#d80-2026-11-05-语料到齐6050-道真题公式精确六成有答案)
  - [D.81 2026-11-05 教材入库：974 页 OCR，1797 块，以及被挤掉的教材命中](#d81-2026-11-05-教材入库974-页-ocr1797-块以及被挤掉的教材命中)
  - [D.82 2026-11-05 模拟卷：抓取链路、两个 bug，以及一次外部服务到期](#d82-2026-11-05-模拟卷抓取链路两个-bug以及一次外部服务到期)

[//]: # (toc:end)

---

## 0. 文档说明与状态约定

本文档汇总当前项目对话中能够恢复的 Chilon 产品与技术设计。它同时记录已经确定的决策、已完成的设计、候选方案，以及尚未设计或尚未核实的工作。

### 0.1 状态标记

| 标记 | 含义 |
| --- | --- |
| **CONFIRMED** | 项目中已明确采纳的决策或设计 |
| **DESIGNED** | 已完成方案设计，但尚未实施或验证 |
| **PROPOSED** | 已提出候选方案，尚未正式冻结 |
| **PENDING** | 等待历史设计、字段或依赖核对 |
| **TODO** | 尚未完成设计、开发、测试或交付 |
| **DEFERRED** | 明确推迟到后续版本 |
| **UNKNOWN** | 当前可恢复的项目记录不足，不能可靠确认 |

### 0.2 重要声明

1.  本文档是设计基线，不代表数据库已经创建、Migration 已执行、代码已提交或服务已部署。
2.  “设计完成”与“实现完成”严格区分。
3.  历史对话中部分模块清单和字段细节未能完整恢复。对于这些内容，本文档标记为 `PENDING` 或 `UNKNOWN`，不凭空补造。
4.  任何正式 DDL 生成前，必须完成实体唯一归属、字段字典、关系、权限、索引、迁移依赖和 Schema Freeze Gate。
5.  本文档应随着设计核对和工程实施持续更新，并通过版本控制管理。

### 0.3 设计分册索引

主文档承载总体基线。进入详细设计后，具体协议、规格和验收标准按分册展开。分册与主文档冲突时以分册为准，并回写主文档。

| 分册 | 标题 | 状态 | 位置 |
| --- | --- | --- | --- |
| D1 | 产品闭环协议 | FROZEN FOR IMPLEMENTATION | [design/Chilon_Design_Volume_D1_Product_Closure_Protocol.md](design/Chilon_Design_Volume_D1_Product_Closure_Protocol.md) |
| D2 | 信息架构与导航树 | FROZEN FOR IMPLEMENTATION | [design/Chilon_Design_Volume_D2_Information_Architecture.md](design/Chilon_Design_Volume_D2_Information_Architecture.md) |
| D3 | 页面级规格与交互 | FROZEN FOR IMPLEMENTATION | [design/Chilon_Design_Volume_D3_Page_Specifications.md](design/Chilon_Design_Volume_D3_Page_Specifications.md) |
| D4 | 动作、错误码与教师可见文案 | FROZEN FOR IMPLEMENTATION | [design/Chilon_Design_Volume_D4_Actions_Errors_And_Copy.md](design/Chilon_Design_Volume_D4_Actions_Errors_And_Copy.md) |
| D5 | API 与 SSE 契约 | FROZEN FOR IMPLEMENTATION | [design/Chilon_Design_Volume_D5_Api_And_Sse_Contract.md](design/Chilon_Design_Volume_D5_Api_And_Sse_Contract.md) |
| D6 | 验收与测试矩阵 | FROZEN FOR IMPLEMENTATION | [design/Chilon_Design_Volume_D6_Acceptance_And_Test_Matrix.md](design/Chilon_Design_Volume_D6_Acceptance_And_Test_Matrix.md) |

D1 冻结了以下内容，后续分册与实现必须以它为准：七道门禁、八条闭环不变量、E0/E1/E2 变更分级、Draft Revision 的 checkpoint/autosave 二分、题源治理守卫、18 项验收指标与端到端 fixture 规格。

D4 冻结了：122 条动作（教师可见 23 条）、23 组单事务复合命令、18 个错误码、74 条教师可见状态文案。动作与错误码的机器可读副本为 `schemas/actions.v1.json`。

D5 冻结了：55 个接口（23 个动作接口 + 32 个资源接口）、三种并发控制的分工、SSE 事件信封与断线回放协议、上传下载的签名 URL 规则。机器可读副本为 `schemas/api_surface.v1.json`。

D2 冻结了：三层信息架构、13 个页面（黄金路径 5 / 骨架 5 / 押后 3）、门禁策略参数化（G4–G7 恒为强制，仅 G3 可按任务类型自动化）、完整生成流程 4 次点击的预算，以及教师走查脚本。机器可读副本为 `schemas/navigation.v1.json`。

### 0.4 部分与章节对照

主文档并行使用两套编号：“第X部分”划分大块，数字章节号用于精确引用（如 §21.8.2）。对照如下：

| 部分 | 章节 | 主题 |
| --- | --- | --- |
| [第一部分：产品定义与战略范围](#第一部分产品定义与战略范围) | 1–3 | 定位、MVP 范围、交互与信息架构 |
| [第二部分：总体技术架构](#第二部分总体技术架构) | 4–5 | 技术栈与总体架构 |
| [第三部分：Agent 与 Harness 设计](#第三部分agent-与-harness-设计) | 6–7 | Agent 职责、Harness 复用边界 |
| [第四部分：数据库总体设计](#第四部分数据库总体设计) | 8–11 | 类型、Registry、RLS、索引与事务 |
| [第五部分：业务模块设计](#第五部分业务模块设计) | 12–19 | K002 / K009 / K011 / K012 / K013 / K014 / K021 |
| [第六部分：文档模型与端到端工作流](#第六部分文档模型与端到端工作流) | 20–21 | 教学内容 AST、端到端链路、状态机 |
| [第七部分：API、前端与用户体验](#第七部分api前端与用户体验) | 22–23 | 接口与前端设计状态 |
| [第八部分：安全、隐私、质量与运维](#第八部分安全隐私质量与运维) | 24–25 | 安全边界与可观测性 |
| [第九部分：数据库字段 Registry 专项规范](#第九部分数据库字段-registry-专项规范) | 26 | 字段标准与 CI 检查 |
| [第十部分：当前设计进度与未完成事项](#第十部分当前设计进度与未完成事项) | 27–28 | 进度台账与设计缺口 |
| [第十一部分：建议实施路线图](#第十一部分建议实施路线图) | 29 | Phase 0–7 |
| [第十二部分：关键架构决策记录（ADR 摘要）](#第十二部分关键架构决策记录adr-摘要) | 30–31 | ADR-001–026 与待冻结决策 |
| [附录 A](#附录-a重要共享实体唯一归属)–[附录 D](#附录-d设计评审记录) | A–D | 实体归属、数据流、完成定义、评审记录 |

------------------------------------------------------------------------

# 第一部分：产品定义与战略范围

## 1. 产品定位

### 1.1 产品名称

**Chilon**

### 1.2 产品定位

Chilon 是面向个人高中教师的 **AI Teaching Agent + Teaching Workspace**，帮助教师根据教学要求和个人教学资料，高效生成、编辑、检查和导出高质量教学材料。

### 1.3 目标用户

-   初始目标：个人高中教师。
-   典型使用方式：一对一教学、小班教学和个人备课。
-   初始学科：中国高中数学。
-   初始课程体系：中国普通高考（Gaokao）。

### 1.4 核心价值

1.  将教师的自然语言教学要求转化为结构化任务。
2.  检索教师个人已审核的教学资料。
3.  生成结构化、可编辑、可追溯的教学材料。
4.  通过数学验证和质量检查降低错误风险。
5.  支持教师通过聊天和文档编辑持续修改。
6.  输出可用于实际教学的 Word 和 PDF 文件。

### 1.5 产品形态

-   Web 应用。
-   AI Agent 与 Teaching Workspace 融合。
-   Project 作为教学专题的主要组织单位。
-   Chat 与结构化 Workspace 双模式协作。
-   教师始终保留计划批准、内容审核和正式发布权。

### 1.6 首个 MVP 基准教学场景

**状态：DESIGNED（第一轮产品闭环与验收基线）**

首个用于贯穿产品设计、领域建模、Agent 行为、API、前端和验收测试的基准场景为：

> 面向中国高中数学“三角函数”专题，生成一份可用于教学的讲义，配合来自教辅书的例题、高考真题与近期模拟题。

该场景不是 MVP 支持范围的唯一内容，而是第一个必须端到端跑通的“黄金路径”。后续功能设计应优先回答它遇到的问题，避免在缺少具体教学闭环时继续堆叠抽象能力。

#### 1.6.1 默认教学内容的四类来源

**2026-11-04 变更**：移除“教材例题”，教学内容改为四类来源。教材书仍在使用，但角色从“提供例题”改为“提供知识依据”。

| 来源 | `source_type` | 在交付物中的角色 | `provenance.kind` |
| --- | --- | --- | --- |
| 教材书（默认人教版数学） | `textbook` | 知识依据：定义、定理、公式、课标要求 | 一般不单独成块；需要摘录原文时用 `adapted` |
| 教辅书（辅导书） | `workbook` | 例题与方法总结 | `workbook_example` |
| 高考真题 | `gaokao_paper` | 真题练习 | `gaokao_question` |
| 近期模拟题 | `mock_exam` | 近年模拟练习 | `mock_question` |

- 四类来源默认来自**平台知识库**（项目方提供，四个默认分类见 §14.1），教师未上传时也能直接使用；教师也可在自己知识库中新增分类并上传。
- “近期”默认为**近 3 年（含当年）**；高考真题默认近 5 年。
- **难度不是默认维度**：需求不要求难度，Agent 不按难度筛选；教师显式要求时才处理。
- 课时/篇幅、资料范围不是必填项：课时默认为 1 课时，资料范围默认为平台知识库 + 教师已审核资料。
- 平台来源权利由平台授权，`rights.status = licensed`；教师来源默认 `unverified`，确认后才能发布或导出。
- `textbook_example` 节点类型保留在 Schema 中以便兼容与后续使用，但不属于默认模板。

该场景的最低内容要求：

-   讲义包含学习目标、前置知识、定义/定理/公式、解题方法、易错点、章节总结。
-   教辅例题保留教辅来源（出版社、版本、页码）、题目原文和完整解答，并明确其与讲义知识点的关系。
-   高考真题保留年份、地区、试卷、题号、原题和答案解析等来源元数据。
-   模拟题保留年份、地区、考试名称（如“2026 届高三第一次模拟考试”）、题号、原题和答案解析。
-   AI 补充内容、对原题的改编和原题引用必须明确区分，不能将模型生成内容伪装成教材、教辅、高考或模拟原题。
-   教师可以审核来源、Agent Plan、生成内容、数学验证结果和质量问题，并完成最终发布。
-   教师版与学生版按用途导出；学生版不得包含不应公开的答案、解析或教师备注。

该场景的完整验收链路为：

``` text
选择教师已审核资料
      |
输入教学目标与材料要求
      |
检索教辅例题、高考真题与近期模拟题
      |
生成包含来源清单的 Agent Plan
      |
教师批准 Plan
      |
生成结构化讲义与题目
      |
数学验证与内容质量检查
      |
Chat 修改或直接文档编辑
      |
教师审核并发布不可变 Material Version
      |
导出教师版和学生版
```

## 2. MVP 功能范围

### 2.1 初始内容类型

#### Lesson

包括： - 知识讲解 - 学习目标 - 前置知识 - 定义、定理和性质 - 公式总结 - 解题方法 - 例题及步骤 - 易错点 - 知识联系 - 章节总结

#### Exercises

支持： - 选择题 - 多选题 - 填空题 - 简答题 - 计算题 - 证明题 - 应用题

支持难度： - Basic - Medium - Advanced - Challenge

支持答案和解析，并与题目节点建立明确关联。

#### Worksheet

支持： - 知识摘要 - 公式 - 例题 - 课堂练习 - 学生作答空间 - 教师版与学生版

学生版导出必须从文档 AST 中排除答案、解析和教师备注，不能仅通过 CSS 隐藏。

### 2.2 编辑与导出

-   Web 在线编辑。
-   AI Chat 修改。
-   直接文档编辑。
-   Word 导出。
-   PDF 导出。
-   同一结构化文档模型作为编辑、验证和导出的共同来源。

### 2.3 人机协作原则

-   Agent 先分析需求并生成任务计划。
-   教师批准计划后才开始正式执行。
-   Agent 生成材料并进行自动质量检查。
-   教师完成最终审核。
-   AI 质量检查不能被表述为绝对正确保证。

## 3. 产品交互与信息架构

### 3.1 核心交互模式

采用 **Hybrid Interaction**： - 结构化参数输入，适合明确、重复的教学任务。 - 自然语言对话，适合探索、澄清和迭代修改。

### 3.2 Workspace + Chat

桌面端建议三栏： 1. 左侧：导航、Project、Material。 2.
中间：文档编辑与预览。 3. 右侧：AI Chat、任务计划、质量反馈。

小屏设备采用可折叠侧栏和面板切换。

### 3.3 导航原则

采用 Workflow-oriented Information Architecture，以教学工作流为主线。一个教学专题对应一个 Project。

### 3.4 主要工作流

1.  创建或选择 Project。
2.  描述教学目标和材料要求。
3.  Agent 分析需求。
4.  Agent 检索教师已审核资料。
5.  Agent 生成任务计划。
6.  教师批准计划。
7.  Agent 生成内容。
8.  质量与数学检查。
9.  教师修改和审核。
10. 发布为正式 Material Version。
11. 导出 DOCX/PDF。

------------------------------------------------------------------------

# 第二部分：总体技术架构

## 4. 推荐技术栈

| 层 | 推荐技术 | 状态 |
| --- | --- | --- |
| Web Frontend | React + TypeScript | DESIGNED |
| Backend API | Python + FastAPI | CONFIRMED |
| ORM | SQLAlchemy 2.0 Async | CONFIRMED |
| PostgreSQL Driver | asyncpg | CONFIRMED |
| Migration | Alembic | CONFIRMED |
| Database | PostgreSQL 17.x | CONFIRMED |
| Cache / Broker | Redis | CONFIRMED |
| Background Jobs | Celery | CONFIRMED |
| Object Storage | S3-compatible Object Storage | DESIGNED |
| Agent Runtime | DeepSeek Harness | CONFIRMED as adopted direction |
| Agent SDK Integration | DeepSeek Harness Python SDK | DESIGNED |
| Math Validation | SymPy isolated Validator Service | DESIGNED |
| Observability | OpenTelemetry + Prometheus + Grafana | DESIGNED |
| Vector Retrieval | pgvector, later phase | DEFERRED |

具体版本锁定、部署拓扑和供应商选择仍需在实施阶段确定。

## 5. 总体架构

``` text
Chilon Web Frontend
       |
       v
FastAPI Application
       |
       +-------------------- PostgreSQL
       |                       |
       +-------------------- Redis
       |
       +-------------------- Object Storage
       |
       +-------------------- Celery Workers
                                  |
                                  v
                         Chilon Agent Control Plane
                                  |
                                  v
                         DeepSeek Harness Runtime
                                  |
                     +------------+------------+
                     |            |            |
                  Plugins       Tools       Domain Services
                     |            |            |
                     +------------+------------+
                                  |
                         Knowledge / Math /
                         Content / Quality /
                         Export Services
```

### 5.1 职责边界

-   FastAPI：身份认证、API、业务权限、请求上下文。
-   PostgreSQL：业务数据唯一权威来源。
-   Redis：缓存、Celery Broker、临时流式缓冲和通知，不作为业务事实来源。
-   Celery：异步任务调度。
-   Object Storage：上传文件、导出文件和大型二进制内容。
-   Chilon Control Plane：教学业务策略、授权、计划批准、质量门禁和发布控制。
-   DeepSeek Harness：Agent Runtime 执行循环、工具注册与执行、上下文管理和插件机制。
-   Chilon Domain Services：知识检索、数学验证、文档生成、质量检查和导出。

------------------------------------------------------------------------

# 第三部分：Agent 与 Harness 设计

## 6. Agent 总体设计

### 6.1 架构决策

采用：

**DeepSeek Harness as Agent Runtime + Chilon Teaching Agent Control Plane**

不从零重写 Agent Harness。复用底层 Runtime 能力，把核心研发资源投入教学业务能力。

### 6.2 Chilon Agent 内部职责模块

1.  Requirement Analyzer
2.  Knowledge Retriever
3.  Template Selector
4.  Task Planner
5.  Content Generator
6.  Quality Checker
7.  Revision Agent

初期采用一个统一 Agent Orchestrator 和内部专业模块，不在 MVP 阶段拆成多个独立 Agent 服务。

### 6.3 主要执行流程

``` text
Teacher Request
      |
Requirement Analysis
      |
Knowledge Retrieval
      |
Template Selection
      |
Task Planning
      |
Teacher Plan Approval
      |
Content Generation
      |
Quality & Math Validation
      |
Teacher Review / Revision
      |
Material Publication
      |
Export
```

### 6.4 Human-in-the-loop

-   计划审批是正式执行的业务门槛。
-   教师最终审核是材料发布的业务门槛。
-   Agent 不得自行扩大知识检索范围。
-   Agent 不得伪造知识来源或数学验证证据。
-   不确定的数学结果必须标为 `inconclusive` 或 `unsupported`。
-   Harness 内部事件不能全部直接暴露给教师。
-   不向用户展示模型内部推理内容。

### 6.5 基准教学场景的 Agent 约定

对“三角函数讲义 + 教辅例题 + 高考真题 + 近期模拟题”基准场景，Agent 必须满足：

1.  Requirement Analyzer 明确年级、专题、课时、内容类型、题量、难度和导出用途；缺失的关键要求应进入澄清，而不是自行假设。
2.  Knowledge Retriever 只检索当前教师已审核且属于当前教学范围的资料，并保留可定位到来源文件的引用。
3.  Task Planner 在正式执行前列出预计使用的参考资料、讲义结构、教辅例题选择原则、真题与模拟题的范围（含年份区间）和需要执行的验证。
4.  Content Generator 对每个文档节点标明来源类型：教材依据、教辅原文、高考原题、模拟题原题、教师资料、合规改编或 AI 补充内容。
5.  教辅例题、高考真题与模拟题不得仅凭模型记忆复现；若输入资料不足，应请求教师补充资料或明确标为不支持，不能伪造出处。
6.  数学验证必须绑定具体题号、公式或节点 ID，区分 `passed`、`failed`、`inconclusive` 和 `unsupported`。
7.  来源不足、授权范围不足或数学验证不通过时，Agent 必须停留在草稿或等待教师处理，不得自动发布。
8.  Chat 修改必须转换成可审计的文档变更；影响教案范围、题目来源或题量结构的变化，应按业务规则重新进入计划确认或质量检查。

## 7. DeepSeek Harness 复用策略

### 7.1 已采纳方向

复用 DeepSeek Harness 的底层能力： - Agent Loop - LLM Adapter - Tool Registry - Tool Execution Pipeline - Session Event Log - Context Assembly - Compaction - Approval primitives - Subagent Runtime（后续） - Plugin System

### 7.2 Chilon 自主控制的业务能力

Harness 不能替代： - 教师是否批准任务计划。 - Agent 是否可以访问某位教师的私有资料。 - 当前任务是否允许生成新题。 - 数学验证是否达到业务要求。 - 教师是否接受某项修改。 - 是否创建正式 Material Version。 - 是否允许跨 Project 引用。 - 业务审计和数据归属。

**原则：Harness 负责执行能力，Chilon 负责业务授权与最终决策。**

### 7.3 集成方式

推荐 Python SDK 启动 Harness Runtime，通过 stdio 上的 newline-delimited JSON-RPC 通信。后端继续使用 Python/FastAPI，不因 Harness 而重写为 Node 服务。

### 7.4 安全与成熟度风险

-   DeepSeek Harness 在项目研究时处于 developer preview，可能存在 breaking changes。
-   不能将其视为已经通过完整安全审计的生产组件。
-   沙箱不能被视为绝对隔离。
-   插件、MCP、外部模型和服务可能产生第三方数据传输。
-   必须使用最小权限、独立容器或 VM、网络出口限制、插件审查、运行时监控和审计。
-   复用开源代码时保留 MIT License 声明，并审查第三方依赖许可证。
-   Harness Runtime 与 Chilon Control Plane 之间应有明确版本兼容层。

### 7.5 TODO

-   [ ] 复核 Harness 当前仓库版本、API 和 SDK 兼容性。
-   [ ] 锁定可复现的 Runtime 版本和依赖。
-   [ ] 建立 Harness Adapter 接口，避免业务代码直接耦合 Runtime 内部 API。
-   [ ] 设计 Runtime 隔离、网络策略、文件系统权限和密钥注入。
-   [ ] 定义 Plugin Manifest、签名/来源审查和版本锁定。
-   [ ] 设计 Harness 崩溃、超时、重启和 Session 恢复。
-   [ ] 建立 Harness 升级兼容性测试。
-   [ ] 对外部模型和插件数据流进行隐私评估。

------------------------------------------------------------------------

# 第四部分：数据库总体设计

## 8. 数据库核心决策

### 8.1 基础选择

-   PostgreSQL 17.x。
-   单一 `public` Schema。
-   UUIDv7 由应用层生成。
-   所有时间戳使用 UTC `TIMESTAMPTZ`。
-   JSONB 用于确有灵活结构需求的数据，并配套 Schema Version。
-   金额、比例、评分等精确数值使用 NUMERIC，不使用 FLOAT/REAL/DOUBLE。
-   正式材料版本不可变。
-   业务事件 Append-only。
-   Owner 复合外键 + RLS + Service Authorization。
-   Registry 是 DDL、ORM、Migration 和测试的唯一结构权威。

### 8.2 命名规范

-   表名：snake_case 复数。
-   字段名：snake_case。
-   主键：`id`。
-   私有业务表通常包含 `owner_id`。
-   复合唯一键优先 `UNIQUE(owner_id, id)`。
-   跨表关系优先使用 Owner 复合 FK。
-   删除默认 `RESTRICT`，不全局使用 CASCADE。

### 8.3 主要数据类型

| 业务语义 | PostgreSQL 类型 | 规则 |
| --- | --- | --- |
| 主键/外键 | UUID | 应用生成 UUIDv7 |
| 短名称/Key | VARCHAR(n) | 长度由语义决定 |
| 长文本 | TEXT | 不设置无意义的统一长度 |
| 整数计数 | SMALLINT/INTEGER/BIGINT | 按范围选择 |
| 精确数值 | NUMERIC(p,s) | 按业务精度选择 |
| 标志 | BOOLEAN | 明确 NULL 语义 |
| 业务日期 | DATE | 不伪装成时间戳 |
| 时间点 | TIMESTAMPTZ | UTC |
| 结构化数据 | JSONB | 必须有结构校验 |
| 文件内容 | Object Storage | DB 只保存元数据和 storage_key |
| 哈希 | CHAR(64) 或受约束 VARCHAR | SHA-256 lowercase hex 建议 |
| 大型二进制 | BYTEA 谨慎使用 | 普通文件不存业务表 |

## 9. Schema Registry 与 DDL 工程

### 9.1 Registry-First

采用：

**Schema Registry-First + Deterministic DDL Generator + Alembic Migration**

`database/registry/` 是唯一结构权威。

建议目录：

``` text
database/
  registry/
    schema.json          # 全局设置：命名、类型映射、模块与表清单、表顺序
    fields/
      k009.json          # 按模块聚合：表、字段、约束、索引、策略
  generator/
    validate_registry.py # FLD-001..012 + 结构一致性
    generate_ddl.py      # 确定性 DDL + manifest（带 registry/schema hash）
  generated/
    k009.sql             # 产物，不要手改
    manifest.json
  README.md
```

**2026-11-04 实现说明**：最初设想按关注点拆成 `module-registry`、`field-registry/`、`relations/`、`indexes/`、`policies/` 等独立文件。实际实现改为**按模块聚合的单文件**（`fields/k009.json` 内含该模块的表、字段、约束、索引、策略）。

理由：一个模块的字段、索引、策略需要一起评审，拆开后评审者要在 5 个文件间跳转；而跨模块共享的结构（命名、类型映射、表清单）已经在 `schema.json` 中集中。若后续单模块表数超过 30 张，再按关注点拆分，届时迁移成本很低。

### 9.2 DDL 生成顺序

1.  Extensions
2.  ENUM / DOMAIN
3.  Functions
4.  Base Tables
5.  Dependent Tables
6.  Constraints
7.  Indexes
8.  Triggers
9.  RLS Policies
10. Permissions / Grants

### 9.3 Deterministic Generation

相同 Registry、Generator 和配置必须生成相同 SQL 与 Hash。生成结果包含 Manifest，记录 Registry 版本、Generator 版本和 Schema Hash。

### 9.4 Alembic

-   Alembic 管理正式 Migration。
-   Autogenerate 只生成候选变更。
-   候选 Migration 必须审查。
-   大表索引可使用独立非事务 Migration + `CREATE INDEX CONCURRENTLY`。
-   采用 Expand–Migrate–Contract。
-   Production Migration 需人工批准。

### 9.5 Schema Freeze Gate

``` text
Module Registry
      |
Entity Ownership
      |
Field Dictionary
      |
Relations & Constraints
      |
Security / RLS / Permissions
      |
Migration Dependency Graph
      |
Freeze Approval + Manifest
      |
DDL Generation
```

表级 `confirmed` 不代表字段级已完整冻结。正式 DDL 需要字段、类型、约束、FK、索引、RLS、权限和 Migration 全部通过。

## 10. 全局安全与 RLS

### 10.1 四层安全

1.  Authentication
2.  Service Authorization
3.  PostgreSQL RLS
4.  Constraints / Audit

### 10.2 Database Roles

能力角色建议： - `chilon_db_owner` - `chilon_migration` - `chilon_app` - `chilon_worker` - `chilon_system_worker` - `chilon_readonly` - `chilon_backup`

运行时角色不得拥有业务表，不得具有 `BYPASSRLS`。实际部署使用独立 Login Principals，不在 SQL 源码写入密码。

### 10.3 RLS

-   私有表 `ENABLE ROW LEVEL SECURITY`。
-   私有表 `FORCE ROW LEVEL SECURITY`。
-   用户上下文通过事务级 GUC 设置。
-   每个请求独立 AsyncSession/事务。
-   GUC 不是数据库身份认证，不能抵御数据库凭据失陷。
-   Worker 不信任队列消息中的 `owner_id`，必须核验 Execution。
-   Admin 不提供无条件 RLS bypass。

上下文函数： - `public.app_current_user_id()` - `public.app_current_request_id()` - `public.app_current_execution_id()`

事务内设置：

``` sql
SELECT
    set_config('app.current_user_id', :user_id, true),
    set_config('app.current_request_id', :request_id, true),
    set_config('app.current_execution_id', :execution_id, true);
```

### 10.4 外键与删除

-   私有业务对象优先 Owner 复合 FK。
-   默认 `ON DELETE RESTRICT`。
-   只对生命周期完全从属的实体考虑有限 CASCADE。
-   用户隐私删除通过专门 Workflow。
-   多态引用由 Service Layer 校验；重要关系使用明确 FK。
-   DAG 无环、跨对象业务状态由 Service Layer 检查。

## 11. Index、事务与可靠性

### 11.1 索引策略

-   B-tree 为默认。
-   Partial B-tree 用于软删除、待处理任务和有效租约。
-   GIN 用于确有查询需求的 JSONB/全文检索。
-   BRIN 用于大型时间序列。
-   pgvector 后续启用。
-   不为每个字段机械创建索引。
-   每个索引登记对应查询用途。
-   FK referencing side 必须检查是否有合适索引。

### 11.2 关键查询模式

-   Agent Queue：Partial Index + `FOR UPDATE SKIP LOCKED`。
-   Outbox Polling：按可投递状态和时间查询。
-   Conversation Events：`(conversation_id, sequence_number)`。
-   Material Version：`(owner_id, material_id, version_number)`。
-   Owner-scoped 查询优先检查 Owner 条件和索引顺序。

### 11.3 事务原则

-   短事务。
-   不在 LLM 请求、文件上传、导出等外部等待期间持有数据库事务。
-   Task 与 Outbox 同事务。
-   业务状态变更与事件写入同事务。
-   采用幂等键和 At-least-once 消费。
-   超时不等于失败；先查询状态再重试。
-   Agent Execution 使用 Lease/Fencing Token 设计，具体字段归属待最终 Registry 核对。

### 11.4 连接池与性能目标

初始压测起点： - API pool_size=10 / max_overflow=5。 - Worker pool_size=5 / max_overflow=2。

这些是初始配置，不是容量保证。API、Agent Worker、General Worker、Migration、Monitoring 使用独立连接池。

初始 P95 目标（待压测验证）： - 主键读取：50ms - 列表查询：100ms - 关联查询：200ms - 写操作：150ms - DB 事务：200ms

### 11.5 监控与恢复

-   pg_stat_statements
-   EXPLAIN ANALYZE BUFFERS
-   OpenTelemetry
-   Prometheus
-   Grafana
-   PostgreSQL 备份 + WAL/PITR

初始恢复目标： - RPO：15 分钟 - RTO：4 小时 - 每月恢复演练

上述目标必须在实际基础设施上验证。

------------------------------------------------------------------------

# 第五部分：业务模块设计

## 12. 模块总览与完整性状态

当前项目记录能够确认的模块范围：

| 模块 | 当前状态 | 说明 |
| --- | --- | --- |
| K001 | UNKNOWN / PENDING | 历史模块定义与实体清单需恢复 |
| K002 | DESIGNED | Identity & Account：7 张表已入 Registry，owner_id 外键已回填（D.29） |
| K003–K008 | UNKNOWN / PENDING | 历史定义未完整恢复 |
| K009 | DESIGNED | Knowledge Base 核心设计完成，待历史去重 |
| K010 | PENDING | 历史模块定义待恢复 |
| K011 | PARTIALLY DESIGNED | Task & Agent；已知约 15 张表，完整约 35 张清单未恢复 |
| K012 | DESIGNED | Project & Material 核心设计完成 |
| K013 | DESIGNED | Conversation & Activity 核心设计完成 |
| K014 | DESIGNED | Quality & Evaluation 24 张核心表设计完成 |
| K015–K020 | UNKNOWN / PENDING | 历史模块定义待恢复 |
| K021 | DESIGNED | Administrative Security 核心设计完成 |
| K022–K023 | UNKNOWN / PENDING | 历史模块定义待恢复 |
| K024 | UNKNOWN | 编号是否对应独立模块尚未确认 |

**注意：**不能因为模块编号存在，就推断其业务名称或表清单。

## 13. K002 — Identity & Account Management

### 13.1 职责

-   用户账户
-   用户名管理
-   登录凭据
-   账户状态
-   身份验证
-   会话管理
-   密码重置
-   邮箱验证
-   登录安全事件
-   用户账户生命周期

### 13.2 已提出的候选实体

以下是候选表名，必须与历史 Registry 去重后才能正式冻结：

-   `users`
-   `user_accounts`
-   `user_credentials`
-   `user_username_history`
-   `user_email_addresses`
-   `user_sessions`
-   `user_verification_tokens`
-   `user_password_reset_requests`
-   `admin_audit_logs`（其模块归属已确认是 K002）

### 13.3 已确定规则

-   `users` 表示稳定身份主体。
-   Username 可变，User ID 不变。
-   凭据与身份主体分离。
-   不保存明文密码或可逆密码加密。
-   Session 只保存 Token Hash。
-   用户账户关闭不级联删除教学资料。
-   用户名历史保留。
-   邮箱验证后才能按策略用于验证身份或通知。
-   `admin_audit_logs` 与 K021 的安全事件分离。

### 13.4 关键 TODO

-   [ ] 恢复历史 Identity 表名和完整字段。
-   [ ] 恢复用户用户名规则方案 B 的精确参数。
-   [ ] 冻结 Username 字符集、长度、规范化、保留字和变更限制。
-   [ ] 确定邮箱唯一性与多邮箱策略。
-   [ ] 设计登录限速、凭据轮换、账户恢复和会话撤销策略。
-   [ ] 完成 MFA 是否进入 MVP 的决策。
-   [ ] 完成个人数据导出和账户删除 Workflow。
-   [ ] 与 K021 管理员身份关系核对。

## 14. K009 — Knowledge Base

### 14.1 定位

知识库负责资料来源管理、版本、解析、审核、索引、检索和引用。**2026-11-04 起分为两层**：

| 层 | 归属 | 内容 | 权利默认值 |
| --- | --- | --- | --- |
| 平台知识库 `scope = platform` | 项目方提供，不属于任何教师 | 默认四个分类：人教版数学教材、辅导书、高考题、模拟题 | `licensed`（平台授权） |
| 教师知识库 `scope = teacher` | 教师私有，按 Owner 隔离 | 教师自行上传，可沿用默认分类，也可新建分类 | `unverified`（需教师确认） |

两层共同构成检索范围。Agent 检索时合并两层，但按 `scope` 分别处理权利与可见性。

#### 14.1.1 分层规则

1. `knowledge_sources` 增加 `scope`（`platform` / `teacher`）。平台来源没有 `owner_id`，教师来源必须有。
2. 分类由 `knowledge_categories` 表达，**不使用数据库 ENUM**，否则教师无法新建分类。四个默认分类映射到 `source_type`：人教版数学教材 → `textbook`、辅导书 → `workbook`、高考题 → `gaokao_paper`、模拟题 → `mock_exam`。
3. 平台来源的权利按平台授权固定，教师不能改写；教师来源默认 `unverified`，须教师确认后才能发布或导出（G6/G7）。
4. 教师不能修改平台来源的解析结果、分类或版本；需要修正时复制为教师来源，用 `derived_from_source_id` 保留出处。
5. **默认教材**：教师未指定教材时，使用平台知识库的「人教版数学教材」作为知识依据来源。
6. 平台来源更新（例如新版教材入库）不改变已发布 Material Version 的 Citation Snapshot，只影响后续检索。

#### 14.1.2 平台资料权利策略（已确认 A 档）

**2026-11-04 法务确认结果：A 档。**

| 确认项 | 结论 |
| --- | --- |
| 四类资料的数字复制权 | 已取得 |
| 摘录原文 | 允许 |
| 改编 | 允许 |
| 分发给学生（课堂或家庭） | 允许 |
| 与教师自有资料混排 | 可以 |
| 撤回时清除已发布摘录 | 非必须 |

因此 `platform_rights_policy = A_classroom`：平台来源 `rights.status = licensed`、`distribution_scope = classroom`，**教师版与学生版均可包含平台来源节点**。四类平台资料构成的知识库因此可以独立支撑黄金路径，不依赖教师上传。

**策略仍保留三档**（不改代码、只改配置），因为未来新增来源类型或更换授权时可能需要降档：

| 档 | 含义 | 摘录原文 | 改编 | 学生版导出 |
| --- | --- | --- | --- | --- |
| `A_classroom` | 平台已获授权，可课堂分发（当前生效） | 允许 | 允许 | **允许** |
| `B_private_excerpt` | 仅限教师个人备课，可摘录不可改编 | 允许 | 禁止 | **阻断**（引用平台来源的节点） |
| `C_private_adapt` | 仅限教师个人备课，可改编不可分发 | 允许 | 允许 | **阻断**（同上） |

**这三种档位对产品的影响不对称：**

- 档 A：黄金路径完整成立，学生版可包含平台来源的题目。
- 档 B/C：学生版**不能引用任何平台来源的节点**。此时学生版只能由教师自有资料 + AI 自编题构成，而平台题库的价值退化为“教师备课时的参考”。

这不是一个开关级别的差异——**档 A 是学生版成立的前提**。若最终落 B 或 C，学生版的定位需要重新设计（例如：学生版只保留教师自有资料与不基于平台原文的 AI 自编题），并同步修改 D1 的 G7 与 §1.6 的黄金路径。

**要法务确认的六个问题**（可逐条回答，不必看这份文档）：

1. 平台是否已获得四类资料的数字复制权？分别取得哪些？
2. 是否允许在生成的教学材料中**摘录原文**（而非仅作检索参考）？
3. 是否允许对原文**改编**后使用？
4. 是否允许将含平台资料的材料**分发给学生**（课堂或家庭）？
5. 平台资料能否与教师自有资料**混排**在同一份材料中？
6. 来源撤回时，已发布材料中的摘录是否必须删除（影响是否要生成 Redacted Version）？

**对撤回语义的影响**：第 6 项确认“非必须清除”，因此平台来源撤回时**不触发强制 Redacted Version**。已发布材料保留摘录与 Citation Tombstone，只阻止基于该来源的新引用与后续新版本使用。§21.1.5 规则 5 的 Redacted 路径保留但不再是默认动作。


### 14.2 核心候选表

原九张表，加题目级单元与分类后共十三张：

| # | 表 | 职责 | 状态 |
| --- | --- | --- | --- |
| 1 | `knowledge_sources` | 来源身份与归属（`scope` = platform / teacher） | 扩展 |
| 2 | `knowledge_document_versions` | 文件版本、解析版本、审核状态 | 原有 |
| 3 | `knowledge_chunks` | 文本块，Citation 的定位单元 | 原有 |
| 4 | `knowledge_questions` | **题目单元**：试卷切分产物，检索与引用的最小单位 | **新增** |
| 5 | `knowledge_categories` | 分类（四个默认 + 教师私有分类），替代 ENUM | **新增** |
| 6 | `knowledge_annotations` | 派生标注：题型、知识点、难度；带 `classification_source` 与版本 | **新增** |
| 7 | `knowledge_question_embeddings` | 向量，派生数据，可随时重建 | **新增** |
| 8 | `knowledge_ingestion_runs` | 上传、扫描、解析、切分、分类的执行记录 | 扩展 |
| 9 | `knowledge_reviews` | 教师审核（含切分校对） | 扩展 |
| 10 | `knowledge_indexing_jobs` | 索引任务 | 原有 |
| 11 | `knowledge_retrieval_runs` | 检索运行 | 原有 |
| 12 | `knowledge_retrieval_results` | 检索结果 | 原有 |
| 13 | `material_knowledge_citations` | 已发布内容的引用投影 | 原有 |

`knowledge_questions` 的存在理由：G2 要回答“平台库里有多少道数列解答题”，必须按**题**计数，而不是按文档计数。

最终实体归属需与历史 K001 等模块去重；`material_knowledge_citations` 建议由 K009 物理拥有，K012 提供 Material 关系。

字段级设计见模块分册 [K09 知识库字段级设计](design/Chilon_Design_Volume_K09_Knowledge_Field_Design.md)：13 张表的字段、约束、索引、RLS 要点与迁移顺序。


### 14.3 生命周期

``` text
Upload（整张试卷 / 整本教材，文件级）
  -> Security Scan
  -> Parse / OCR
  -> Extract
  -> Segment（试卷切分为题目单元）
  -> Chunk
  -> Classify（题型与知识点标注，派生数据）
  -> Teacher Review（核对切分与标注）
  -> Approve
  -> Index（关键词 + 元数据；向量为派生数据）
  -> Search
  -> Cite
```

**上传单元是文件（整张试卷），引用单元是题目。** 这两者不能混——教师按试卷上传，Agent 按题目检索和引用。

### 14.4 核心规则

-   上传不等于正式入库。
-   解析完成不等于审核通过。
-   检索到不等于可以正式引用。
-   只有已审核、已索引、未撤回的版本可以正式检索。
-   新版本不继承旧版本审核。
-   Citation 固定 Document Version、Chunk、Retrieval Run/Result 和源位置。
-   文件二进制保存在私有 Object Storage。
-   DB 保存 storage_key、checksum、mime、size 等元数据。
-   解析器运行于受限环境，不执行宏、脚本或嵌入程序。
-   提示词注入不能改变 Agent 权限。
-   MVP 使用关键词与元数据检索；中文 tokenizer 需评估。
-   **向量检索不作为 MVP 主路径**；embedding 作为派生数据存储，用于题型分类辅助与后续检索升级。
-   Owner Filter 必须在排序前生效。

#### 14.4.1 题目级切分

-   一张试卷切分为若干题目单元，每题记录：题号、卷面题型（选择/填空/解答）、分值、题干范围、答案与解析位置。
-   题目切分结果必须可人工校对：合并、拆分、改题号，全部留痕。
-   跨页题允许一个题目单元对应多个原文区段；Citation 定位必须能覆盖全部区段。
-   切分错误的后果比解析错误更严重：后续标注、检索、引用都建立在这上面。

#### 14.4.2 派生标注与原文事实的边界

知识库里的字段分两类，**不能混用**：

| 类别 | 例子 | 能否被教师改 | 能否作为引用证据 |
| --- | --- | --- | --- |
| 原文事实 | 题干文本、题号、页码、字符区间、文件 Hash | 否（只能重新解析） | **是** |
| 派生标注 | 题型、知识点、难度、embedding 向量、聚类分组 | 是，且可多版本并存 | **否** |

-   Citation 只能引用原文事实。`provenance` 与 Citation Snapshot 中不得出现“题型由模型判定”作为来源依据。
-   派生标注带 `classification_source ∈ {rule, model, teacher}` 与版本号；教师修正后，原标注保留为历史，不覆盖。
-   题型分类优先用卷面规则（如“第 I 卷选择题”“第 II 卷解答题”），模型只在规则无法判定时兜底。
-   embedding 与向量索引属于派生数据，重建不影响已发布 Material Version 的 Citation。

#### 14.4.3 卷面题型：只存一层

**2026-11-04 决定**：题型分类只存**卷面题型**一层，不存内容题型（计算/证明/应用）。

| `paper_question_type` | 含义 | 卷面识别方式 |
| --- | --- | --- |
| `single_choice` | 单选题 | 选择题区，四个选项，唯一正确 |
| `multiple_choice` | 多选题 | 新高考选择题区，四个选项，正确项 ≥ 2 |
| `fill_blank` | 填空题 | 填空题区，无选项，有空格 |
| `free_response` | 解答题 | 解答题区，无选项，需写出过程 |

**为什么是四类而不是三类**：新高考数学卷面区分单选与多选（如第 1–8 题单选、第 9–12 题多选），只存“选择题”无法还原原卷结构，也会让 `single_choice` / `multiple_choice` 的 AST 校验失去依据。

**为什么不存内容题型**：教师口语里的“大题”“选择题”指的是卷面结构，不是解题方法。内容题型（计算/证明/应用）由生成器在写入 AST 时按题目内容判定，属于生成期判断，不进入知识库标注层。

**与 AST 的映射**由 §20.9 规则 19 约束：卷面题型限定 `question_type` 的取值范围，并决定 `options` 是否必须存在。


#### 14.4.3 分类与层级

-   分类来自 `knowledge_categories`，四个默认分类由平台层提供：人教版数学教材、辅导书、高考题、模拟题。
-   教师新增的分类**默认私有**，仅该教师可见；平台分类全局可见。
-   分类是检索过滤维度，不改变来源事实；一个来源可属于一个分类，题目可带多个知识点标签。


### 14.5 TODO

-   [ ] 与 K001 历史知识实体去重。
-   [ ] 冻结十三张表的唯一归属。
-   [ ] 解决同一 Document Version 多次解析产生 Chunk 唯一键冲突的问题。
-   [ ] 明确 OCR、公式和表格解析产物 Schema。
-   [ ] 评估中文全文检索 tokenizer。
-   [x] 定义文档撤回、删除和历史引用保留策略。详见 [21.1.5](#2115-来源生命周期与撤回)。
-   [ ] 实现文件安全扫描、隔离区和解析沙箱。
-   [ ] 实现正式检索索引和检索质量评估。
-   [ ] 实现引用来源可视化。
-   [ ] 冻结试卷切分规则与人工校对交互（合并/拆分/改题号）。
-   [ ] 明确跨页题的多段定位模型（`locator` 需支持多段区间）。
-   [x] 冻结题型分类体系：只存卷面题型四类（单选/多选/填空/解答），与 AST `question_type` 的相容规则见 §20.9 规则 19、§14.4.3。
-   [ ] 定义 `classification_source` 与标注版本规则；教师修正如何留痕。
-   [ ] 评估 embedding 模型选型、维度与重建成本；确定向量是否只用于分类。
-   [ ] 定义平台知识库首批内容清单与覆盖率指标（直接决定 G2 的 `capability_gap` 频率）。


## 15. K011 — Task & Agent Orchestration

### 15.1 职责

-   Task Management
-   Requirement Versioning
-   Agent Planning
-   Plan Approval
-   Step Orchestration
-   Execution Management
-   Runtime Integration
-   Tool Execution
-   Outbox Event Delivery

### 15.2 已明确的表

1.  `tasks`
2.  `task_requirement_versions`
3.  `agent_plans`
4.  `agent_plan_versions`
5.  `agent_plan_approvals`
6.  `agent_plan_steps`
7.  `agent_step_dependencies`
8.  `agent_step_executions`
9.  `agent_executions`
10. `agent_runs`
11. `agent_runtime_events`
12. `agent_execution_events`
13. `agent_tool_definitions`
14. `agent_tool_executions`
15. `outbox_events`

历史设计约有 35 张表，其余实体尚未完整恢复。

### 15.3 核心规则

-   Task、Requirement Version、Plan、Plan Version、Approval、Execution 分离。
-   Plan Approval 绑定具体 Plan Version 和 Hash。
-   执行前重新验证审批与 Hash。
-   Execution 与 Agent Run 分离。
-   Harness Runtime Events 与 Chilon Business Execution Events 分离。
-   Tool Registry 的业务权威归 Chilon。
-   每次 Tool Call 都要通过 Identity、Owner、Scope、Capability、Business Approval Gate。
-   工具参数中的 owner_id/project_id 不可信。
-   Tool Result 必须经过业务验证。
-   超时不能直接认定执行失败；应先查询实际状态。
-   Outbox 与业务状态更新在同一事务。
-   消费语义为 At-least-once，Consumer 必须幂等。

### 15.4 工具目录初稿

-   `knowledge.search`
-   `knowledge.get_source`
-   `knowledge.preview`
-   `math.parse`
-   `math.validate`
-   `math.test_examples`
-   `template.select`
-   `content.generate`
-   `content.revise`
-   `quality.check`
-   `quality.get_issues`
-   `material.create_draft`
-   `material.publish`（受审批保护，MVP 不要求 Agent 自动执行）
-   `material.get_version`
-   `export.create`（后续启用）

### 15.5 候选实体（待合并审查）

-   `agent_tool_versions`
-   `agent_tool_grants`
-   `agent_tool_execution_events`
-   `agent_runtime_plugins`
-   `agent_tool_plugin_bindings`

不能在 Registry 完成去重前视为正式表。

**2026-11-04 去重结论（见 D.27）：** `agent_tool_versions` 与 `agent_tool_plugin_bindings` 落为`agent_tool_definitions` 上的列；`agent_tool_grants` 与 `agent_runtime_plugins` 各自成为独立表；`agent_tool_execution_events` 不单独建表，由 `agent_execution_events` 按 `aggregate_type` 承载。

### 15.6 TODO

-   [x] 用 §15.2 的 15 张已知表 + 契约推导替代“恢复 35 张清单”（2026-11-04，见 D.27）。
-   [x] 补全所有表字段字典：17 张表已入 Registry（2026-11-04）。
-   [x] 确定 Tool Version / Grant / Plugin 的归属：Version 与 Plugin Binding 落为列，Grant 与 Plugin 各建一表（见 D.27）。
-   [x] 冻结 Lease / Heartbeat / Fencing Token：字段落在 `agent_executions`（见 D.27）。
-   [x] `outbox_events` 字段冻结；物理归 K011、逻辑为跨模块共享设施（见 D.27）。
-   [ ] 明确 Plan Step DAG 的环检测和调度规则。
-   [x] 设计暂停、取消、重试、恢复和超时状态机。详见 [21.6](#216-executionrunstep-与-tool-状态机)。
-   [ ] 设计 Runtime Session 与业务 Execution 的恢复映射。
-   [ ] 完成并发 Worker 与幂等测试。

## 16. K012 — Project & Material Management

### 16.1 核心实体

MVP 启用：

1. `projects`
2. `materials`
3. `material_versions`
4. `material_drafts`
5. `material_draft_revisions`
6. `material_references`
7. `task_material_links`
8. `material_publication_approvals`
9. `material_exports`

暂缓： - `material_project_links` - `document_schema_definitions`（实体归属未定） - `material_knowledge_citations` 与 K009 一起启用

### 16.2 Project

-   一个 Project 表示一个教学专题。
-   Project 有唯一 Owner。
-   Project 归档不自动归档其 Material。
-   Project 删除走专门 Workflow，不级联删除材料。

### 16.3 Material 归属

-   `materials.primary_project_id IS NULL` 表示 Personal Library。
-   非 NULL 表示 Project-owned。
-   一个 Material 只有一个主归属。
-   相关关系不改变主归属，也不自动授予权限。

### 16.4 Material Version

-   Version 不可变。
-   修改创建新 Version。
-   恢复旧版本也创建新版本。
-   Version 保存 Document Schema Version、Document Content、Content Hash、Change Summary 和来源。
-   创建 Version 与更新 current pointer 在同一事务。
-   普通 App Role 不允许 UPDATE/DELETE 正式版本。

### 16.5 Draft

-   Draft 保存 `base_version_id`。
-   多个 Draft 可并存。
-   使用 `current_revision_id`、`current_revision_no`、`current_content_hash`和乐观锁。
-   每次有效保存创建不可变 `material_draft_revisions` 记录。
-   接受 Draft 前检查 Base Version 是否变化。
-   直接编辑和 Chat Revision 都使用 `If-Match`/`expected_revision_no`，冲突时不能静默覆盖。
-   检查、审批和发布都绑定具体 Revision 与 Content Hash。
-   发布时从已批准的 Draft Revision 创建不可变 Material Version；Draft 不能直接成为正式版本。

### 16.6 References 与 Task Links

-   `material_references` 支持 `latest` 与 `pinned`。
-   `pinned` 必须固定目标版本。
-   跨 Project 引用默认只读。
-   `task_material_links` 必须引用具体 Material Version。

### 16.7 Export

-   Export 固定 Material Version、Document Schema、Profile、Renderer、Options Hash。
-   文件存 Object Storage。
-   DB 保存 storage_key 和导出状态。
-   Worksheet Student Profile 从 AST 删除答案和解析。

### 16.8 TODO

-   [ ] 核对历史 K012 完整表清单。
-   [ ] 冻结字段类型和所有 FK。
-   [ ] 确认 `cover_storage_key` 等候选字段是否纳入。
-   [x] 冻结 Document Schema Registry 的实体归属为 K012 `document_schema_definitions`。
-   [x] 完成发布审批实体与 K014 Quality Gate 的关系设计。详见 [21.9](#219-publication-approval-与发布事务状态机)。
-   [ ] 实现 Draft 并发编辑冲突处理。
-   [ ] 实现版本发布事务和幂等恢复。
-   [ ] 实现 DOCX/PDF Renderer。
-   [ ] 完成导出文件访问控制和过期清理。

## 17. K013 — Conversation & Activity

### 17.1 核心实体

1.  `conversations`
2.  `conversation_messages`
3.  `conversation_events`
4.  `agent_activities`
5.  `conversation_attachments`
6.  `conversation_participants`
7.  `conversation_cursors`
8.  `conversation_message_revisions`（扩展候选，非 MVP）

### 17.2 概念边界

-   Conversation：交流上下文。
-   Message：教师和 Agent 可见消息。
-   Event：追加式事件流。
-   Activity：教师可理解的任务进度。
-   Task：业务目标。
-   Execution：实际执行实例。
-   Harness Session Log：Runtime 内部执行记录。

不能将这些实体合并。

### 17.3 Message

-   Role：`user`、`assistant`、`system`。
-   工具调用不是教师可见 Message Role。
-   Content 使用版本化 JSON Blocks。
-   支持 text、math、exercise、answer、explanation、material_reference、knowledge_citation、approval_request、activity_summary、error 等内容块。
-   状态：`streaming`、`completed`、`interrupted`、`failed`。
-   流式增量由 Redis 临时缓冲。
-   需要持久化 streaming Message 和恢复检查点。
-   完成或中断后写入 PostgreSQL。

### 17.4 Event 与 SSE

-   Conversation Event Append-only。
-   Event Sequence 在事务内原子递增。
-   Event 与 Outbox 同事务。
-   SSE Last-Event-ID 使用 Event Sequence。
-   PostgreSQL Event Log 是事实来源。
-   Redis Pub/Sub 只负责通知。
-   订阅先建立并记录高水位，再回放至高水位，再消费实时通知并去重。
-   定期对账补漏。

### 17.5 Activity

-   可更新，不是 Append-only Event。
-   展示教师可理解的进度。
-   不记录 Token。
-   不暴露模型内部推理。

### 17.6 TODO

-   [x] 核对 K013 字段：7 张表已入 Registry，`conversation_message_revisions` 判定为非 MVP（2026-11-04，见 D.28）。
-   [ ] 完成 Message Content JSON Schema。
-   [ ] 完成流式检查点和中断恢复设计。
-   [ ] 完成 Sequence 并发和 SSE 无遗漏测试。
-   [ ] 完成 Event 保留与分区策略。
-   [ ] 完成附件扫描和下载授权。
-   [ ] MVP 不开放多人共享；未来再评估 Participants。
-   [ ] 明确 Message 与 Task 的创建、绑定和解除规则。

## 18. K014 — Quality & Evaluation

### 18.1 24 张核心表

1.  `quality_rules`
2.  `quality_rule_versions`
3.  `quality_check_runs`
4.  `quality_check_rule_snapshots`
5.  `quality_check_results`
6.  `quality_issues`
7.  `quality_evidence`
8.  `math_validation_runs`
9.  `math_validation_evidence`
10. `quality_issue_feedback`
11. `quality_issue_resolutions`
12. `quality_datasets`
13. `quality_dataset_versions`
14. `quality_dataset_items`
15. `quality_evaluations`
16. `quality_evaluation_runs`
17. `quality_evaluation_results`
18. `quality_metrics`
19. `quality_metric_observations`
20. `quality_alerts`
21. `quality_alert_events`
22. `quality_releases`
23. `quality_release_approvals`
24. `quality_release_events`

### 18.2 质量检查规则

-   Rule Version 不可变。
-   Check Run 固定 Rule Snapshot。
-   Check 固定被检查的 Material Version 或 Draft 快照。
-   结果状态：`passed`、`failed`、`warning`、`not_applicable`、`inconclusive`。
-   `inconclusive` 不等于 `passed`。
-   Issue Severity：S0/S1/S2/S3。
-   S0 阻止发布。
-   S1 默认阻止，例外需要教师明确确认并记录理由。
-   S2 由教师决定。
-   S3 不阻止发布。
-   Evidence 必须追溯真实执行过程，不能仅保存 LLM 声称“验证通过”的文本。

### 18.3 数学验证

五层： 1. Formula Validation 2. Symbolic Validation 3. Numerical Validation 4. Solution Validation 5. Cross-material Validation

关键原则： - 数值样例通过不能证明恒等式。 - Symbolic Validation 必须考虑定义域和前提。 - LLM 不能单独证明复杂数学结论。 - SymPy 在独立 Validator Service 中运行。 - 采用受限 AST，不执行任意 Python。 - 状态：`validated`、`failed`、`inconclusive`、`unsupported`。

### 18.4 Evaluation 与 Release

Evaluation 固定： - Dataset Version - Model - Prompt - Harness - Plugin Manifest - Tool Registry - Validator Version

Dataset Version 不可变。样本不足时结果为 `inconclusive`。

Release 固定 Application、Model、Prompt、Harness、Plugin、Tool Registry、Validator 等版本和 Hash。

流程： Offline Evaluation → Quality Gate → Canary → Production Approval
→ Monitoring → Rollback。

回滚不得删除教师已经正式批准的 Material Version。

### 18.5 TODO

-   [x] 完成 24 张表字段级 Registry（2026-11-04，见 D.26）。
-   [ ] 确定系统级和教师级数据的精确隔离。
-   [x] 冻结 Draft 与 Material Version 的 Check Target 表达。详见 [21.8](#218-质量检查与数学验证状态机)。
-   [ ] 完成 Issue、Evidence、Resolution 的关系约束。
-   [ ] 完成数学验证证据结构和 Validator 版本追踪。
-   [ ] 建立高考数学测试集及数据治理流程。
-   [ ] 建立模型/Prompt/Harness 回归评估。
-   [ ] 定义 Release Gate 的量化阈值。
-   [ ] 实现告警、Canary、审批和回滚工具链。

## 19. K021 — Administrative Security

### 19.1 已知实体

-   `admin_security_events`
-   `admin_operation_requests`
-   `admin_operation_approvals`
-   `admin_operation_executions`

`admin_audit_logs` 属 K002。

### 19.2 核心规则

-   高风险管理员操作：申请 → 审批 → 执行。
-   审批绑定 `request_version` 和 `parameters_hash`。
-   申请人不能批准自己的申请。
-   MVP 双人职责分离。
-   执行前重新验证审批、Hash 和执行权限。
-   超时结果未知时先查询目标状态，不能盲目重试。
-   短期授权需限定 Scope、Capability、时间窗和撤销状态。
-   紧急安全隔离可以按预授权缩短审批，但必须审计。
-   Admin 不允许无条件绕过 RLS。
-   操作目标属于教师资源时，单独记录 `target_owner_id`。
-   审批策略版本化；旧申请不能被新策略静默改变。

### 19.3 TODO

-   [x] 核对 K021 表清单：4 张，与 §19.1 一致（2026-11-04，见 D.28）。
-   [ ] 与 K002 Identity 恢复后的管理员身份表建立 FK（**阻塞于 K002 未恢复**；当前 `actor_id` 等为无外键 uuid，见 D.28）。
-   [x] 冻结 K021 每张表的字段、约束和 RLS（2026-11-04）。
-   [ ] 定义管理员权限矩阵。
-   [ ] 定义紧急操作预授权范围和事后审查 SLA。
-   [ ] 实现不可抵赖的审批与执行审计。
-   [ ] 完成管理操作幂等和未知结果恢复测试。

------------------------------------------------------------------------

# 第六部分：文档模型与端到端工作流

## 20. Structured Teaching Document Model

### 20.1 统一模型

Lesson、Exercises、Worksheet 采用统一 Structured Document Model + Versioned JSON Schema。

-   JSONB 存储结构化文档。
-   AST 是编辑、生成、验证和导出的统一模型。
-   每个节点有稳定 UUID。
-   文档结构有明确 Schema Version。
-   正式 Material Version 固定 Schema Version。
-   历史正式版本不静默迁移。

### 20.2 Lesson 结构

-   Overview
-   Learning Objectives
-   Prerequisites
-   Key Concepts
-   Definitions
-   Theorems & Properties
-   Formula Summary
-   Teaching Methods
-   Worked Examples
-   Common Mistakes
-   Knowledge Connections
-   Summary

### 20.3 Exercises 结构

题型： - `single_choice` - `multiple_choice` - `fill_blank` - `short_answer` - `calculation` - `proof` - `application`

难度： - `basic` - `medium` - `advanced` - `challenge`

高考能力维度： - `knowledge_understanding` - `logical_reasoning` - `mathematical_operation` - `data_analysis` - `modeling` - `problem_transfer`

答案和解析通过稳定 ID 与题目关联。

### 20.4 Worksheet 结构

-   知识摘要
-   公式
-   例题
-   练习
-   学生作答空间
-   Teacher / Student Profile

### 20.5 数学公式

Formula Node 保存： - LaTeX - display_mode - alt_text

安全渲染；不允许任意 Python 执行或 HTML/JS 注入。

### 20.6 编辑器

-   支持结构化块编辑。
-   支持 AI Chat Revision。
-   两者修改同一 Draft。
-   使用乐观锁和 expected_version。
-   冲突时显式处理，不静默覆盖。

### 20.7 Teaching Document Schema v1 正式契约

**状态：DESIGNED / FROZEN FOR IMPLEMENTATION**

Teaching Document 的机器可读契约：

-   [teaching_document.v1.schema.json](schemas/teaching_document.v1.schema.json)
-   [source_citation.v1.schema.json](schemas/source_citation.v1.schema.json)
-   [trigonometry_golden_path.v1.example.json](schemas/trigonometry_golden_path.v1.example.json)

契约标识：

-   Schema ID：`chilon.teaching_document`
-   Schema Version：`1.0.0`
-   JSON Schema：Draft 2020-12
-   Citation Schema ID：`chilon.source_citation`

顶层文档固定包含：

-   `schema`、`schema_version`、`document_id`。
-   `document_kind`：`lesson`、`exercise_set`、`worksheet` 或 `mixed`。
-   `metadata`：标题、学科、年级、课程体系、语言和专题。
-   `citations`：本文档 Revision 自包含的 Citation Snapshot。
-   `blocks`：结构化教学内容 AST。

基准场景“讲义 + 教辅例题 + 高考真题 + 近期模拟题”使用 `document_kind = mixed`，可以在同一 Material Document 中包含讲义区和练习区。

### 20.8 AST 节点注册表

所有块节点固定包含：

-   `id`：UUID 稳定节点 ID。
-   `type`：本版本允许的节点类型。
-   `visibility`：`student`、`teacher` 或 `internal`。
-   `provenance`：内容来源、引用和改编说明。

Schema v1 节点：

| 节点类型 | 用途 | 关键字段 |
| --- | --- | --- |
| `section` | 讲义或练习章节 | `purpose`、`title`、`children` |
| `heading` | 章节标题 | `level`、`content` |
| `paragraph` | 普通段落 | `content` |
| `list` / `list_item` | 有序或无序列表 | `ordered`、`items`、`content` |
| `formula` | 独立数学公式 | `latex`、`display_mode`、`alt_text` |
| `table` | 结构化表格 | `columns`、`rows`、`caption` |
| `definition` | 数学定义 | `term`、`statement`、`conditions` |
| `theorem` | 定理、性质、引理或推论 | `theorem_kind`、`assumptions`、`conclusion`、`proof` |
| `worked_example` | 教辅或自定义例题 | `problem`、`children`、答案/解析节点 ID |
| `solution_step` | 解题步骤 | `instruction`、`children` |
| `exercise_group` | 同难度或同来源题组 | `title`、`difficulty`、`children` |
| `exercise` | 单道题目 | 题型、难度、能力维度、题干、选项、答案/解析节点 ID |
| `answer` | 答案 | `content` |
| `solution` | 解析 | `content`、`children` |
| `hint` | 学生提示 | `content` |
| `worksheet_response` | 作答区域 | `response_type`、`min_lines`、`min_height_mm` |
| `callout` | 提示、易错点或警告 | `variant`、`children` |
| `image` | 图片资产 | `asset_id`、`alt_text`、`caption` |
| `page_break` | 明确分页 | 无扩展字段 |

行内内容只允许：

-   `text`：纯文本及受控标记。
-   `math`：LaTeX 与必需的无障碍替代文本。
-   `citation_ref`：通过 `citation_id` 指向本文档 Citation Snapshot。
-   `line_break`。

禁止在 AST 中存储 HTML、JavaScript、任意富文本 HTML、外部脚本或可由文档执行的代码。

### 20.9 AST 语义与引用完整性规则

以下约束由 Document Validator 执行，不能只依赖 JSON Schema：

1.  `document_id`、所有块节点 ID、表格列 ID、选项 ID 在文档内唯一。
2.  稳定 ID 一经创建不得复用；移动节点保持 ID，复制节点生成新 ID，删除节点后其 ID 不重新分配。
3.  `exercise.answer_node_ids` 必须指向其后代 `answer` 节点；`solution_node_ids` 必须指向其后代 `solution` 或 `solution_step` 节点。
4.  选择题必须有至少两个选项；答案节点必须与题型及选项规则一致。
5.  `answer`、`solution` 和教师备注不得使用 `student` 可见性。
6.  `citations` 中的 `citation_id` 唯一；所有 `provenance.citation_ids` 和 `citation_ref` 必须能找到对应 Citation Snapshot。
7.  每个 Citation Snapshot 至少被一个节点使用；无使用者的 Citation 视为无效。
8.  `textbook_example` / `workbook_example` 只能使用 `verbatim` 或 `excerpt` basis，并至少绑定一个对应来源（`textbook` / `workbook`）。
9.  `gaokao_question` / `mock_question` 只能使用 `verbatim` 或 `excerpt` basis，并至少绑定一个对应来源（`gaokao_paper` / `mock_exam`）。
10. `adapted` 必须绑定来源和 `change_note`；不能把改编题伪装成教材、教辅、高考或模拟原题。
11. 表格每行 `cells` 数量必须与 `columns` 数量匹配，并校验合并单元格导致的列跨度。
12. 图片必须引用当前 Material 可用资产，不能存储任意外链作为正式内容来源。
13. 公式 LaTeX 必须通过 Renderer 的命令白名单和复杂度限制；禁止 HTML、文件读取、网络访问和任意代码执行命令。
14. `list_item` 只能位于 `list.items`；`answer`、`solution`、`solution_step` 和 `hint` 只能位于合法题目或例题容器中。
15. `exercise_set` 必须至少包含一道 `exercise`，`worksheet` 必须至少包含一个 `worksheet_response`；空内容不得发布。
16. Citation 的定位必须自洽（新增于 D.15）：
    - 单段：`char_end` 大于 `char_start`，`page_number` 与 Locator 类型匹配。
    - 跨段：`segments` 至少 2 段，每段 `char_end` 大于 `char_start`；`locator_kind = pdf_text` 时每段必须有 `page_number`。
    - 两种形式至少提供一种；跨页题（题干与选项不在同一页）必须使用 `segments`。
17. Citation 的 `usage.rights` 必须满足目标导出 Profile；`excerpt_hash` 必须与 `excerpt.text` 的 Hash 一致。
18. `section.purpose` 必须与直接子节点类型一致（新增于 D1）：
    - `worked_examples` 至少包含一个 `worked_example`。
    - `exercises` 至少包含一个 `exercise` 或 `exercise_group`。
    - `worksheet` 至少包含一个 `worksheet_response`。
    - `overview`、`learning_objectives`、`prerequisites`、`key_concepts`、`definitions`、`theorems`、`formula_summary`、`teaching_methods`、`common_mistakes`、`knowledge_connections`、`summary` 不得只包含题目或例题节点。
19. 题目来源的**卷面题型**必须与 AST 的 `question_type` 相容（新增于 D.14）：
    - `single_choice` → 只能是 `single_choice`
    - `multiple_choice` → 只能是 `multiple_choice`
    - `fill_blank` → 只能是 `fill_blank`
    - `free_response` → `short_answer` / `calculation` / `proof` / `application` 之一
    - 卷面题型为选择题时必须存在 `options`；为填空题或解答题时不得出现 `options`。

### 20.10 Teacher / Student / Internal 投影

导出和预览必须从 AST 执行确定性的 Profile 投影，不允许仅用 CSS 隐藏内容：

| Profile | 包含的 visibility | 排除内容 | 主要用途 |
| --- | --- | --- | --- |
| `teacher` | `student`、`teacher` | `internal` | 教师备课、教师版导出、质量审核 |
| `student` | `student` | `teacher`、`internal` 以及全部答案、解析和教师备注 | 学生讲义、Worksheet、学生版导出 |
| `internal` | `student`、`teacher`、`internal` | 不导出文件 | 编辑、诊断和质量检查 |

Student 投影必须满足：

-   答案、解析、教师备注和内部验证证据均不进入 Renderer 输入。
-   Citation 的展示遵循来源权利策略；若要求署名，保留最小 Attribution 文本。
-   数学公式同时携带 `alt_text`。
-   投影结果计算独立 Hash，并在 Export 中固定。

### 20.11 Canonicalization、Hash 与 Schema 演进

-   JSON 规范化使用 RFC 8785 JSON Canonicalization Scheme。
-   `content_hash = "sha256:" + SHA-256(canonical_json(teaching_document))`。
-   Hash 包含节点 ID、可见性、来源和 Citation Snapshot；因此移动、删除、答案变化或来源变化都会产生新 Hash。
-   Schema 小版本只能增加可选字段或节点；改变必填字段、字段语义或已发布节点结构必须创建新的 Major Schema。
-   已发布 Material Version 固定原始 Schema Version 和文档内容，永不原地迁移。
-   读取旧版本时由兼容 Reader 转换为内部表示；导出仍固定使用原版本或明确的 Schema 迁移记录。
-   未知 Schema Version 默认拒绝发布和导出，不能由客户端声明“兼容”。
-   `restore` 恢复旧内容时生成新 Document/Revision Hash，不改变历史 Revision。

## 21. K009 → K012 → K014 端到端内容链路

``` text
Teacher Uploads Source
        |
Security Scan / Parse / OCR
        |
Teacher Review & Approval
        |
Knowledge Index
        |
Retrieval Run + Evidence
        |
Draft Generation
        |
Draft Citation Anchors
        |
Quality & Math Check
        |
Teacher Review / Approval
        |
Publish Immutable Material Version
        |
Persist Material Citations
        |
DOCX / PDF Export
```

### 21.1 Citation

Draft 阶段可在文档结构中保存 Citation Anchor，使用稳定 `content_node_id`。正式发布时固化到 `material_knowledge_citations`。

引用关系的两个层次：

-   Draft 阶段：AST 节点通过 `citation_id` 引用同一 Draft Revision 内的 Citation Snapshot；此时绑定 Draft Revision、Content Node、Source Version、Chunk、Retrieval Run/Result、原文位置和 Excerpt。
-   发布阶段：将引用关系投影到 `material_knowledge_citations`，绑定 Material Version、Content Node 和不可变 Citation ID/Snapshot。

不能在 Draft 阶段要求一个尚不存在的 Material Version ID；发布事务负责完成 Draft Revision 到 Material Version 的固定映射。

#### 21.1.1 Source / Citation Contract v1

**状态：DESIGNED / FROZEN FOR IMPLEMENTATION**

Citation Snapshot 使用 [source_citation.v1.schema.json](schemas/source_citation.v1.schema.json)，作为 `teaching_document.citations[]` 的一部分嵌入 Draft Revision 和 Material Version。这样 Citation 与文档内容一起参与 Content Hash，避免发表后来源变化导致证据漂移。

每个 Citation Snapshot 固定：

| 区块 | 必需内容 | 用途 |
| --- | --- | --- |
| 身份 | `citation_id`、Schema Version | AST 节点和 Citation 的唯一关联 |
| `source` | Source ID、Document Version ID、来源类型、标题 | 固定被引资料身份 |
| 来源元数据 | 教材/教辅出版社与版本，高考/模拟年份、地区、试卷、题号等 | 显示完整 Attribution |
| `locator` | Chunk ID、定位类型、字符范围、页码/坐标 | 从结论返回原文位置 |
| `excerpt` | 精确摘录、Excerpt Hash、是否截断 | 发表后的可审计证据 |
| `retrieval` | Retrieval Run/Result、Query Hash、Rank、时间 | 证明内容确实来自检索 |
| `usage` | 引用关系、Attribution、改编说明、权利策略 | 决定如何展示与导出 |
| `integrity` | Source Version Hash、Chunk Hash、Excerpt Hash | 防止来源或片段被静默替换 |
| `teacher_verification` | 审核教师、审核时间 | 固定人工审核事实 |

#### 21.1.2 来源类型与元数据

| `source_type` | 必须提供的元数据 |
| --- | --- |
| `textbook` | `publisher`、`edition`、标题、页码或精确 Locator |
| `workbook` | `publisher`、`edition`、标题、页码或精确 Locator |
| `gaokao_paper` | `year`、`region`、`paper_name`、`question_number`、标题或页码 |
| `mock_exam` | `year`、`region`、`paper_name`（考试名称）、`question_number`、标题或页码 |
| `curriculum_standard` | 标准名称、发布机构、版本或年份 |
| `teacher_authored` | 标题、创建者或文档版本 |
| `licensed_material` | 标题、授权策略引用、版本 |
| `other` | 标题和可定位来源信息 |

教辅例题只能使用 `provenance.kind = workbook_example`；高考原题使用 `gaokao_question`；模拟题使用 `mock_question`；教材例题使用 `textbook_example`（不属于默认模板，但类型保留）。若模型或教师修改原题，必须切换为 `adapted`、保留来源并记录 `change_note`，不能继续冒充原文。

#### 21.1.3 Citation 使用关系

| `relation` | 含义 | 发布规则 |
| --- | --- | --- |
| `verbatim` | 原文完整引用 | Citation、原文 Hash 和来源 Locator 必须一致 |
| `excerpt` | 原文节选 | 必须保留精确 Excerpt、范围和 Attribution |
| `adapted` | 基于来源进行改编 | 必须填写 `adaptation_note`，展示时标明改编 |
| `supporting_evidence` | 来源用于支撑生成结论，不直接复制 | 保留检索证据和署名 |
| `solution_reference` | 引用参考答案或解析思路 | 不得把它表述为 Original Source 的教师结论 |

#### 21.1.4 来源权利与发布门禁

来源权利不构成法律结论，而是 Chilon 在 MVP 中执行的产品策略：

| `rights.status` | Draft | 发布/教师版导出 | 课堂或学生版导出 | 公开分享 |
| --- | --- | --- | --- | --- |
| `unverified` | 允许 | 阻止 | 阻止 | 阻止 |
| `teacher_confirmed` | 允许 | 允许 | 按 `distribution_scope` | 仅 `public`，MVP 不开放 |
| `licensed` | 允许 | 允许 | 按 `distribution_scope` | 按授权，MVP 不开放公开分享 |
| `restricted` | 允许内部控制 | 阻止 | 阻止 | 阻止 |

-   `distribution_scope = private_teacher` 只允许教师个人备课导出。
-   `distribution_scope = classroom` 允许教师版和学生版课堂使用。
-   `distribution_scope = public` 为后续能力，MVP 关闭公开分享入口。
-   教材、教辅、高考原题和模拟题的 `rights.status` 默认为 `unverified`；教师必须明确确认使用范围后才能发布或导出。
-   Attribution 要求由 Citation 固定；Student Profile 不得因隐藏答案而删除必需的来源署名。

#### 21.1.5 来源生命周期与撤回

K009 Version 生命周期固定为：

`processing` → `pending_review` → `approved` → `indexed`

异常和终止状态：

-   `processing` → `failed`/`quarantined`
-   `pending_review` → `rejected`
-   `approved`/`indexed` → `withdrawn`
-   任意未删除状态 → `deleted`，但受 Citation 保留和历史审计约束

规则：

1. 只有 `approved + indexed + not withdrawn` 的来源版本可以正式检索和生成 Citation。
2. 新 Document Version 不继承旧审核；必须重新扫描、解析和教师审核。
3. 撤回立即从新检索中移除，并阻止基于该来源创建新 Citation。
4. 撤回或删除不自动改变已发布 Material Version 的 AST 和 Citation Snapshot；引用 UI 显示“来源已撤回”或“来源不可用”Tombstone。
5. 仅当来源的授权或合同**明确要求**清除已发表 Excerpt 时，才创建新的 Redacted Material Version 或阻止后续导出；历史 Version 不原地修改。**平台四类资料已确认不要求清除（§14.1.2），因此平台来源撤回走 Tombstone 路径，不生成 Redacted Version。**
6. Source Binary 从 Object Storage 删除后，保留最小 Citation Metadata、Hash 和已发布文档中必要 Excerpt，除非执行明确的数据清除 Workflow。

#### 21.1.6 Chunk、解析与幂等

-   Chunk 唯一域为 `(document_version_id, parser_version, parse_schema_version, chunk_key)`。
-   同一 Document Version 重复解析时，相同 Parser/Parse Schema 必须产生相同 `chunk_key` 和 Content Hash，并通过 Upsert 幂等处理。
-   Parser 升级产生新的解析产物和 Chunk 版本，不覆盖已被 Citation 引用的旧 Chunk。
-   OCR、公式和表格必须保存解析类型、原文位置、Normalized Text 和必要坐标；Citation Locator 永远指向具体解析产物。
-   Citation 不得由 LLM 自行编造；只能从已审核 Source Version、Retrieval Result 和 Chunk 生成。

#### 21.1.7 发布投影与归属

-   Draft Revision 中 Citation 的权威副本是 `teaching_document.citations[]`。
-   发布时从已批准 AST 固化 `material_knowledge_citations`，形成可查询的 Material Version × Content Node × Citation 投影。
-   `material_knowledge_citations` 的唯一归属为 **K009 Knowledge**；K012 只拥有 Material Version 和 Content Node，不重复拥有来源事实。
-   `document_schema_definitions` 的唯一归属为 **K012 Material**；K014 引用 Schema Version 执行检查。
-   如果 `material_knowledge_citations` 投影损坏，可以从不可变 Material AST 重建；它不能在 AST 之外引入新来源或修改 Excerpt。

### 21.2 发布事务

建议的正式发布事务：

1. 锁定 Material 和 Draft。
2. 校验 `expected_version` 和 `base_version`。
3. 校验 Quality Gate。
4. 校验 Teaching Document Schema、AST 语义与 Citation 完整性。
5. 校验来源权利和导出范围。
6. 校验教师接受/审批。
7. 创建 Material Version。
8. 固化 AST、Hash 和 Citations。
9. 更新 `current_version` Pointer。
10. 更新 Draft 状态。
11. 写入 Outbox Event。
12. 提交事务。

若发布成功但响应丢失，使用幂等键避免重复创建版本。

### 21.3 待完成设计

-   [x] 核对 `material_publication_approvals`是否为新表或复用现有审批实体。结论：MVP 新增 K012 `material_publication_approvals`，详见 [21.9](#219-publication-approval-与发布事务状态机)。
-   [x] 冻结 Draft Check 与正式 Version Check 的统一数据模型。详见 [21.8](#218-质量检查与数学验证状态机)。
-   [x] 明确 Citation Snapshot 的最小必要字段。详见 [21.1](#211-citation) 和 `schemas/source_citation.v1.schema.json`。
-   [x] 定义发布失败、重试和补偿策略。详见 [21.9](#219-publication-approval-与发布事务状态机)。
-   [x] 完成跨模块事务边界与 Outbox Event 契约。详见 [21.11](#2111-跨模块事件与失效传播)。

### 21.4 状态机设计总则

**状态：DESIGNED**

状态机采用“**模块内强一致、跨模块显式门禁**”的设计。每个聚合只拥有自己的状态；跨模块通过不可变 ID、版本、Hash、质量报告和事件协作，不允许一个模块直接修改另一个模块的状态。

#### 21.4.1 状态机归属

| 状态机 | 权威实体/模块 | 主要职责 | 终止状态 |
| --- | --- | --- | --- |
| Task | K011 `tasks` | 教师业务目标、计划审批入口和交付物状态 | `completed`、`cancelled` |
| Requirement Version | K011 `task_requirement_versions` | 冻结本次任务输入 | `superseded`、`abandoned` |
| Plan Version | K011 `agent_plan_versions` | 可审批的 Agent 执行计划 | `rejected`、`expired`、`invalidated`、`superseded` |
| Plan Approval | K011 `agent_plan_approvals` | 对特定 Plan Version + Hash 的教师授权 | `rejected`、`revoked`、`invalidated`、`expired` |
| Execution | K011 `agent_executions` | 一次可暂停、取消和恢复的逻辑执行 | `succeeded`、`failed`、`cancelled`、`superseded` |
| Agent Run | K011 `agent_runs` | 逻辑 Execution 下的一次 Harness Runtime 会话 | `completed`、`failed`、`lost`、`superseded` |
| Step Execution | K011 `agent_step_executions` | 单个 Plan Step 的执行生命周期 | `succeeded`、`failed`、`skipped`、`cancelled`、`superseded` |
| Tool Execution | K011 `agent_tool_executions` | 单次受权工具调用 | `succeeded`、`failed`、`rejected`、`cancelled` |
| Draft | K012 `material_drafts` | 可编辑文档、质量检查和教师发布审核 | `published`、`abandoned`、`superseded` |
| Quality Check Run | K014 `quality_check_runs` | 对固定内容快照执行质量规则 | `succeeded`、`failed`、`cancelled` |
| Math Validation Run | K014 `math_validation_runs` | 对固定内容快照执行数学验证 | `succeeded`、`failed`、`cancelled` |
| Publication Approval | K012 | 对固定 Draft Revision + Quality Snapshot 的发布授权 | `rejected`、`invalidated`、`expired`、`consumed` |
| Export | K012 `material_exports` | 对固定 Material Version 渲染并上传文件 | `failed`、`cancelled`、`expired` |

**注（D.6 修正）：** Export 的 `ready` 不是终止态——它可因保留期限转为 `expired`（§21.10），而终止态不允许有出边。此前本表把 `ready` 列为终止态，与 §21.10 的迁移表冲突，现已修正。

#### 21.4.2 共同状态规则

1.  **服务端权威**：客户端只能发送业务动作，例如 `submit_plan`、`approve_plan`、`request_cancel`，不能直接写 `status`。
2.  **CAS 更新**：所有状态变更必须使用类似 `UPDATE ... WHERE id = :id AND status = :expected_status AND state_version = :expected_state_version`的条件更新；受影响行数不是 1 时必须返回冲突，不得重试为最后写入者胜出。
3.  **状态字段**：可变聚合至少包含 `status`、`state_version`、`state_changed_at`、`status_reason_code` 和可选 `status_reason`。`state_version` 单调递增，与内容 Revision 分开。
4.  **事件同事务**：状态更新、业务事件和 Outbox 写入必须处于同一 PostgreSQL 事务。事件至少包含 `event_id`、`aggregate_type`、`aggregate_id`、`from_status`、`to_status`、`actor_type`、`actor_id`、`correlation_id`、`idempotency_key` 和发生时间。
5.  **终止态不可复活**：终止状态不可修改。重试创建新的 Attempt/Execution/Export，不把旧记录改回运行中。
6.  **不推断状态**：Celery 的 job 状态、Redis Key、Harness Event 或 SSE 连接状态都不能作为业务状态事实来源；业务状态只存在于 PostgreSQL。
7.  **输入固定**：审批和执行必须固定相关 Requirement Version、Plan Version、Plan Hash、Document Schema Version、Rule Snapshot、Tool Registry Hash 和模型/运行时配置。
8.  **派生状态不重复存储**：例如“质量报告是否过期”由目标 Hash 与当前 Draft Revision 比较得出，不能仅依赖前端显示或手写布尔值。
9.  **超时不等于失败**：Worker 失联、工具超时或 Harness 无响应时先进入可协调状态，查询实际效果后再决定成功、失败或取消。
10. **状态可见性与内部状态分离**：教师可见 Activity 可以聚合内部状态，但不得把 Harness 内部推理、Token 或未过滤事件直接映射成业务状态。

### 21.5 Task、Requirement 与 Plan 状态机

#### 21.5.1 Task 状态

`tasks.status` 取值为：

-   `draft`：正在整理任务要求，尚未进入规划。
-   `planning`：正在检索、分析和生成 Plan。
-   `awaiting_plan_approval`：Plan 已提出并通过机械校验，等待教师审批。
-   `ready`：存在与当前要求匹配的有效 Plan Approval，可以启动 Execution。
-   `running`：至少一个当前有效 Execution 正在运行或等待恢复。
-   `completed`：要求的 Draft 已持久化并完成交付，Task 不再推进 Agent 执行。
-   `needs_attention`：失败、输入不足、状态不确定或业务门禁阻塞，需要教师处理。
-   `cancelling`：已请求取消，等待所有执行活动和副作用停止。
-   `cancelled`：取消完成，终止态。

Task 状态迁移：

| 当前状态 | 动作/守卫 | 下一状态 | 必要副作用 |
| --- | --- | --- | --- |
| `draft` | 提交有效 Requirement Version | `planning` | 固定 Requirement Version |
| `planning` | Plan 通过结构、DAG、Capability 和来源快照校验 | `awaiting_plan_approval` | 创建 Plan Version 与审批请求 |
| `planning` | 重试耗尽、输入不足或不可恢复错误 | `needs_attention` | 记录错误码和可恢复动作 |
| `awaiting_plan_approval` | 教师批准与当前 Plan Hash 匹配的 Approval | `ready` | 固化 Approval |
| `awaiting_plan_approval` | 教师要求修改 Plan | `planning` | 旧 Plan Version 标记 `superseded` |
| `awaiting_plan_approval` | Plan/Approval 过期或失效 | `planning` | 不创建 Execution |
| `awaiting_plan_approval` | 教师取消 | `cancelled` | 不创建 Execution |
| `ready` | 创建 Execution 并成功入队 | `running` | 记录当前 Execution ID |
| `ready` | 入队失败或 Execution 创建失败 | `needs_attention` | 记录可重试错误 |
| `ready` | Plan/Approval 在执行前失效 | `planning` | 创建新的 Plan 版本 |
| `running` | 所有必需 Draft 已持久化并完成交付，无活跃 Execution | `completed` | 记录交付物 ID |
| `running` | Execution 失败、结果不确定或阻塞 | `needs_attention` | 记录原因和当前 Execution ID |
| `running` | Plan 因输入、工具或策略变化失效，并已停止活跃执行 | `awaiting_plan_approval` | 生成或选择新的 Plan Version |
| `needs_attention` | 教师发起重新规划 | `planning` | 创建新的 Requirement/Plan 版本 |
| `needs_attention` | Plan 仍有效，教师重试 | `ready` | 旧 Attempt 保留 |
| `needs_attention` | 教师取消 | `cancelled` | 所有子执行必须终止或超时协调 |
| `draft`/`planning`/`awaiting_plan_approval`/`ready` | 教师取消 | `cancelled` | 无活跃副作用时直接终止 |
| `running` | 教师请求取消 | `cancelling` | 创建取消命令 |
| `cancelling` | 所有 Execution 已终止或确认无副作用 | `cancelled` | 写入终止事件 |
| `cancelling` | 超过取消协调期限且结果不确定 | `needs_attention` | 保留 `cancel_pending` 标记并告警 |

Task 进入 `completed` 表示 Agent 已完成交付，不表示 Draft 已发布。Draft 的教师审核和发布由 K012 状态机独立管理，这样教师可以在 Task 完成后继续修改同一 Draft。

进入 `completed` 前还必须满足：所有必需 Draft 已持久化，初轮质量与数学检查 Run 均已到达终态并绑定具体 Draft Revision，且没有待写入的输出副作用。内容问题可以留在 Draft 的 `changes_required`；检查基础设施失败或结果不确定则应让 Task 进入 `needs_attention`。

此处绑定的检查证据只证明 Agent 已完成初轮交付，**不构成发布门禁证据**。发布必须使用针对 Draft 当前 Revision 的新鲜检查（§21.8.2）；Draft 在该证据之后产生任何新 Revision，都会使其变为 `stale`。该澄清由 D1 补充。

-   `completed` 是终止态；教师在 Draft 中直接修改或通过 Chat 做局部修改不会重开 Task。若新要求需要重新检索、重做 Plan 或多步骤生成，则创建新 Task，并可通过 `parent_task_id` 保留来源关系。
-   MVP 中同一 Task 最多存在一个非终止 Execution。新 Execution 只能在前一 Execution 已终止或 `outcome_unknown` 完成对账后创建。

#### 21.5.2 Requirement Version 状态

`task_requirement_versions.status` 取值为 `draft`、`active`、`superseded`、`abandoned`。

-   `draft` → `active`：提交时完成 Schema 校验并计算 Hash；进入 `active` 后不可修改。
-   `draft` → `abandoned`：教师放弃未提交版本。
-   `active` → `superseded`：教师创建新版本。若已有批准 Plan 或活跃 Execution，必须先回到 `planning` 或完成取消协调，不能静默替换。
-   同一 Task 最多一个 `draft` 和一个 `active` Requirement Version。
-   Plan、Execution 和 Draft 必须保存创建时使用的 `requirement_version_id` 与 Hash。

#### 21.5.3 Plan Version 与 Plan Approval

`agent_plan_versions.status` 取值为：

-   `draft`：Plan 正在生成或机械校验。
-   `awaiting_approval`：Plan 已稳定，等待教师决策。
-   `approved`：存在绑定相同 Plan Hash 的有效 Approval。
-   `rejected`：教师拒绝该版本，终止态。
-   `expired`：超过审批有效期或依赖资料已失效，终止态。
-   `invalidated`：Requirement、来源快照、能力版本或 Hash 不再匹配，终止态。
-   `superseded`：已被新 Plan Version 替代，终止态。

Plan Version 迁移：

| 当前状态 | 动作/守卫 | 下一状态 |
| --- | --- | --- |
| `draft` | 校验通过并计算 Plan Hash | `awaiting_approval` |
| `draft` | 校验失败 | 不持久化为可执行 Plan |
| `awaiting_approval` | Approval 为 `approved` 且 Hash 一致 | `approved` |
| `awaiting_approval` | 教师拒绝 | `rejected` |
| `awaiting_approval` | 超过 `expires_at` | `expired` |
| `awaiting_approval` | 生成新 Plan Version | `superseded` |
| `awaiting_approval` | 输入或依赖 Hash 失效 | `invalidated` |
| `approved` | Execution 尚未启动且出现新批准 Plan | `superseded` |
| `approved` | 审批被撤销、输入变化或关键版本不再匹配 | `invalidated` |

`agent_plan_approvals.status` 取值为 `pending`、`approved`、`rejected`、`revoked`、`invalidated`、`expired`。

-   `pending` → `approved`/`rejected`/`expired`。
-   `approved` → `revoked`：仅在尚未启动 Execution 时允许。
-   `approved` → `invalidated`：Plan Hash、Requirement、来源快照或审批期限发生变化。
-   Approval 必须绑定 `plan_version_id`、`plan_hash`、`requirement_version_id`、审批人、审批时间和可选期限。
-   Execution 启动前必须重新检查 Plan 仍为 `approved`、Approval 仍有效、Hash 一致且 Requirement Version 未失效。

### 21.6 Execution、Run、Step 与 Tool 状态机

#### 21.6.1 Execution 状态

`agent_executions.status` 取值为：

-   `queued`：已创建并等待 Worker/Runtime。
-   `starting`：已取得执行租约，正在校验 Plan 并建立 Runtime Session。
-   `running`：Runtime 已确认开始，正在推进 Step DAG。
-   `pause_requested`：已请求暂停，等待安全 checkpoint。
-   `paused`：已保存 checkpoint 且当前没有活跃工具副作用，可恢复。
-   `cancel_requested`：已请求取消，尚未确认 Runtime/Run 已停止。
-   `cancelling`：Runtime 已接收取消，正在终止工具和清理临时资源。
-   `outcome_unknown`：租约丢失、Worker 失联或超时，当前无法证明是否产生副作用。
-   `succeeded`：所有必需 Step 成功，输出和验证结果已持久化。
-   `failed`：已确认且不可在当前 Attempt 内恢复的失败。
-   `cancelled`：取消完成且无活跃副作用。
-   `superseded`：因 Plan/配置失效被替换，且旧执行已停止或确认无副作用。

Execution 迁移：

| 当前状态 | 动作/守卫 | 下一状态 |
| --- | --- | --- |
| `queued` | 取得 Lease + Fencing Token，Plan/Approval 复核通过 | `starting` |
| `queued` | 启动前教师取消 | `cancelled` |
| `queued` | Plan 失效且任务已被替换 | `superseded` |
| `starting` | Runtime Session 建立并写入首个 Checkpoint | `running` |
| `starting` | 建立明确失败 | `failed` |
| `starting` | 超时且无法确认是否已产生副作用 | `outcome_unknown` |
| `running` | 请求暂停 | `pause_requested` |
| `pause_requested` | 安全 Checkpoint 已保存 | `paused` |
| `pause_requested` | 当前无法安全暂停 | `running` |
| `paused` | 教师恢复 | `queued` |
| `paused` | 请求取消 | `cancel_requested` |
| `queued`/`starting`/`running`/`paused` | 请求取消 | `cancel_requested` |
| `cancel_requested` | 没有活跃 Runtime/Tool，或全部已确认终止 | `cancelled` |
| `cancel_requested` | Runtime 已接收取消 | `cancelling` |
| `cancel_requested` | 取消确认超时 | `outcome_unknown` |
| `cancelling` | 所有 Tool/Run 进入终止态且清理完成 | `cancelled` |
| `cancelling` | 无法确认 Tool/Run 实际结果 | `outcome_unknown` |
| `running` | 全部必需 Step 成功，输出 Hash 与结果已持久化 | `succeeded` |
| `running` | 达到重试上限或出现确定性异常 | `failed` |
| `running` | Lease 丢失或长时间无有效 Heartbeat | `outcome_unknown` |
| `outcome_unknown` | 对账确认执行完成并产出合法结果 | `succeeded` |
| `outcome_unknown` | 对账确认执行失败 | `failed` |
| `outcome_unknown` | 对账确认取消完成 | `cancelled` |
| `queued`/`starting`/`running`/`paused` | 旧执行被替换并完成停止协调 | `superseded` |

约束：

-   `outcome_unknown` 不是终止态，但在完成状态对账前禁止自动重试，避免重复产生题目、草稿或导出副作用。
-   失败或取消后的重试创建新的 Execution，旧记录永久保留；新记录通过 `retry_of_execution_id` 追溯。
-   恢复暂停的 Execution 仍使用同一 Execution ID，但创建新的 Agent Run。
-   Lease 更新必须携带 Fencing Token。旧 Token 写入的结果即使迟到，也只能作为审计证据，不能推进业务状态。
-   `succeeded`、`failed`、`cancelled`、`superseded` 为终止态。

#### 21.6.2 Agent Run 状态

`agent_runs.status` 取值为 `starting`、`running`、`interrupted`、`completed`、`failed`、`lost`、`superseded`。

-   Execution 的每次启动或恢复创建一个 Run，并记录 `runtime_session_id`、Harness 版本和 Plugin Manifest Hash。
-   `starting` → `running`：Harness 确认 Session 可执行。
-   `running` → `interrupted`：安全暂停或进程受控中断。
-   `running` → `completed`/`failed`：本次 Run 明确结束。
-   `starting`/`running` → `lost`：租约或心跳丢失，业务对账交给 Execution。
-   旧 Run 在新 Run 已接管后变为 `superseded`，其迟到事件只能审计，不能推进 Step。

#### 21.6.3 Step 与 Tool 状态

`agent_step_executions.status` 取值为：

`pending`、`ready`、`running`、`paused`、`succeeded`、`failed`、`blocked`、`skipped`、`cancelled`、`superseded`。

-   `pending` → `ready`：所有 DAG 依赖满足，且 Execution 处于可调度状态。
-   `ready` → `running`：Step 获得执行权。
-   `running` → `paused`：安全 Checkpoint 已保存；恢复后回到 `running`。
-   `running` → `succeeded`/`failed`。
-   上游失败时，所有无法继续的依赖步骤进入 `blocked`；不会错误标记为 `failed`。
-   `skipped` 必须记录原因和规则，用于可选 Step。
-   Step 与 Execution 的暂停状态必须同时更新：先收到暂停请求，安全 Checkpoint 后 Step 进入 `paused`，Execution 再进入 `paused`。

`agent_tool_executions.status` 取值为：

`requested`、`authorizing`、`authorized`、`rejected`、`dispatching`、`running`、`succeeded`、`failed`、`cancelled`、`outcome_unknown`。

-   任何 Tool 调用都必须先经过身份、Owner、Scope、Capability 和业务审批 Gate。
-   `authorizing` → `authorized`/`rejected`。
-   `authorized` → `dispatching` → `running`。
-   `running` → `succeeded`/`failed`/`cancelled`/`outcome_unknown`。
-   有副作用的 Tool 必须携带稳定的 `idempotency_key`，参数 Hash、Execution ID、Step ID 和 Tool Version 共同参与幂等键计算。
-   `outcome_unknown` 必须先查询或对账，不能直接重新调用有副作用的 Tool。

### 21.7 Draft 与文档 Revision 状态机

#### 21.7.1 Draft 状态

`material_drafts.status` 取值为：

-   `editing`：可接受教师直接编辑和 Chat Revision。
-   `checking`：已提交固定 Revision 执行质量与数学检查。
-   `changes_required`：检查完成且存在阻塞问题，或教师审核要求修改。
-   `awaiting_review`：必需检查通过或仅有允许警告，等待教师发布审核。
-   `approved`：教师已批准固定 Draft Revision，可以执行发布事务。
-   `needs_rebase`：Draft 的 Base Material Version 已不是当前版本，需要显式比较或合并。
-   `needs_attention`：检查基础设施失败、来源失效或授权异常等非内容性问题。
-   `published`：已成功创建 Material Version，终止态。
-   `abandoned`：教师主动放弃，终止态。
-   `superseded`：被明确选择的其他 Draft 替代，终止态。

Draft 状态迁移：

| 当前状态 | 动作/守卫 | 下一状态 |
| --- | --- | --- |
| `editing` | 提交检查，固定当前 Revision 和 Content Hash | `checking` |
| `editing` | 发现 Base Version 已变化 | `needs_rebase` |
| `editing` | 教师放弃 | `abandoned` |
| `checking` | 新 Revision 被接受 | `editing` |
| `checking` | 教师中止检查（`cancel-check`），关联 Run 已取消或从未启动 | `editing` |
| `checking` | 全部检查完成且 Gate 为 `blocked`/`inconclusive` | `changes_required` |
| `checking` | 全部检查完成且 Gate 为 `passed`/`passed_with_warnings` | `awaiting_review` |
| `checking` | 检查基础设施失败或结果无法对账 | `needs_attention` |
| `checking` | 发现 Base Version 已变化 | `needs_rebase` |
| `changes_required` | 教师修改并产生新 Revision | `editing` |
| `changes_required` | 教师重新提交检查 | `checking` |
| `awaiting_review` | 教师批准当前 Revision + Gate Snapshot | `approved` |
| `awaiting_review` | 教师拒绝或要求修改 | `changes_required` |
| `awaiting_review` | 新 Revision 被接受 | `editing` |
| `approved` | 发布事务成功 | `published` |
| `approved` | 编辑或检查/审批快照失效 | `editing` |
| `approved` | 教师撤回授权或审批过期，目标 Revision 仍新鲜 | `awaiting_review` |
| `approved` | 发现 Base Version 已变化 | `needs_rebase` |
| `needs_attention` | 问题已处理并恢复编辑 | `editing` |
| `needs_attention` | 目标 Revision 未变化，重试同一检查 | `checking` |
| `needs_attention` | 教师放弃 | `abandoned` |
| `needs_rebase` | 完成显式 Rebase 并产生新 Revision | `editing` |
| `needs_rebase` | 教师放弃 | `abandoned` |
| `editing`/`checking`/`changes_required`/`awaiting_review`/`approved` | 教师放弃 | `abandoned` |
| `editing`/`checking`/`changes_required`/`awaiting_review`/`approved`/`needs_attention`/`needs_rebase` | 教师明确选择另一 Draft 替代 | `superseded` |

约束：

-   `published`、`abandoned`、`superseded` 为终止态。
-   发布不设置持久化的 `publishing` 状态。`approved` → `published` 在一个 PostgreSQL 事务中完成；失败回滚时保持 `approved`，由同一幂等请求重试。
-   任何新 Revision 都会使基于旧 Revision 的检查、教师审核和发布授权失效。
-   `checking` 期间允许编辑，但新 Revision 会立即把 Draft 拉回 `editing`；旧检查可以继续完成，其结果显示为 `stale`，不能参与发布门禁。
-   发布成功不会修改其 Material Base Version；后续修改必须新建 Draft。

#### 21.7.2 Draft Revision 模型

为支持可追溯检查、审批、冲突处理和发布回滚，MVP 新增：

**`material_draft_revisions`**

-   Revision 不可变，保存 `draft_id`、`revision_no`、`parent_revision_id`、`document_schema_version`、`content`、`content_hash`、`change_origin`、创建者和创建时间。
-   Revision 序号在单个 Draft 内单调递增，`(draft_id, revision_no)` 唯一。
-   `change_origin` 至少区分 `teacher_edit`、`chat_revision`、`agent_generation`、`rebase`、`restore` 和 `import`。
-   `material_drafts` 保存 `current_revision_id`、`current_revision_no`、`current_content_hash` 和 `base_version_id`。
-   每次有效写入同时创建 Revision 并切换 Draft 当前指针；两个操作在同一事务中完成。
-   被质量检查、教师审批或发布引用的 Revision 必须永久保留。未被引用的自动保存 Revision 可按保留策略压缩，但不得静默改变已存在的 Revision Hash。
-   MVP 使用不可变完整快照，优先保证正确性和可审计性；后续可根据数据量改为快照 + Patch 存储。

#### 21.7.3 直接编辑与 Chat 并发协议

MVP 不引入 CRDT，采用结构化 JSON/JSON Patch、乐观并发控制和显式冲突处理：

1.  客户端加载 Draft 时获得 `current_revision_no` 和 ETag。ETag 由 Draft ID、Revision No、Document Schema Version 和 Content Hash 共同生成。
2.  每次保存必须携带 `If-Match` 或 `expected_revision_no`。不匹配时返回 `409 REVISION_CONFLICT`，不得最后写入者胜出。
3.  Chat 请求发出时记录 `base_revision_no`。Agent 产生修改提案后，服务端再次检查 Draft 指针。
4.  若 Draft 指针未变化，服务端在同一事务中应用结构操作、创建新 Revision，并递增 Revision No。
5.  若 Draft 指针已变化，Agent 修改只作为待审阅 Patch/Proposal 返回，不自动应用。教师可查看差异、重新生成或手动合并。
6.  编辑操作优先使用稳定 Node ID 和局部结构操作；整篇内容替换仅用于导入、恢复或明确的全文改写。
7.  删除节点、改变题目来源、改变答案/解析关联或改变 Student Profile 可见性时，服务端必须进行结构校验。
8.  冲突处理本身不得覆盖已存在 Revision；接受合并结果时创建新的 `rebase` 或 `teacher_edit` Revision。

### 21.8 质量检查与数学验证状态机

#### 21.8.1 检查过程状态

`quality_check_runs.process_status` 与 `math_validation_runs.process_status` 统一使用：

`queued`、`running`、`succeeded`、`failed`、`cancelled`、`outcome_unknown`。

-   `queued` → `running`：Worker 取得任务并固定规则/Validator 版本。
-   `running` → `succeeded`：检查执行完成，并已保存结果和证据。
-   `running` → `failed`：检查程序本身明确失败。
-   `running` → `cancelled`：被取消或目标已被替换。
-   `running` → `outcome_unknown`：Worker 或 Validator 失联。
-   `succeeded`、`failed`、`cancelled` 为终止态；技术失败与内容质量失败必须分开表达。

每个 Run 必须固定：

-   `target_type`：`draft_revision` 或 `material_version`。
-   `target_id`、`target_content_hash` 和 `document_schema_version`。
-   规则快照、Validator 版本、Tool Version 和执行配置 Hash。
-   `started_at`、`finished_at`、证据和错误码。

#### 21.8.2 检查结论与发布门禁

`quality_check_runs.gate_result` 取值为：

`not_evaluated`、`passed`、`passed_with_warnings`、`blocked`、`inconclusive`。

`math_validation_runs.validation_result` 取值为：

`not_evaluated`、`validated`、`failed`、`inconclusive`、`unsupported`。

发布 Gate 规则：

1.  `process_status` 不是 `succeeded` 的 Run 不产生有效发布证据。
2.  `stale` 是派生属性：目标不再是 Draft 当前 Revision、Content Hash 不匹配、规则政策 Hash 变化或 Validator 版本不再满足当前门禁时，检查失效。
3.  S0 问题永久阻止发布，不能由教师覆盖。
4.  S1 默认阻止发布；教师显式确认例外时，必须保存原因、风险提示、确认人和确认时间，并绑定到具体 Revision 与 Gate Snapshot。
5.  S2 由教师决定；S3 不阻止发布，但应保留记录。
6.  `inconclusive` 和 `unsupported` 在 MVP 中默认阻止发布，除非对应规则明确声明该结果为允许。
7.  发布审批必须固定 `required_quality_run_ids`、`required_math_run_ids`、规则政策 Hash、Gate Result 和 Gate Snapshot Hash。
8.  单个 LLM 输出“通过”不能作为数学证据；证据必须来自实际 Validator、规则执行或可复现测试。
9.  Teaching Document Schema、AST 语义、Citation 完整性和来源权利是独立于数学质量检查的发布前置门禁；任一失败均进入 `changes_required` 或 `needs_attention`，不得发布。

#### 21.8.3 Issue 与 Evidence 生命周期

`quality_issues.resolution_status` 取值为：

`unresolved`、`resolved`、`waived`、`invalidated`、`superseded`。

-   `unresolved` → `resolved`：新内容或补充证据证明问题已消除；必须绑定验证 Run 或人工确认记录。
-   `unresolved` → `waived`：S1/S2 在规则允许时由教师显式接受风险；S0 永远不能 `waived`。
-   `unresolved` → `invalidated`：确认规则误报或证据失效，必须记录理由和审核人。
-   任意未终止 Issue → `superseded`：问题所属检查目标已不是当前 Revision，或规则政策版本已被替换。
-   `quality_evidence` 不可变，只能追加；更正证据通过新 Evidence 记录和关联表达，不覆盖原证据。
-   Gate 计算必须同时检查 Issue Severity、Resolution Status、Check Freshness 和 Policy Version。

### 21.9 Publication Approval 与发布事务状态机

#### 21.9.1 Publication Approval

`material_publication_approvals.status` 取值为：

`pending`、`approved`、`rejected`、`invalidated`、`expired`、`consumed`。

-   `pending` → `approved`/`rejected`/`expired`。
-   `approved` → `consumed`：发布事务成功，且已绑定新建的 Material Version。审批只能消费一次。
-   `approved` → `invalidated`：Draft 产生新 Revision、Base Version 变化、质量结果过期、审批策略变化或教师撤回。
-   `rejected`、`invalidated`、`expired`、`consumed` 为终止态。
-   `consumed` 后相同 `Idempotency-Key` 的重复请求返回已创建的 Material Version；不同发布意图必须重新审批。
-   只有 Draft 处于 `awaiting_review` 且目标 Revision、Gate Snapshot 均新鲜时才能创建 `pending` Approval；审批与 Draft 的 `approved` 状态必须在同一事务中写入。

Approval 必须绑定：

-   `material_id`、`draft_id`、`draft_revision_id` 和 `draft_content_hash`。
-   `base_version_id`。
-   `document_schema_version`。
-   `required_quality_run_ids`、`required_math_run_ids`、`quality_policy_hash` 和 `gate_snapshot_hash`。
-   `citation_snapshot_hash` 和 Student/Teacher Profile 配置 Hash。
-   `approver_id`、审批时间、失效时间和可选教师例外确认。

#### 21.9.2 发布事务

Draft `approved` → `published` 必须使用一个短 PostgreSQL 事务：

1.  校验身份、Owner、Project 权限和 `Idempotency-Key`。
2.  锁定 Material、Draft 和 Approval，或使用等价的条件更新保护。
3.  校验 Draft 仍为 `approved`，Revision、Content Hash、Base Version 和 `state_version` 均符合预期。
4.  校验 Approval 为 `approved` 且未过期，审批目标 Hash 与当前内容一致。
5.  重新计算质量 Gate Freshness；任何检查失效都拒绝发布。
6.  按固定 Document Schema Version 校验 AST，执行 20.9 的引用、节点、题型和可见性语义检查。
7.  校验每个 Citation Snapshot 非过期、Source Version 已审核、Excerpt/Chunk Hash 一致，且没有虚构或无法追溯的来源。
8.  根据目标 Teacher/Student Profile 校验 `rights.status` 和 `distribution_scope`；任何越权导出都阻止发布。
9.  校验 Material 当前版本仍等于 Draft `base_version_id`；否则转 `needs_rebase`，不得覆盖其他 Draft 的发布结果。
10. 规范化 AST，计算 Document Hash，固化 Citation Snapshot 和必要来源元数据。
11. 创建不可变 `material_versions`，写入 Approval ID 和幂等键唯一约束。
12. 固化 Citation、Schema Version、Profile 配置和 Change Summary。
13. 更新 Material 当前版本指针。
14. 将 Draft 更新为 `published`，将 Approval 更新为 `consumed`。
15. 写入业务事件和 `event.material.version_published` Outbox 事件后提交。

发布事务不存在可持久化的“部分成功”。任何一步失败均回滚，Draft 保持 `approved`；若是业务校验失败，则返回明确错误并保持或转为 `needs_rebase`。若提交成功但 HTTP 响应丢失，客户端以相同幂等键重试并获得原版本。

### 21.10 Export 状态机

`material_exports.status` 取值为：

`queued`、`rendering`、`uploading`、`ready`、`failed`、`cancelled`、`outcome_unknown`、`expired`。

迁移规则：

| 当前状态 | 动作/守卫 | 下一状态 |
| --- | --- | --- |
| `queued` | 导出 Worker 取得任务 | `rendering` |
| `queued` | 教师取消 | `cancelled` |
| `rendering` | 文件渲染完成 | `uploading` |
| `rendering` | 明确渲染失败 | `failed` |
| `uploading` | Object Storage 上传完成并校验 Hash | `ready` |
| `uploading` | 明确上传失败 | `failed` |
| `uploading` | 上传结果不确定 | `outcome_unknown` |
| `outcome_unknown` | 对账确认成功 | `ready` |
| `outcome_unknown` | 对账确认失败 | `failed` |
| `queued`/`rendering`/`uploading` | 教师取消 | `cancelled` |
| `ready` | 达到保留期限 | `expired` |
| `ready`/`failed`/`cancelled`/`expired` | 重试 | 创建新 Export 记录 |

约束：

-   Export 必须固定 `material_version_id`、Document Schema、Teacher/Student Profile、Renderer Version、Options Hash 和 Source Document Hash。
-   Student Profile 在 AST 层删除答案、解析和教师备注后才进入 Renderer。
-   有副作用的渲染/上传使用稳定幂等键；Object Storage Key 可以包含导出意图 Hash，避免重试产生多个不可追踪文件。
-   `ready` 表示文件已持久化并校验，不等于永久公开可用；下载使用短时效受权 URL。

### 21.11 跨模块事件与失效传播

跨模块协作使用业务事件，不通过直接修改其他聚合状态实现：

| 事件 | 生产者 | 必须触发的下游行为 |
| --- | --- | --- |
| `task.requirement_activated` | K011 | 生成或重新生成 Plan；旧 Plan 不能继续执行 |
| `plan.approved` | K011 | Task 可进入 `ready` |
| `plan.invalidated` | K011 | 停止当前 Execution；不得复用旧 Approval |
| `execution.succeeded` | K011 | 持久化 Draft、Citation 和 Activity；满足条件时完成 Task |
| `execution.failed` | K011 | Task 进入 `needs_attention`；未完成产物不得伪装成正式 Draft |
| `draft.revision_created` | K012 | 旧质量检查、审核和发布授权变为失效 |
| `quality.gate_completed` | K014 | Draft 进入 `changes_required` 或 `awaiting_review` |
| `draft.approved` | K012 | 允许发起一次发布事务 |
| `material.version_published` | K012 | 更新 Material 当前指针；其他同 Base Draft 标记 `needs_rebase` |
| `material.export_requested` | K012 | 创建固定版本和 Profile 的 Export |
| `material.export_ready` | K012 | 通知教师文件可下载 |

关键失效规则：

1.  Requirement 或 Plan 变化不能静默改写已生成 Draft；旧 Draft 保留并标记来源关系，由教师决定继续、重建或放弃。
2.  Draft 任一有效编辑都会使旧检查和发布审批失效，但不会删除旧证据。
3.  Material 出现新版本后，所有基于旧 Base Version 的可编辑 Draft 进入 `needs_rebase`。
4.  已发布 Material Version、已消费 Approval 和已完成的 Check Evidence 永不因上游重试而修改。
5.  跨模块事件消费必须幂等，以 `event_id`、目标版本号和业务幂等键去重。

#### 21.11.1 基准教学场景的正常状态序列

``` text
Task:        draft -> planning -> awaiting_plan_approval -> ready
                  -> running -> completed
Plan:        draft -> awaiting_approval -> approved
Execution:   queued -> starting -> running -> succeeded
Draft:       editing -> checking -> awaiting_review -> approved -> published
Export:      queued -> rendering -> uploading -> ready
```

其中 Task 的 `completed` 表示 Agent 已交付 Draft；Draft 的教师修改、再次检查和发布通过 K012 状态机继续，二者不能混成一个状态字段。

### 21.12 API、数据库与测试约束

#### 21.12.1 API 契约

-   状态变更使用动作接口，例如 `POST /tasks/{id}/actions/submit`、`POST /executions/{id}/actions/cancel`、`POST /drafts/{id}/actions/request-check`、`POST /drafts/{id}/actions/approve`。
-   客户端提交 `Idempotency-Key`、`expected_state_version`，Draft 编辑另提交 `If-Match`/`expected_revision_no`。
-   响应返回服务端权威的 `status`、`state_version`、关联版本 ID、允许动作和阻塞原因。
-   非法迁移返回 `409 STATE_CONFLICT`；Revision 不匹配返回 `409 REVISION_CONFLICT`；质量或审批过期返回 `409 STALE_GATE` 或对应领域错误码。
-   客户端不得通过通用 `PATCH status` 写入状态；所有状态值和允许动作由服务端策略决定。

#### 21.12.2 数据库表达

-   状态字段使用 Registry 统一枚举/受控字符串，数据库 CHECK、Domain Model 和 OpenAPI 使用同一名称。
-   状态迁移由领域服务控制，不能只依赖数据库 Trigger；Trigger 可用于防止非法回写终止态或更新不可变字段。
-   所有需要 CAS 的聚合增加 `state_version INTEGER NOT NULL DEFAULT 0`，更新时同时递增。
-   Task 对 `draft`/`active` Requirement 使用部分唯一约束；Draft Revision 对 `(draft_id, revision_no)` 使用唯一约束；Material Version 对发布 `Idempotency-Key` 使用唯一约束。
-   发布事务对 Material 当前版本使用行锁或带旧版本条件的单调更新，防止两个 Draft 同时成为当前版本。
-   状态、Owner、Project、创建时间和关联版本字段建立面向查询的复合索引；事件流使用聚合 ID + 序列查询。
-   事件必须保留 `correlation_id` 和 `causation_id`，支持从 Task 追踪到 Execution、Draft、Quality Run、Publication 和 Export。

#### 21.12.3 必须建立的测试

-   使用表驱动测试覆盖每一个合法迁移和所有关键非法迁移。
-   对 UI/Celery/SSE 断线与重连，验证业务状态只由 PostgreSQL 状态和事件决定。
-   两个请求同时审批、暂停、恢复、取消或发布时，只允许一个 CAS 成功。
-   Draft 当前 Revision 与 Chat `base_revision_no` 不一致时，必须返回冲突且不创建修改。
-   质量检查期间修改 Draft，验证旧报告变 `stale` 且发布门禁拒绝。
-   在发布事务的每一步注入失败，验证不会出现孤立 Material Version、错误指针或重复 Approval 消费。
-   使用相同发布幂等键重复请求，返回同一 Material Version。
-   丢失 Worker Lease 后使用旧 Fencing Token 写入，验证旧结果不能推进状态。
-   `outcome_unknown` 分别对账为成功、失败和取消，验证不会重复执行有副作用的 Tool。
-   SSE 断线后通过事件 Sequence 回放，状态投影与 PostgreSQL 当前状态一致。
-   从 Requirement Version 到 Export 建立完整 Trace，验证来源、审批和导出固定的是同一 Revision/Version Hash。

### 21.13 State Machine Registry 契约

**状态：DESIGNED / 机器可读副本已生成**

§21.4–§21.11 的状态机同时以机器可读形式维护，供实现、测试与工具消费：

-   [schemas/state_machines.v1.json](schemas/state_machines.v1.json) — 13 个聚合、101 个状态、136 条迁移、8 组值域、11 个跨模块事件、9 条 Gate 规则。
-   [schemas/state_machines.v1.schema.json](schemas/state_machines.v1.schema.json) — 该文件的 JSON Schema（Draft 2020-12）。
-   `design/check_state_machines.py` — 校验 JSON Schema 无法表达的一致性，并与本文档交叉核对。
-   [schemas/actions.v1.json](schemas/actions.v1.json) — 动作层（D4）：122 条动作、23 组复合命令、18 个错误码，与上述迁移一一对应。
-   `design/check_actions.py` — 校验每条迁移恰好被一个动作认领、复合命令分组一致、错误码引用有效。

Registry 覆盖的聚合：Task、Requirement Version、Plan Version、Plan Approval、Execution、Agent Run、Step Execution、Tool Execution、Draft、Quality Check Run、Math Validation Run、Publication Approval、Export。

**每条迁移记录**：`id`、`from`（单值或数组）、`to`、`trigger`（动作标识）、`guard`（守卫条件）、`effects`（副作用）。

`trigger` 是本轮提出的动作标识（如 `submit_check`、`cancel_check`、`publish`、`reconcile_succeeded`），用于对齐 D4 的动作接口与 D5 的错误码；**其命名在 D4 正式冻结前仍可能调整**。

**双向同步规则**：

1. 修改状态机时，本文档 §21 与 `state_machines.v1.json` 必须在同一次变更中同时更新。
2. `check_state_machines.py` 校验：状态名在文档中以行内代码出现；§21.4.1 的终止态列与 Registry 完全一致；终止态无出边（SM-R05）；所有状态从初始态可达；迁移端点均为已声明状态。
3. 任何一侧单独修改导致的不一致必须视为缺陷，不得以“以文档为准”或“以 JSON 为准”绕过。

**本轮由此发现的文档缺陷**：§21.4.1 曾把 Export 的 `ready` 列为终止态，与 §21.10 的 `ready` → `expired` 迁移冲突。已修正为 `failed`、`cancelled`、`expired`，并在该表下注明原因。

------------------------------------------------------------------------

# 第七部分：API、前端与用户体验

## 22. API 设计状态

用户已授权 API 设计由项目设计方全权负责。当前可恢复记录尚无完整冻结的 Endpoint 清单，因此本节记录设计原则和待办，不伪造已确认 API。

### 22.1 API 原则

-   REST API 为主要业务接口。
-   SSE 用于实时对话和执行事件。
-   API 版本化。
-   请求/响应 Schema 与 Registry/Domain Model 对齐。
-   统一错误码和错误响应结构。
-   所有写操作考虑幂等性。
-   Owner/Project/Task 权限在服务端核验。
-   不信任客户端传入的 Owner ID。
-   长任务异步化，返回 Task/Execution 标识。
-   上传和导出使用受限、短时效对象存储 URL。
-   API 不暴露 Harness 内部未过滤事件。

### 22.2 预期 API 领域

-   Authentication / Identity
-   Projects
-   Materials
-   Material Drafts
-   Material Versions
-   Knowledge Sources
-   Knowledge Reviews
-   Knowledge Search
-   Tasks
-   Agent Plans
-   Plan Approvals
-   Agent Executions
-   Conversations
-   Conversation Messages
-   SSE Events
-   Quality Checks
-   Math Validation
-   Exports
-   Account Settings
-   Administrative Security

### 22.3 API TODO

-   [ ] 完成 Endpoint Inventory。
-   [ ] 定义 REST Resource 和命名。
-   [ ] 定义 Request/Response JSON Schema。
-   [ ] 定义分页、排序、过滤规范。
-   [ ] 定义统一错误码和 HTTP Status 映射。
-   [ ] 定义 Idempotency-Key 规则。
-   [ ] 定义 ETag/Version 乐观锁策略。
-   [ ] 定义 SSE Event Envelope、重放和断线恢复。
-   [ ] 定义上传、下载和导出 API。
-   [ ] 生成 OpenAPI 文档。
-   [ ] 完成 API Contract Tests。

## 23. UI/UX 与前端实现状态

用户已授权前端设计由项目设计方全权负责。当前已确认整体交互方向，但尚无完整页面规格和实现。

### 23.1 已确认方向

-   React + TypeScript。
-   Workflow-oriented IA。
-   Workspace + Chat。
-   桌面端三栏布局。
-   小屏可折叠布局。
-   结构化文档编辑与 AI Chat 修改并行。
-   计划批准、质量问题、发布审核在工作区中可见。
-   以 Project 为教学专题组织中心。

### 23.2 建议页面/区域清单（待详细设计）

1.  登录与账户设置
2.  Home / Dashboard
3.  Project List
4.  Project Workspace
5.  Material Library
6.  Material Editor
7.  AI Chat
8.  Task Plan Review
9.  Execution Progress
10. Knowledge Base
11. Knowledge Source Review
12. Quality Report
13. Math Validation Details
14. Export Center
15. Account & Preferences
16. Admin Console（按权限开放）

### 23.3 前端 TODO

-   [ ] 完成信息架构和导航树。
-   [ ] 完成核心用户旅程和任务流程图。
-   [ ] 完成页面级 Wireframe。
-   [ ] 完成 Design System（色彩、字体、间距、层级、组件）。
-   [ ] 选择并冻结 UI Component Library。
-   [ ] 定义前端路由和权限守卫。
-   [ ] 定义 Query Cache、表单状态和编辑器状态管理。
-   [ ] 设计 SSE 客户端、断线恢复和重放。
-   [ ] 设计结构化 Document Editor。
-   [ ] 设计数学公式编辑和预览。
-   [ ] 设计 Plan Approval、Quality Issue 和 Publish Review 交互。
-   [ ] 完成响应式布局与可访问性规范。
-   [ ] 建立视觉回归和 E2E 测试。
-   [ ] 实现前端性能监控和错误上报。

------------------------------------------------------------------------

# 第八部分：安全、隐私、质量与运维

## 24. 安全与隐私

### 24.1 数据隔离

-   教师资料默认私有。
-   Knowledge Base 私有。
-   Project/Material/Conversation/Task/Execution 等按 Owner 隔离。
-   跨 Project 引用默认只读。
-   任何跨 Owner 操作必须有显式业务授权和审计。

### 24.2 文件安全

-   上传文件先进入隔离区。
-   检查文件名、MIME 和实际内容。
-   限制文件大小、类型和解析资源。
-   恶意文件不进入正式知识库。
-   解析器不执行文件内脚本、宏或嵌入程序。
-   文件通过短时效授权访问。

### 24.3 敏感数据

建议字段安全分类： - `public` - `internal` - `confidential` - `restricted`

密码 Hash、Session Token Hash、邮箱、教师教学资料和私有知识内容应按敏感级别处理。真实密码、Token、Secret 不得写入日志或导出。

### 24.4 Agent 安全

-   最小权限。
-   工具调用逐次授权。
-   工具参数不可信。
-   外部内容视为数据，不视为权限指令。
-   受限执行环境。
-   网络出口控制。
-   Secret 通过安全配置注入。
-   高风险操作审批。
-   完整审计与异常告警。

## 25. 可观测性与运维

### 25.1 可观测性

-   Structured Logs
-   Metrics
-   Traces
-   Request ID
-   Execution ID
-   Agent Run ID
-   Tool Invocation ID

不得在日志中记录密码、Token、完整私有资料或不必要的个人数据。

### 25.2 可靠性

-   Outbox Pattern。
-   At-least-once Delivery。
-   Idempotent Consumers。
-   Lease + Fencing Token。
-   有限重试和退避。
-   Dead Letter / Failed Job 管理。
-   Redis 故障时以 PostgreSQL 事件记录为事实来源。
-   导出和解析任务异步执行。

### 25.3 运维 TODO

-   [ ] 定义环境：local、dev、staging、production。
-   [ ] 定义 Secret Management。
-   [ ] 建立 CI/CD。
-   [ ] 建立 DB Migration 发布流程。
-   [ ] 建立备份、PITR 和恢复演练。
-   [ ] 建立日志、指标和 Trace Dashboard。
-   [ ] 定义告警分级与值班流程。
-   [ ] 建立容量规划与压测。
-   [ ] 建立灾难恢复演练。
-   [ ] 建立依赖漏洞扫描和镜像签名策略。

------------------------------------------------------------------------

# 第九部分：数据库字段 Registry 专项规范

## 26. Global Field Registry

### 26.1 字段标准属性

每个字段至少记录：

-   `name`
-   `postgres_type`
-   `nullable`
-   `default`
-   `generated`
-   `identity`
-   `domain`
-   `enum`
-   `sensitivity`
-   `classification`
-   `description`
-   `source_reference`
-   `status`

建议增加： - `semantic_type` - `max_length` - `precision` - `scale` - `check_constraints` - `indexed` - `index_purpose` - `orm_type` - `json_schema_ref` - `deprecation` - `introduced_in` - `last_reviewed_at`

### 26.2 公共字段模板

-   `base_entity`
-   `mutable_entity`
-   `owned_entity`
-   `soft_delete_entity`
-   `audit_actor`
-   `immutable_record`

模板不是强制每张表使用全部字段。

### 26.3 关键字段规范

-   `id`：UUID，应用层 UUIDv7。
-   `owner_id`：UUID，指向 Owner 身份主体。
-   `created_by` / `updated_by`：UUID，按业务审计需求使用。
-   `version`：INTEGER，乐观锁版本。
-   `schema_version`：INTEGER，记录 JSON Schema/结构版本。
-   `metadata`：JSONB，仅放非核心、可扩展元数据。
-   `idempotency_key`：VARCHAR(255) 候选标准，按作用域建立唯一性。
-   `request_id`：UUID，用于请求关联。
-   `content_hash`：建议 SHA-256 lowercase hex。
-   `storage_key`：Object Storage Key，不存文件本体。
-   `created_at` / `updated_at`：TIMESTAMPTZ UTC。
-   `deleted_at`：仅软删除实体使用。

### 26.4 JSONB 规范

-   只用于文档 AST、快照、配置等真正需要灵活结构的字段。
-   有版本化 Schema 的 JSONB 必须保存 Schema Version。
-   关键结构通过 JSON Schema 和 Service Layer 验证。
-   必要时使用 CHECK 限制 object/array 和必要键。
-   不将关系数据全部塞入 JSONB。

### 26.5 数值规范

-   金额、比例、分数、数学评分使用 NUMERIC。
-   不使用 FLOAT/REAL/DOUBLE 表示精确业务数值。
-   `NUMERIC(p,s)` 由业务语义决定。
-   百分比字段必须定义单位和范围。
-   进度字段需明确是 0–100 还是 0–1。

### 26.6 时间规范

-   时间点：UTC `TIMESTAMPTZ`。
-   教学日期等无时区业务日期：`DATE`。
-   时间段：确有需要时使用 `INTERVAL`。
-   不将业务日期错误地转换为 UTC 时间点。

### 26.7 Hash 与文件规范

-   文件二进制放 Object Storage。
-   DB 保存 storage_key、mime_type、file_size_bytes、checksum。
-   Hash 算法和编码必须明确。
-   SHA-256 lowercase hex 建议长度 64。
-   大文件不放普通业务表 BYTEA。

### 26.8 ORM 对照

-   Registry 是唯一权威。
-   SQLAlchemy 2.0 Async Mapping 必须与 Registry 一致。
-   Python `default` 与数据库 `server_default` 区分。
-   UUIDv7 由应用层生成。
-   JSONB Schema 在 Service Layer 验证。
-   乐观锁使用 SQLAlchemy `version_id_col` 或显式 Compare-and-Swap。

### 26.9 CI Field Checks

-   FLD-001 字段名 snake_case。
-   FLD-002 重复字段/语义冲突。
-   FLD-003 类型映射有效。
-   FLD-004 Nullable/default 明确。
-   FLD-005 ENUM/DOMAIN 有实际引用。
-   FLD-006 精确数值禁止浮点类型。
-   FLD-007 时间时区规范。
-   FLD-008 JSONB Schema Version 完整。
-   FLD-009 敏感度分类完整。
-   FLD-010 Hash 格式一致。
-   FLD-011 storage_key 不存真实文件内容。
-   FLD-012 公共字段模板一致。
-   FLD-013 ORM Mapping 与 Registry 一致。
-   FLD-014 Migration Column 与 Registry 一致。
-   FLD-015 Schema Release Hash 一致。

### 26.10 代表性字段 Registry 样例状态

下列示例只展示已知字段设计的规范化方式。未核实字段必须保留 `proposed` 或 `pending`，不得直接生成正式 DDL。

| 表 | 字段 | 状态 | 说明 |
| --- | --- | --- | --- |
| projects | id | DESIGNED | UUIDv7 |
| projects | owner_id | DESIGNED | Owner Scope |
| projects | name | DESIGNED | VARCHAR(160) |
| projects | cover_storage_key | PROPOSED | 需核对是否纳入 |
| materials | primary_project_id | DESIGNED | NULL 表示 Personal Library |
| materials | current_version_id | DESIGNED | 延迟复合 FK |
| material_versions | document_content | DESIGNED | JSONB AST |
| material_versions | content_hash | DESIGNED | 内容 Hash |
| knowledge_document_versions | storage_key | DESIGNED | Object Storage Key |
| knowledge_document_versions | parser_version | PENDING | 需冻结字段字典 |
| conversation_messages | content | DESIGNED | JSONB Blocks |
| conversation_messages | sequence_number | DESIGNED | Conversation 内顺序 |
| quality_check_runs | target_type | PROPOSED | Draft/Version Target 方案待冻结 |
| quality_check_runs | content_hash | PROPOSED | 固定检查内容快照 |

------------------------------------------------------------------------

# 第十部分：当前设计进度与未完成事项

## 27. 已完成的设计工作

以下表示设计层面已完成或已形成较完整方案，不代表已开发：

-   产品定位、目标用户、初始学科和课程体系。
-   Lesson / Exercises / Worksheet MVP 内容范围。
-   Hybrid Interaction、Workspace + Chat。
-   Human-in-the-loop Agent 工作流。
-   DeepSeek Harness 复用方向与 Chilon Control Plane 边界。
-   PostgreSQL 17、单一 public Schema、FastAPI、SQLAlchemy Async、Alembic 等技术方向。
-   Registry-First DDL 工程原则。
-   RLS、Owner 复合 FK、权限角色和事务上下文规范。
-   索引、连接池、事务、Outbox、备份恢复原则。
-   K012 Project/Material 核心表与主要约束。
-   K013 Conversation/Activity 核心表与事件流方案。
-   K014 Quality/Evaluation 24 张表的职责和核心规则。
-   K009 Knowledge Base 九张候选表及审核检索生命周期。
-   K021 Administrative Security 四张已知核心表的审批控制原则。
-   Structured Teaching Document Model。
-   Teaching Document Schema v1 与 Source/Citation Contract v1，以及可校验的 JSON Schema 和基准场景样例。
-   Knowledge → Draft → Quality → Publish → Export 端到端链路。
-   Task、Requirement、Plan、Approval、Execution、Run、Step、Tool、Draft、 Quality、Publication 和 Export 的跨模块状态机。
-   不可变 Draft Revision、直接编辑与 Chat 冲突协议、质量 Gate Freshness 和单次发布审批协议。
-   Global Schema Freeze Gate 和字段 Registry 规范初稿。

## 28. 尚未完成的关键设计工作

**台账约定：** 本节只保留跨模块事项和指向模块章节的指针。模块级待办以各模块自身的 TODO 小节为准；同一事项不在两处重复叙述，避免措辞漂移。

### 28.1 历史设计恢复与模块清点

| 待办 | 权威位置 |
| --- | --- |
| K001–K008、K010、K015–K020、K022–K023 的原始模块定义与表清单 | [§12](#12-模块总览与完整性状态) |
| K024 是否为独立模块 | [§12](#12-模块总览与完整性状态) |
| K002 Identity 历史表名与用户名方案 B 参数 | [§13.4](#134-关键-todo) |
| K001 与 K009 知识实体去重 | [§14.5](#145-todo) |
| K011 约 35 张表的完整清单 | [§15.6](#156-todo) |
| K012 完整历史表清单 | [§16.8](#168-todo) |
| K013 完整历史表清单 | [§17.6](#176-todo) |
| K021 完整历史表清单 | [§19.3](#193-todo) |

### 28.2 数据库 Schema

-   [ ] 完成所有已确认实体的 Global Field Registry。
-   [ ] 完成所有字段 PostgreSQL 类型、NULL、DEFAULT、CHECK。
-   [ ] 完成全部 FK / Unique / Check Registry。
-   [ ] 完成全部 Index Registry。
-   [ ] 完成 ENUM / DOMAIN 的实际引用核对。
-   [ ] 完成所有 RLS Policy Registry。
-   [ ] 完成 Permissions / Grants Registry。
-   [ ] 完成 Migration Dependency Graph。
-   [x] 冻结 `material_knowledge_citations` 归属为 K009。
-   [x] 冻结 Document Schema Registry 归属为 K012 `document_schema_definitions`。
-   [x] 冻结 Material Publication Approval 实体与状态。详见 [21.9](#219-publication-approval-与发布事务状态机)。
-   [ ] 冻结 Execution Lease/Fencing Token 字段归属。
-   [ ] 生成正式 Registry Manifest。
-   [ ] 通过 Schema Freeze Gate。

### 28.3 DDL 与数据库实施

-   [ ] 建立真实 `database/registry/` 文件。
-   [ ] 实现 Registry Parser 和 Validator。
-   [ ] 实现 Deterministic DDL Generator。
-   [ ] 建立 Alembic Migration 基线。
-   [ ] 生成 Bootstrap SQL。
-   [ ] 生成 Tables / Constraints / Indexes / RLS / Grants。
-   [ ] 在 PostgreSQL 17 测试环境执行 Migration。
-   [ ] 验证 Deferred FK 和循环关系。
-   [ ] 验证 RLS 使用真实 Runtime Role。
-   [ ] 验证 Append-only 权限和 Trigger。
-   [ ] 验证并发、锁、幂等和 Outbox。
-   [ ] 建立 Migration Drift CI。
-   [ ] 建立备份与恢复测试。

### 28.4 Agent 与 Harness

-   [ ] 完成 Harness Adapter 设计与实现。
-   [ ] 固定 Harness 版本。
-   [ ] 完成 Runtime 安全隔离。
-   [ ] 完成 Plugin Manifest 与版本管理。
-   [ ] 完成 Tool Registry 与 Harness Registry 同步。
-   [ ] 完成业务授权 Gate。
-   [ ] 完成 Plan Approval 持久化。
-   [ ] 完成 Execution/Run/Session 映射。
-   [ ] 完成中断、恢复、取消和重试机制。
-   [ ] 完成 Agent 评估和回归测试。

### 28.5 Knowledge 与内容质量

-   [ ] 完成文件扫描、解析、OCR 和 Chunking 实现。
-   [ ] 完成教师审核 UI。
-   [ ] 完成中文检索质量评估。
-   [ ] 完成 Citation UI 和来源定位。
-   [ ] 完成数学 Validator Service。
-   [ ] 完成高考数学测试数据集。
-   [ ] 完成 Quality Rules 初始版本。
-   [ ] 完成质量发布 Gate。

### 28.6 API 与前端

-   [ ] 完成 API Endpoint Inventory。
-   [ ] 完成 OpenAPI。
-   [ ] 完成统一错误码。
-   [ ] 完成 SSE 协议。
-   [ ] 完成 UI Information Architecture。
-   [ ] 完成 Wireframes。
-   [ ] 完成 Design System。
-   [ ] 完成 Document Editor。
-   [ ] 完成 Chat / Plan Approval / Quality Review。
-   [ ] 完成 DOCX/PDF Export UI。
-   [ ] 完成 E2E 和视觉回归测试。

### 28.7 生产准备

-   [ ] 完成 CI/CD。
-   [ ] 完成环境和 Secret 管理。
-   [ ] 完成监控告警。
-   [ ] 完成性能压测。
-   [ ] 完成安全测试。
-   [ ] 完成隐私和数据生命周期审查。
-   [ ] 完成备份恢复演练。
-   [ ] 完成生产发布和回滚 Runbook。

### 28.8 产品闭环与状态一致性

以下事项是第一轮设计收敛的高优先级缺口。它们会同时影响领域模型、API、前端和 Agent，必须先于大规模 DDL 与页面实现完成：

-   [x] 定义 Draft、Plan、Execution、Quality Check、Review 和 Publication 的状态机及允许迁移。详见 [21.4](#214-状态机设计总则)–[21.10](#2110-export-状态机)。
-   [x] 定义直接文档编辑与 Chat 修改同时发生时的 Revision、ETag/版本条件和冲突处理协议。详见 [21.7](#217-draft-与文档-revision-状态机)。
-   [x] 定义文档节点的来源分类：教材依据、教辅原文、高考原题、模拟题原题、教师资料、合规改编和 AI 补充内容。详见 [1.6](#16-首个-mvp-基准教学场景)、[6.5](#65-基准教学场景的-agent-约定) 和 [21.7](#217-draft-与文档-revision-状态机)。
-   [x] 定义教辅例题、高考真题与模拟题的来源元数据、定位方式、引用展示和失效处理。详见 [1.6](#16-首个-mvp-基准教学场景) 和 [21.8](#218-质量检查与数学验证状态机)。
-   [x] 定义哪些操作必须重新审批 Plan，哪些局部修改只需重新执行质量检查，降低不必要的人机协作摩擦。结论：教师编辑一律不重审 Plan；变更为 E0/E1/E2 三级，E2 才进入规划。详见 D1 §3。
-   [x] 定义 Draft 的自动保存、提交审核、撤回、放弃和恢复语义。详见 D1 §4。
-   [x] 定义发布后修正的规则：创建新 Material Version，不静默覆盖已发布版本。详见 [21.9](#219-publication-approval-与发布事务状态机)。
-   [x] 定义基准教学场景的可度量验收指标，包括生成时长、引用可追溯率、数学验证覆盖率和教师修改成本。详见 D1 §6（18 项指标，9 项阻断）。
-   [x] 为“三角函数讲义 + 教辅例题 + 高考真题 + 近期模拟题”建立端到端测试样例和固定评估数据集。规格详见 D1 §7；fixture 实体由 D6 落地。
-   [ ] 复核历史 K001–K024 清单。历史编号只作为参考，当前业务边界和已验证需求是模块定义的优先依据。

------------------------------------------------------------------------

# 第十一部分：建议实施路线图

## 29. 推荐阶段顺序

### Phase 0 — Design Baseline

-   [x] 汇总产品定位和主要架构。
-   [x] 明确核心业务模块。
-   [x] 明确主要技术栈方向。
-   [x] 定义跨模块状态机、并发协议和失效传播规则。
-   [x] 定义 Teaching Document Schema v1 与 Source/Citation Contract v1。
-   [x] 定义产品闭环协议：门禁、变更分级、Draft 生命周期、题源治理与验收指标（分册 D1）。
-   [ ] 恢复全部历史模块清单。
-   [ ] 建立统一项目设计文档版本管理。

### Phase 1 — Schema Registry Completion

-   [ ] Module Registry 完整核对。
-   [ ] Table Registry 完整核对。
-   [ ] Global Field Registry。
-   [ ] Relation / Constraint Registry。
-   [ ] State / Transition Registry。
-   [ ] Index / RLS / Permission Registry。
-   [ ] Migration Dependency Graph。
-   [ ] Schema Freeze。

### Phase 2 — Database Foundation

-   [ ] PostgreSQL 17 Bootstrap。
-   [ ] Roles / Extensions / Functions。
-   [ ] Identity / Shared Infrastructure。
-   [ ] Project / Material。
-   [ ] Knowledge Base。
-   [ ] Task / Agent。
-   [ ] Conversation。
-   [ ] Quality / Evaluation。
-   [ ] Admin Security。
-   [ ] 全套 RLS 与集成测试。

### Phase 3 — Backend Domain Services & API

-   [ ] Authentication / Authorization。
-   [ ] Project / Material Services。
-   [ ] Knowledge Ingestion / Retrieval。
-   [ ] Task / Agent Orchestration。
-   [ ] Conversation / SSE。
-   [ ] Quality / Math Validation。
-   [ ] Export Service。
-   [ ] OpenAPI 和 Contract Tests。

### Phase 4 — Agent Runtime

-   [ ] Harness Runtime Integration。
-   [ ] Chilon Agent Control Plane。
-   [ ] Tool Registry / Authorization Gate。
-   [ ] Plan Approval。
-   [ ] Execution / Recovery。
-   [ ] Evaluation / Observability。

### Phase 5 — UI/UX & Frontend

-   [ ] Design System。
-   [ ] Project Workspace。
-   [ ] Material Editor。
-   [ ] Chat。
-   [ ] Plan Review。
-   [ ] Knowledge Base。
-   [ ] Quality Review。
-   [ ] Export Center。

### Phase 6 — MVP Validation

-   [ ] 跑通“三角函数讲义 + 教辅例题 + 高考真题 + 近期模拟题”基准教学场景。
-   [ ] 验证教辅例题、高考真题与模拟题的来源可追溯性，以及原文、改编、AI 补充内容的可辨识性。
-   [ ] 端到端教学任务测试。
-   [ ] 数学正确性测试。
-   [ ] 教师可用性测试。
-   [ ] 文档导出质量测试。
-   [ ] 安全与隐私测试。
-   [ ] 性能与可靠性测试。
-   [ ] MVP Release Gate。

### Phase 7 — Post-MVP

-   [ ] pgvector 向量检索。
-   [ ] 更多学科。
-   [ ] 更丰富的题型和教学模板。
-   [ ] 多人协作与共享。
-   [ ] 更完整的 Agent Subagent 能力。
-   [ ] 高级质量评估和模型版本治理。

------------------------------------------------------------------------

# 第十二部分：关键架构决策记录（ADR 摘要）

## 30. 已确认决策

| ID | 决策 | 结果 |
| --- | --- | --- |
| ADR-001 | 产品定位 | AI Teaching Agent + Teaching Workspace |
| ADR-002 | 初始用户/学科 | 个人高中教师、中国高中数学 |
| ADR-003 | 初始课程体系 | 中国高考 |
| ADR-004 | MVP 内容 | Lesson / Exercises / Worksheet |
| ADR-005 | 人机协作 | Human-in-the-loop |
| ADR-006 | 编辑模式 | Chat + Direct Document Editing |
| ADR-007 | Database | PostgreSQL |
| ADR-008 | Schema 组织 | 单一 public Schema |
| ADR-009 | 技术栈 | FastAPI / SQLAlchemy Async / Alembic / Redis / Celery |
| ADR-010 | Agent Runtime | 复用 DeepSeek Harness，Chilon 保留业务 Control Plane |
| ADR-011 | 数据归属 | Owner Scope + Composite FK + RLS |
| ADR-012 | Material Version | Immutable |
| ADR-013 | Knowledge | 教师私有、审核后检索 |
| ADR-014 | Quality | AI 检查 + 教师最终审核 |
| ADR-015 | Export | DOCX + PDF |
| ADR-016 | Schema Source of Truth | Schema Registry |
| ADR-017 | DDL Generation | Deterministic Generator + Alembic |
| ADR-018 | Event Delivery | Transactional Outbox + At-least-once + Idempotency |
| ADR-019 | 首个 MVP 基准场景 | 高中数学“三角函数”：讲义 + 教辅例题 + 高考真题 + 近期模拟题（由 ADR-027 修订） |
| ADR-020 | 状态机权威性 | 服务端 PostgreSQL 状态 + CAS + 同事务业务事件/Outbox |
| ADR-021 | Draft 并发控制 | 不可变 Draft Revision + 乐观并发；MVP 不使用 CRDT |
| ADR-022 | 质量状态表达 | 检查过程状态与 Gate 结论分离 |
| ADR-023 | Material 发布审批 | K012 新增 `material_publication_approvals` |
| ADR-024 | Teaching Document | `chilon.teaching_document` v1.0.0；JSON Schema Draft 2020-12 |
| ADR-025 | Source / Citation | Citation Snapshot 嵌入 Draft Revision 与 Material AST，共同参与 Content Hash |
| ADR-026 | Citation 归属 | `material_knowledge_citations` 归 K009；Schema Registry 归 K012 |
| ADR-027 | 默认教学内容 | 四类来源：教材书（知识依据）、教辅书（例题）、高考真题、近期模拟题；移除教材例题；新增 `workbook` / `mock_exam` 来源与 `workbook_example` / `mock_question` 节点类型 |
| ADR-028 | 知识库分层 | 知识库分平台层与教师层；平台层提供四个默认分类（人教版数学教材、辅导书、高考题、模拟题）；分类用 `knowledge_categories` 表而非 ENUM，教师新增分类默认私有 |
| ADR-029 | 题目级知识单元 | 上传单元是整张试卷，引用单元是题目；新增 `knowledge_questions`；派生标注（题型、知识点、embedding）与原文事实分离，Citation 只能引用原文事实 |

## 31. 仍需冻结的决策

-   [ ] K002 Username 方案 B 的具体参数。
-   [ ] K001–K008、K010、K015–K020、K022–K023 的原始模块定义。
-   [ ] K024 是否为模块。
-   [ ] K011 完整实体清单。
-   [ ] Knowledge 与历史 K001 实体去重结果。
-   [ ] Execution Lease/Fencing Token 字段归属。
-   [ ] DeepSeek Harness 生产版本与隔离部署方案。
-   [ ] 前端 UI Component Library。
-   [ ] Object Storage 具体服务和部署形态。
-   [ ] 部署平台与生产拓扑。

------------------------------------------------------------------------

# 附录 A：重要共享实体唯一归属

| 实体 | 唯一归属 | 说明 |
| --- | --- | --- |
| `admin_audit_logs` | K002 | 通用管理员审计 |
| `admin_security_events` | K021 | 管理安全事件 |
| `admin_operation_requests` | K021 | 管理操作申请 |
| `admin_operation_approvals` | K021 | 管理操作审批 |
| `admin_operation_executions` | K021 | 管理操作执行 |
| `outbox_events` | K011 | 可靠事件投递基础设施 |
| `agent_activities` | K013 | 教师可见活动 |
| `conversation_events` | K013 | Conversation 实时事件 |
| `conversation_messages` | K013 | 对话消息 |
| `projects` | K012 | 教学专题 |
| `materials` | K012 | 教学材料身份 |
| `material_versions` | K012 | 不可变材料版本 |
| `material_drafts` | K012 | 可编辑草稿 |
| `material_draft_revisions` | K012 | 不可变草稿修订快照 |
| `material_publication_approvals` K012 |  | 单次发布授权与快照绑定 |
| `document_schema_definitions` | K012 | Teaching Document Schema Registry |
| Knowledge 核心实体 | K009（待历史去重） | 教师私有知识库 |
| `material_knowledge_citations` | K009 | 已发布内容与来源证据投影 |

跨模块只能通过 FK/API/事件协作，不能让多个模块同时拥有同一实体。

# 附录 B：重要数据流边界

## B.1 三种历史记录

| 记录 | 所属 | 用途 |
| --- | --- | --- |
| Conversation Messages | K013 | 教师与 Agent 的可见交流 |
| Business Events | K011/K013 等 | Chilon 业务状态与事件 |
| Harness Session Log | DeepSeek Harness Runtime | Runtime 内部执行诊断 |

不能将三类记录混为一个日志系统。

## B.2 关键事实来源

| 数据 | 权威来源 |
| --- | --- |
| 用户身份 | K002 Identity |
| 教师私有资料 | K009 Knowledge |
| 教学专题和材料 | K012 Material |
| 任务和执行状态 | K011 Task/Agent |
| 对话和实时事件 | K013 Conversation |
| 质量检查和数学验证 | K014 Quality |
| 管理操作审批 | K021 Admin Security |
| 可靠事件投递 | K011 Outbox |
| 文件二进制 | Object Storage |
| 缓存和实时通知 | Redis（非事实来源） |

# 附录 C：项目完成定义（Definition of Done）

Chilon 不应仅以“页面能打开”或“Agent 能回答”为完成标准。

一个可交付 MVP 至少满足：

1.  教师可以注册、登录并安全管理账户。
2.  教师可以创建 Project。
3.  教师可以上传资料并完成安全扫描、解析和审核。
4.  Agent 只能检索当前教师已批准的资料。
5.  教师可以创建教学任务并审核 Agent Plan。
6.  Agent 可以按批准计划生成 Lesson、Exercises 或 Worksheet。
7.  生成内容具有结构化 AST 和稳定节点 ID。
8.  数学验证结果能够区分通过、失败、不确定和不支持。
9.  Quality Check 能定位问题并追溯证据。
10. 教师可以直接编辑或通过 Chat 修改 Draft。
11. 发布操作会检查版本、审批和质量门禁。
12. 正式 Material Version 不可被静默覆盖。
13. 教师可以导出 DOCX/PDF。
14. Student Worksheet 不包含答案、解析和教师备注。
15. Owner 数据隔离、RLS 和权限测试通过。
16. SSE 断线后能够无遗漏恢复事件。
17. Outbox、幂等和任务恢复机制通过故障测试。
18. 备份恢复、监控告警和发布回滚流程已验证。
19. API、前端和数据库 Schema 有自动化契约测试。
20. 生产安全、隐私和数据生命周期检查完成。
21. 所有状态机通过合法/非法迁移测试，并发状态更新只允许一个 CAS 成功。
22. 直接编辑与 Chat Revision 的冲突协议通过并发测试，不发生静默覆盖。
23. 过期质量证据和失效审批无法通过发布门禁。
24. 发布幂等、Fencing Token、Outcome Unknown 对账和故障注入测试通过。

# 附录 D：设计评审记录

## D.1 2026-11-03 第一轮设计收敛

**当前判断：** 文档已经覆盖产品范围、主要技术栈、Agent Control Plane、数据库 Registry、安全隔离和实施路线。下一阶段的主要风险不是技术组件选得不够多，而是产品闭环、来源可追溯性和跨模块状态协议尚未闭合。

**本轮已记录的设计结论：**

1. 使用高中数学“三角函数”作为第一个 MVP 基准教学场景。
2. 基准输出为讲义、教材例题和高考真题练习，并明确区分原文、改编和 AI 补充内容。
3. 教材例题与高考真题必须可追溯，不能让模型只凭记忆生成并冒充原题。
4. 基准场景必须覆盖从资料选择、Plan 审批、生成、数学与质量检查、修改、发布到教师版/学生版导出的完整链路。

**下一阶段的四项优先工作：**

1. 定义具体、可度量的 MVP 黄金路径和验收指标。
2. 定义 Draft、Plan、Execution、Quality Check、Review、Publication 的状态机。
3. 定义直接编辑与 Chat 修改并发时的版本和冲突处理协议。
4. 定义教学材料的来源追踪与质量验收规则，避免“AST 合法”或“数学验证通过”被误认为材料已经可用。

**模块恢复原则：** K001–K024 的历史编号仍是线索，但不再是设计推进的硬阻塞。无法验证的旧模块不得被凭空补造；以当前基准教学场景、已验证业务流程和安全要求重新核对模块边界。

## D.2 2026-11-03 状态机设计收敛

**设计责任：** 用户明确授权由项目设计方全权负责状态机设计。已形成的设计位于 21.4–21.12，并作为后续 Schema、API、前端 Agent 执行的统一协议。

**已冻结的设计结论：**

1. 状态以 PostgreSQL 中的服务端状态为唯一事实来源，使用 CAS、事件和 Outbox 保证并发与可追溯性。
2. Task、Plan、Execution、Draft、Quality 和 Export 各自拥有独立状态机，跨模块只通过固定版本/Hash 和业务事件协作。
3. Task `completed` 表示 Agent 已交付 Draft，不表示 Draft 已审核或发布。
4. Draft 使用不可变 `material_draft_revisions`；编辑和 Chat 均使用 Revision/ETag 乐观并发，MVP 不使用 CRDT，不允许最后写入者胜出。
5. 质量检查过程状态与 Gate 结论分离；只有新鲜、成功且满足政策的质量与数学证据可以参与发布。
6. Material 发布使用单次消费的 `material_publication_approvals` 和短 PostgreSQL 事务；发布成功创建不可变 Material Version。
7. 超时或失联进入 `outcome_unknown` 并先对账，禁止直接重复调用有副作用的工具或任务。

**后续尚未完成的实现前设计：**

1. 将状态枚举、字段、约束、索引和关系落入 Global Field/Relation/Constraint Registry。
2. 定义每种状态的允许动作、错误码和面向教师的状态文案。
3. 定义基准教学场景的量化验收阈值。
4. 建立状态机表驱动测试、并发测试和故障注入测试。
5. 以状态机协议为输入冻结 API Endpoint 与 SSE Event Envelope。

## D.3 2026-11-03 Teaching Document 与 Citation 契约冻结

**设计责任：** 用户授权由项目设计方完成教学内容模型与来源协议设计。

**本轮已交付：**

1. `Teaching Document Schema v1.0.0`，使用 JSON Schema Draft 2020-12。
2. `Source Citation Contract v1.0.0`，定义来源类型、Locator、Excerpt、Retrieval、Usage、Rights 和 Integrity。
3. 20 类块节点与 4 类行内内容，覆盖讲义、教材例题、高考真题、练习、答案、解析和 Worksheet 作答区。
4. Teacher、Student、Internal 三种 AST 投影规则。
5. 教材例题与高考真题的来源、原文/改编/AI 补充辨识规则。
6. 来源生命周期、撤回/删除、旧引用保留和 Citation Tombstone 规则。
7. Citation 与 Document Schema Registry 的唯一归属。
8. 可执行的基准场景 JSON 样例。

**验证结果：**

-   两份 JSON Schema 通过 Draft 2020-12 Meta-schema 校验。
-   `schemas/trigonometry_golden_path.v1.example.json` 通过两份 Schema 的实例校验，错误数为 0。
-   JSON Schema 无法表达的跨节点引用、唯一 ID、答案关联和 Profile 可见性约束已写入 20.9、20.10 和 21.1。

**下一步设计输入：** 在实现 Validator 时，同时实现 20.9 的语义校验、21.1 的 Citation/Rights 门禁，以及 Student Profile 的 AST 级过滤；不能仅依赖 JSON Schema。

## D.4 2026-11-04 产品闭环协议（D1）

**本轮交付：** 新建分册 [D1 产品闭环协议](design/Chilon_Design_Volume_D1_Product_Closure_Protocol.md)，补齐 §28.8 的四条未完成项。

**已冻结的设计结论：**

1. 建立七道门禁（G1–G7）与八条闭环不变量（I1–I8），作为 D2–D6 不得破坏的性质。
2. **编辑与审批分权**：教师的一切直接编辑与 Chat 局部修改都不重新审批 Plan；Plan 审批只约束 Agent。安全性由发布与导出门禁集中保证。
3. 变更分为 E0 内容编辑、E1 来源变更、E2 范围扩展三级，判定表机械化；级别不拦截保存，只在门禁处生效。
4. E1 不引入新审批实体：新增来源由 K009 审核/权利确认与发布审批的 `citation_snapshot_hash` 绑定共同覆盖。
5. Draft Revision 分为 `checkpoint` 与 `autosave`；自动保存不改变 Draft 状态，MVP 不做压缩。
6. 新增 `cancel-check` 迁移（`checking` → `editing`），并回写 §21.7.1。
7. `source_requirements` 与守卫 R1–R7 定义题源治理；可行性（G2）与合规性（G6/G7）分离。
8. 18 项验收指标，其中 9 项为阻断级；端到端 fixture 规格与断言集固定。

**对既有结论的两处修正：**

- `schemas/trigonometry_golden_path.v1.example.json` 此前“实例校验错误数为 0”仅指 JSON Schema 层面；该样例实际违反 20.9 规则 4（选择题仅 1 个选项）。已补齐 A/B/C/D 四个选项，并拆为三个 `purpose` 正确的 `section`。
- §20.9 新增规则 18（`section.purpose` 与子节点一致），§21.5.1 补充 Task 完成证据不构成发布门禁证据的澄清。

**新增可执行资产：** `design/check_golden_path.py`，覆盖 20.9 中 JSON Schema 无法表达的语义规则，可独立运行。

## D.5 2026-11-04 文档排版规范化

**本轮目标：** 修正排版层的可读性与渲染兼容性缺陷，不改动任何设计结论。全文内容零删减。

**已完成的修改：**

1. **10 张 pandoc 简单表转为标准竖线表。** 原表是按等宽显示对齐的，其中 §12 模块总览、§26.10 字段样例、附录 B.1 三张表在行间夹了空行、单元格靠续行对齐，在任何 Markdown 渲染器里都不成表。转换时保留全部单元格文本，含续行合并。
2. **生成目录。** 覆盖 12 个部分、31 个章节与 4 个附录，共 57 个锚点链接。
3. **新增 §0.4 部分与章节对照**，解决“第X部分”与数字章节号两套编号并行造成的定位困难。
4. **交叉引用改为锚点链接。** “详见 [21.8.2](#2182-检查结论与发布门禁)” 这类散文引用现在可直接跳转。
5. **标点规范化。** `--` 统一为 `–`，`---` 统一为 `—`（原为 pandoc 转换残留，在渲染器中会显示为字面连字符）；直引号统一为中文弯引号。行内代码与链接目标不做转换。
6. **合并句中断行。** 原文档按 72 列硬折行，Markdown 的软换行会渲染成空格，导致中文句子中间出现空隙。现按段合并为单行；拉丁字符与中文交界处保留一个空格，代码块、表格、标题、列表项与硬换行不参与合并。
7. **§28 台账约定。** §28.1 改为指向模块章节的指针表，消除同一待办在两处措辞不同的漂移风险。

**可复现的工具：**

| 脚本 | 作用 |
| --- | --- |
| `design/doc_audit.py` | 输出行数、标题层级、表格语法、折行、引号等编排指标 |
| `design/check_docs.py` | 校验竖线表列数与代码围栏配对 |
| `design/gen_toc.py` | 重建目录并校验内部锚点，报告断链数 |
| `design/normalize_text.py` | 标点规范化与句中断行合并，保护代码、链接与列表边界 |
| `design/verify_no_text_loss.py` | 对比两次快照的正文（忽略空白），证明排版改动未丢内容 |
| `design/check_golden_path.py` | 校验黄金路径样例的 20.9 语义规则 |

修改后 `check_docs.py` 与 `gen_toc.py` 均报告 0 断链、0 表格列数错误；`verify_no_text_loss.py` 证明本轮正文（忽略空白）与改动前逐字符一致。后续修改文档后应重跑这四支脚本。

## D.6 2026-11-04 状态机机器可读化

**动因：** §21 的 13 个状态机此前只存在于散文表格中。人工实现需要解析表格，且同一状态在不同章节重复出现，措辞差异难以发现。改为机器可读契约后，实现、测试与文档可以相互校验。

**本轮交付：**

1. `schemas/state_machines.v1.json`：13 个聚合、101 个状态、136 条迁移、8 组值域、11 个跨模块事件、9 条 Gate 规则。
2. `schemas/state_machines.v1.schema.json`：该文件的 JSON Schema。
3. `design/check_state_machines.py`：校验跨字段一致性，并与本文档交叉核对。
4. 本文档新增 §21.13，规定双向同步规则。

**校验项**（JSON Schema 无法表达的部分）：

- 状态名在聚合内唯一；初始态与终止态均已声明且不相交。
- 每条迁移的 `from`/`to` 均为已声明状态。
- 终止态不得有出边（对应 SM-R05）。
- 所有状态从初始态可达；不存在完全不参与迁移的状态。
- 每个状态名在本文档中以行内代码出现。
- §21.4.1 的终止态列与 Registry 逐项一致。

**由此发现的真实缺陷：**

§21.4.1 把 Export 的 `ready` 列为终止态，但 §21.10 允许 `ready` → `expired`。终止态有出边违反 SM-R05。已修正 §21.4.1 为 `failed`、`cancelled`、`expired`，并注明原因（Export 的 `ready` 可因保留期限转 `expired`，因此不是终止态）。

**为后续分册提供的输入：**

- D4：136 条迁移的 `trigger` 已具名，可直接映射为动作接口与错误码；命名在 D4 冻结前仍可调整。
- D5：每个聚合的 `status`、`state_version` 字段与允许动作集合已确定。
- D6：表驱动测试的合法迁移集与非法迁移集可从 Registry 直接生成，无需从文档抄写。

## D.7 2026-11-04 动作层（分册 D4）

**本轮交付：** 新建分册 [D4 动作、错误码与教师可见文案](design/Chilon_Design_Volume_D4_Actions_Errors_And_Copy.md)，把 §21 的状态机翻译成教师可执行的动作层。

**已冻结的设计结论：**

1. **122 条动作**由 `state_machines.v1.json` 自动派生，每条迁移恰好被一个动作认领；教师可见 23 条，`system` 80 条、`worker` 19 条全部隐藏。
2. **23 组复合命令**：一次教师点击要跨多个聚合原子更新。例如 `approve_plan` 同时推进 Task、Plan Version、Plan Approval 三个聚合，必须在同一事务完成，否则会出现“Task 说已批准、Approval 仍是 pending”的不可自愈分裂态。
3. **18 个错误码**，409 与 422 的语义按“重试是否可能成功”划分；错误响应必须带回 `allowed_actions`，让前端能自愈。
4. **74 条教师可见状态文案**：区分技术失败与内容失败，危险操作说明后果，文案不复述状态名。
5. 27 个内部状态（Agent Run / Step / Tool）不产生独立文案，只以 Activity 聚合呈现，符合 SM-R10。

**三条容易误读的边界**（已写入 D4 §2.1）：

- 计划批准是 Task 级动作，Plan Version 自己只有“拒绝”；
- 没有“批准发布审批”按钮，批准草稿即批准发布；
- 导出重试不产生状态迁移，它是新建记录。

**新增可执行资产：**

| 文件 | 作用 |
| --- | --- |
| `schemas/actions.v1.json` | 动作、复合命令、错误码的机器可读副本 |
| `schemas/actions.v1.schema.json` | 该文件的 JSON Schema |
| `design/check_actions.py` | 覆盖检查 + 复合命令一致性 + 错误码引用 + 自测 |

`check_actions.py` 报告：122 条动作、23 条教师动作、23 组复合命令，每条迁移恰好被认领一次；注入的 4 个缺陷（删除动作、教师动作缺标签、引用未知错误码、迁移被重复认领）全部被检出。

## D.8 2026-11-04 接口层（分册 D5）

**本轮交付：** 新建分册 [D5 API 与 SSE 契约](design/Chilon_Design_Volume_D5_Api_And_Sse_Contract.md)，把 D4 的动作层落成接口形状。

**已冻结的设计结论：**

1. **55 个接口**：23 个动作接口与教师动作一一对应，32 个资源接口覆盖黄金路径的读写。动作路径固定为 `/{资源}/{id}/actions/{kebab-case 动作名}`，动作名直接来自 D4 的 `trigger`，可机械化对照。
2. **复合命令是一个接口，不是三个**。`approve-plan` 一次写 Task、Plan Version、Plan Approval。这否定了“每个聚合各有一个 REST 资源、各自改自己”的常见设计。
3. **三种锁各管一段**：`expected_state_version` 管状态推进，`If-Match` 管内容编辑，`Idempotency-Key` 管重复提交。三者不可互换。
4. **`allowed_actions` 是每个动作响应与错误响应的必需字段**。前端不自行推导按钮可用性，避免 D3 与 D4 各写一份状态判断。
5. **SSE 只做通知，PostgreSQL 是事实来源**。断线按 `Last-Event-ID` 回放，客户端另以 `GET /activity` 兜底对账。

**明确押后的接口**（D5 §9）：账户、知识审核队列、管理员、批量操作、协作。理由：形状依赖尚未冻结的 K002/K021，提前设计会锁定错误假设。

**新增可执行资产：**

| 文件 | 作用 |
| --- | --- |
| `schemas/api_surface.v1.json` | 55 个接口、SSE 契约、通用约定的机器可读副本 |
| `design/check_api_surface.py` | 动作↔接口覆盖、路径参数、错误码子集、路径冲突 + 自测 |

`check_api_surface.py` 报告：23 个动作接口全部命中教师动作，55 个接口无路径冲突，错误码全部来自 Registry；注入的 4 个缺陷（删除接口、重复路径、引用未知错误码、资源路径与动作冲突）全部被检出。

## D.9 2026-11-04 信息架构与门禁参数化（分册 D2）

**本轮交付：** 新建分册 [D2 信息架构与导航树](design/Chilon_Design_Volume_D2_Information_Architecture.md)，确定导航层级、页面分档、门禁策略与走查方法。

**已冻结的设计结论：**

1. **三层信息架构**：全局 / 项目内 / 材料内，深度上限 3。材料是二级资产而非任务的子项——任务是一次生成过程，材料是长期资产。
2. **13 个页面分三档**：黄金路径 5 个（承载 G2–G7）、骨架 5 个、押后 3 个。押后页面在 MVP 期间不注册路由，避免半成品入口被点到。
3. **门禁参数化**：七道门禁不写死在流程里，按“任务类型 × 门禁”查策略表。G4–G7 恒为 `required`，只有 G3 计划审批可按任务类型自动通过。
4. **门禁数 ≠ 点击数**：七道门禁分布在 5 个页面，完整生成流程点击预算 4 次，由校验器强制。
5. **反馈分三类处置**：认知类改文案、效率类合并步骤或调任务类型默认值、信任类加证据展示。最常见的错误是把信任问题当效率问题，于是加确认弹窗。

**为什么只让 G3 自动化：**

G4 是数据结构问题（只有过与不过）、G5 已有 S1 人工例外通道、G6 就是教师最终审核权本身、G7 涉及权利与答案泄漏。四者都不存在“有条件放行”的空间。只有 G3 在“不引入新检索来源”时风险有界，可以代批且全程可见。

**教师走查脚本**（D2 §9）：4 张场景卡（从零备课、改已有讲义、课堂小测、只有纸质资料），每卡附必问问题与观察点，并给出反馈到设计改动的映射表。走查用线框图即可，不需要产品或账号，1 小时/人。

**新增可执行资产：**

| 文件 | 作用 |
| --- | --- |
| `schemas/navigation.v1.json` | 13 个页面、路由、读接口与动作映射、5 种任务类型的门禁策略 |
| `design/check_navigation.py` | 页面动作∈教师动作、读接口∈接口面、门禁取值合法、G4–G7 锁定 + 自测 |

`check_navigation.py` 报告：13 个页面（黄金路径 5 / 骨架 5 / 押后 3）、5 种任务类型、G4–G7 锁定；注入的 4 个缺陷（任务类型缺门禁、G6 被设为自动、页面引用不存在动作、导航指向不存在页面）全部被检出。

------------------------------------------------------------------------

## D.10 2026-11-04 教师走查包

**动因：** D3 是最大的分册，也是最难返工的一份。用走查结果去写它，比写完再改便宜。走查只需极简线框，不需要可运行的产品。

**交付物：**

| 文件 | 内容 |
| --- | --- |
| [design/walkthrough/Walkthrough_Kit.md](design/walkthrough/Walkthrough_Kit.md) | 主持人指南：60 分钟流程、逐字开场白、4 张场景卡、记录表、反馈三分法、禁忌清单 |
| [design/walkthrough/wireframes.html](design/walkthrough/wireframes.html) | 8 个极简线框（自包含、可打印、标注可切换、打印时自动隐藏标注） |

**走查要验证的三件事：**

1. 七道门禁的顺序是否可接受——重点看场景 A 的计划审批页，老师能不能说清“在批准什么”。
2. “编辑不重审计划”能否被感知——场景 B 直接问“你觉得这次还需不需要重新批准计划”。
3. “自动批准计划”能否被接受——场景 C 提供一个 G3 = `auto` 的版本做对照。

**反馈处置方法**：分认知类、效率类、信任类三类，对应改文案、合并步骤、加证据。最常见的错误是把信任问题当效率问题处理，于是加确认弹窗——流程更长，信任没变。

**走查后的产出**：每个场景一张记录表、一份“必须改”清单、一份“待观察”清单，以及一句话结论：**七道门禁的顺序是否需要调整**。该结论回写 D2 §5/§6，再冻结 D3。

## D.11 2026-11-04 默认教学内容变更（取代 D.1 第 2–3 条、D.3 的节点覆盖描述）

**动因：** 产品方决定移除默认模板中的“教材例题”，教学内容改为四类来源：教材书、教辅书、高考题、近期模拟题。

**本轮的判断与结论：**

1. **教材书仍在用，但角色变了**：从“提供例题”改为“提供知识依据”（定义、定理、公式、课标要求）。例题改由教辅书承担。
2. **不删除 `textbook_example` 节点类型**，只从默认模板移除。删除会让已定义类型失效并破坏向后兼容；保留它，教师仍可手动使用。
3. **新增两类来源与两类节点**：`workbook` / `mock_exam` 来源；`workbook_example` / `mock_question` 节点。
4. **“近期”定近 3 年（含当年）**，通过 `source_requirements.year_min` 表达，由 G1 确定，不写死在代码里。
5. **权利处理不变**：四类来源的 `rights.status` 默认 `unverified`，教师确认后才能发布或导出。

**契约变更：**

| 文件 | 变更 | 兼容性 |
| --- | --- | --- |
| `teaching_document.v1.schema.json` | `schema_version` 接受 `1.0.0` 与 `1.1.0`；`provenance.kind` 增加两个值 | 向后兼容（只放宽，不移除） |
| `source_citation.v1.schema.json` | `source_type` 增加 `workbook`、`mock_exam`；两者各自的必需元数据 | 向后兼容 |
| `trigonometry_golden_path.v1.example.json` | 例题改为教辅来源；新增模拟题引用与题组 | 样例更新 |

**为什么是 minor 而不是 major**：只新增了允许值，没有改变任何既有字段的语义或必填性。已发布的 1.0.0 文档仍然有效，不需要迁移（符合 §20.11）。

**同步修正的位置**：§1.6（新增 1.6.1 四类来源表）、§6.5、§20.7、§20.8、§20.9（规则 8–10）、§21.1.1、§21.1.2、§21.1.4、§28.8、§29、ADR-019、ADR-027；D1 §5.1/§5.2/§7.2/§7.3/§7.4；D2 §9.2；走查包的场景卡 A 与线框第 1、2 屏。

**历史记录不改写**：D.1、D.3 保留原文，本条明确取代其中与教学内容构成有关的表述。

## D.12 2026-11-04 需求门槛放宽与知识库分层

**动因：** 产品方补充三条要求：年级固定高三；默认不考虑难度；知识库由项目方提供四个默认分类，教师也可新增分类或沿用旧分类上传。

**已冻结的结论：**

1. **G1 判据放宽**。必填项缩为：年级、专题、内容类型、题量、题源构成。课时/篇幅、难度、资料范围有了默认值，不再触发澄清。默认值：课时 1 课时、资料范围 = 平台知识库 + 教师已审核资料。
2. **难度退出默认维度**。Agent 不按难度生成、筛选或加权；`difficulty_max` 与 `allow_high_difficulty` 从 `source_requirements` 移除，守卫 R3 废止。教师显式要求难度时按普通过滤条件处理，不再是硬门禁。
3. **知识库分两层**（ADR-028）：
   - 平台层 `scope = platform`：项目方提供，默认四个分类——人教版数学教材、辅导书、高考题、模拟题。
   - 教师层 `scope = teacher`：教师上传，可沿用默认分类，也可新建分类。
4. **分类用表不用 ENUM**：`knowledge_categories` 承载分类，四个默认分类映射到 `source_type`。用 ENUM 会让“教师新增分类”无法实现。
5. **默认教材为人教版数学教材**：教师未指定教材时，取平台层的人教版作为知识依据来源。

**这改变了一个前提**：原设计的 G2 经常因为“教师没上传资料”而返回 `capability_gap`。有了平台层，`capability_gap` 变成真正例外——只在跨学科、超范围或冷门题源时出现。这是好事，但也意味着**平台层的资料覆盖率成了 MVP 的关键依赖**，不再是“教师自己解决”。

**阻塞项（需法务/产品确认）：**

平台四类资料的授权范围是否覆盖**课堂使用与学生版导出**。若只覆盖教师个人备课，则平台来源的 `distribution_scope` 必须限制为 `private_teacher`，学生版导出会被 G7 阻断——而学生版恰恰是这个产品的主要交付物。这条不确认，G7 的行为无法最终冻结（见 §14.1.2）。

**同步修正**：§1.6.1、§14.1（新增 14.1.1/14.1.2）、ADR-028；D1 §1.2（G1 判据）、§5.1（结构去掉难度）、§5.2（R3 废止）。

## D.13 2026-11-04 题目级知识单元与派生标注

**动因：** 产品方确认两件事：教师新增分类默认私有；知识库按**整张试卷**上传，之后 embedding 做题型分类再入库。

**已冻结的结论：**

1. **上传单元是文件，引用单元是题目。** 新增 `knowledge_questions`，把试卷切分出的每道题作为检索与引用的最小单位。没有它，G2 无法回答“平台库里有多少道数列解答题”——只能按文档数猜。
2. **原文事实与派生标注分离**（ADR-029）。题干、题号、页码、字符区间、文件 Hash 属于原文事实，可作引用证据；题型、知识点、难度、embedding 属于派生标注，可被教师修正且**永不作为引用证据**。
   - 这是本轮最重要的一条：如果题型分类被当成来源事实，“这道题是数列解答题”就变成了模型判断而非原文证据，I1（无来源不成原题）会被绕过。
3. **题型分类优先规则、模型兜底。** 卷面结构（第 I 卷选择题、第 II 卷解答题）先判；规则不确定时才用模型。分类结果带 `classification_source ∈ {rule, model, teacher}`，教师修正后原标注保留为历史。
4. **embedding 的用途限定**。向量作为派生数据存储，用于题型分类辅助；**检索主路径仍是关键词 + 元数据**，与 §4/ADR-011 的 DEFERRED 定位一致。向量可随时重建，不影响已发布 Citation。
5. **教师新增分类默认私有**，平台分类全局；一个来源属于一个分类，一道题可带多个知识点标签。

**最大的风险不在 embedding，在切分。**

整张试卷 → 题目的切分是整条链的**单点依赖**：

- 跨页题（题干在第 3 页、选项在第 4 页）会让字符区间断裂；
- 答案册与试卷分离时，“答案位置”无法用同一文档的字符区间表达；
- 切分错一道，后面的标注、检索、引用全部错位，而且**引用看起来仍然合法**——这是最危险的地方。

因此切分结果必须人工可校对（合并/拆分/改题号），并且 Citation 必须能覆盖多段区间。当前 `source_citation` 的 `locator` 只支持单段 `char_start`/`char_end`，**这是已知缺口**，需要在 Schema 下一次 minor 升级中扩展为多段。

**表格与分类的落地**（§14.2 由 9 张扩到 13 张）：新增 `knowledge_questions`、`knowledge_categories`、`knowledge_annotations`、`knowledge_question_embeddings`。

**仍需你确认**（同 D.12 的阻塞项）：平台四类资料的授权是否覆盖课堂使用与学生版导出。

## D.14 2026-11-04 题型分类只存卷面层

**动因：** 产品方确认题型分类只存一层，存卷面类型。

**已冻结的结论：**

1. **卷面题型四类**：`single_choice`、`multiple_choice`、`fill_blank`、`free_response`。
2. **为什么是四类**：新高考数学卷面区分单选（第 1–8 题）与多选（第 9–12 题）。只存“选择题”会丢失原卷结构，并让 AST 的 `single_choice` / `multiple_choice` 校验失去依据。
3. **不存内容题型**（计算/证明/应用）：教师口语里的“大题”“选择题”指卷面结构；内容题型由生成器写 AST 时按题目内容判定，属于生成期判断，不进知识库标注层。
4. **映射由 §20.9 规则 19 约束**：卷面题型限定 `question_type` 的取值集合，并决定 `options` 是否必须存在。三对一映射，只有 `free_response` 对应四种 AST 类型。

**这个决定减少了什么：**

- 知识库标注层少一个字段、少一套需要模型的判断；
- 检索过滤维度从两套变一套，教师说“十道解答题”时直接命中；
- 派生标注里“题型由模型判定”的风险大幅下降——单选/多选/填空/解答由卷面结构规则可判，不需要模型猜。

**代价**：生成器在写 AST 时必须再判一次内容题型（解答题是计算还是证明）。这一步如果判错，AST 里 `calculation` 与 `proof` 会标错，但不影响来源真实性，只影响标签准确性，且属于可修正的生成期标注。

**同步修正**：§14.4.2（分类规则）、新增 §14.4.3（卷面题型定义）、§20.9（新增规则 19）、§14.5（TODO 勾掉题型体系）。

## D.15 2026-11-04 Citation 定位支持跨段

**动因：** 整张试卷上传后，跨页题（题干在第 3 页、选项在第 4 页）无法用单段 `char_start`/`char_end` 表达。这是 D.13 记录里明确标注的已知缺口。

**变更：**

- `source_citation.v1.schema.json` 的 `locator` 现在接受两种形式：
  - 单段：`char_start` + `char_end`（原有形式，不变）；
  - 跨段：`segments[]`，每段自带字符区间与页码，至少 2 段。
- 两种形式至少提供一种（`anyOf` 约束）。
- 这是**非破坏性扩展**：只新增可选能力，没有改变任何既有字段的语义或必填性，已发布 Citation 全部仍然合法。

**校验侧同步：**

- §20.9 规则 16 重写为“定位必须自洽”，区分单段与跨段，并要求跨页题必须用 `segments`。
- `design/check_golden_path.py` 的规则 16 相应扩展：校验每段区间、每段页码，并拒绝“只有一段却用 segments 形式”。

**为什么不用“多个 Citation 拼起来”绕过：** 一个 Citation 代表**一条来源证据**。同一道题的题干与选项属于同一条证据，拆成两条 Citation 会让引用计数、Hash 校验和权利判定各算一次，语义就错了。

**下一步：** D5 的知识库接口仍停留在题目级改造之前（只有文档级检索），需要补题目级检索、分类过滤与切分校对接口。

## D.16 2026-11-04 知识库接口补齐（D5 §3.1）

**动因：** K009 连续三次改造（文件级→题目级、加分类、题型定层）之后，D5 的知识库接口还停在文档级检索，接口面与设计脱节。

**新增 8 个接口**（D5 §3.1）：

| 接口 | 作用 |
| --- | --- |
| `GET /knowledge/questions` | 题目级检索，支持分类、卷面题型、年份、scope 过滤 |
| `GET /knowledge/questions/{id}` | 题目详情、切分位置与派生标注 |
| `GET /knowledge/sources/{id}/questions` | 某张试卷的切分结果 |
| `POST /knowledge/questions/{id}/segments` | 切分修正（合并 / 拆分 / 改题号） |
| `POST /knowledge/questions/{id}/annotations` | 标注修正（题型 / 知识点） |
| `GET /knowledge/categories` | 分类列表（平台 + 私有） |
| `POST /knowledge/categories` | 新建教师私有分类 |
| `POST /knowledge/sources` | 提交上传资料进入审核 |

**顺带补了一个原有缺口**：`POST /knowledge/sources` 在 D5 §7.1 的上传流程里被引用，但从未进入接口清单。这类“文中引用了但清单里没有”的漂移，只有机械对照才能发现。

**三条约定：**

1. **检索单位是题不是卷。** `GET /knowledge/search` 保留为文档级粗检索，选题一律走 `/knowledge/questions`；`source_requirements` 的计数与 G2 判断都按题计。
2. **切分与标注修正不用 `/actions/` 路径。** 附录 A 规定 `/actions/` 只用于 D4 教师动作；这两个是知识库编辑操作，不推进任何状态机。
3. **标注修正不改原文。** 新版本写入 `knowledge_annotations`，原标注保留；题干与定位区间不能用这两个接口修改。

**接口总数**：55 → 63（23 个动作接口 + 40 个资源接口）。

**同步修正**：D5 §0.1、§3（含新增 §3.1）、§7.1、§8、§9；`schemas/api_surface.v1.json`。

## D.17 2026-11-04 平台权利策略三档化与未决看板

**动因：** 平台资料授权是需要法务确认的事实，设计侧无法假定；但把它挂在“待确认”上会阻塞整个学生版设计。改为**策略档位**：结论回来只改配置。

**三档策略**（§14.1.2）：

| 档 | 摘录 | 改编 | 学生版导出 |
| --- | --- | --- | --- |
| `A_classroom` | 允许 | 允许 | 允许 |
| `B_private_excerpt` | 允许 | 禁止 | 阻断 |
| `C_private_adapt` | 允许 | 允许 | 阻断 |

**三条判断：**

1. **未确认时默认按 C 运行**。宁可先挡住学生版，不可先放开——放开后产生的合规问题无法回收，而挡住只是暂时少一个功能。
2. **档 A 是学生版成立的前提**，不是开关级别的差异。若落 B/C，学生版只能由教师自有资料与不基于平台原文的 AI 自编题构成，§1.6 的黄金路径与 D1 的 G7 都要重做。
3. **六个可直接发给法务的问题**已写入 §14.1.2，不要求对方读设计文档就能回答。

**新增未决看板**：[design/OPEN_ITEMS.md](design/OPEN_ITEMS.md)。按“只有产品方能定”与“设计侧可继续”分开，避免互相等待；含走查的降级阶梯与 D3 的冻结条件。

**D3 的冻结条件**（写入看板）：至少 1 份「场景 A」的教师走查记录。若完全无法安排，D3 只能标 `PROPOSED`，不得标 `FROZEN FOR IMPLEMENTATION`。

## D.18 2026-11-04 授权结论 A 档与走查状态

**一、平台资料授权：A 档（已确认）**

法务确认：四类资料的数字复制权已取得；摘录、改编、分发学生、与教师资料混排均允许；撤回时清除已发布摘录非必须。

由此：

1. `platform_rights_policy = A_classroom`，平台来源 `rights.status = licensed`、`distribution_scope = classroom`。
2. **平台知识库可独立支撑黄金路径**，教师无需先上传资料即可出讲义与练习。
3. **来源撤回不触发强制 Redacted Version**，走 Tombstone 路径（§21.1.5 规则 5 已改）。
4. 三档策略保留为配置，用于未来新增来源类型或更换授权时降档。

**二、走查状态：产品方确认可接受，未经教师验证**

走查未由高中数学教师执行。产品方查看草图后确认可接受。

**记录这一点的原因不是为了追责，是为了不让它变成“已通过”。** D3 可以冻结，但必须带风险清单——以下 5 条假设从未被真实教师检验：

1. 教师能看懂「计划审批」页在批准什么（风险最高；若不成立，G3 就是纯摩擦）。
2. 七道门禁的认知负荷可接受。
3. 教师信任“学生版已剔除全部答案”，不会逐题核对。
4. S0–S3 分级能被理解，不会盲点“忽略”。
5. “项目 / 材料 / 草稿”这套术语符合教师日常说法。

这 5 条写入 D3 首页，测试版上线后第一件事就是验证。

**同步修正**：§14.1.2、§21.1.5、[design/OPEN_ITEMS.md](design/OPEN_ITEMS.md)。

## D.19 2026-11-04 教师走查结果与导出预览

**一、走查结果（1 位教师 / 教高三 / 教龄 3 年 / 场景 A）**

通过：计划审批页可理解、无可感知的门禁摩擦、无“不如自己写”、术语一致、检查证据被主动查看、可接受等待 20 分钟内。

未覆盖：场景 B（改讲义）、C（课堂小测）、D（纸质资料）。其中**场景 B 承载 D1-03 这条最核心的判断——教师编辑不重审 Plan**，目前仍只有推理支撑。

**二、被证伪的一条假设**

导出页原本的做法是给一句自证：`已核对：24 个内容块，答案类 0 个`。教师反应是“我得自己下载看一下”。

这印证了一条通用原则：**系统声明不能替代可验证性**。教师不信“我们核对过了”，只信“我自己看到了”。这不是效率问题（加个确认弹窗只会更烦），是信任问题，只能靠证据解决。

**三、设计改动**

1. **导出改为两步：先预览、后下载。** 渲染产物生成后提供浏览器内预览（`GET /exports/{id}/preview-url`），教师翻看确认后再下载。
2. **预览与下载使用同一份渲染产物**，避免“预览是好的、下载的不一样”这种更糟的情况。
3. **删除自证式文案。** 不再写“已核对 0 个”，改为让预览本身说话；保留剔除数量作为辅助信息，但不作为可信性依据。
4. DOCX 需先生成 PDF 预览件；预览件与正片同源。

**四、风险清单更新**

| 假设 | 状态 |
| --- | --- |
| 计划审批页可理解 | 已验证（1 人） |
| 七道门禁负荷可接受 | 已验证（1 人） |
| 术语符合教师习惯 | 已验证（1 人） |
| S0–S3 分级可理解 | 部分验证（证据被点开） |
| 学生版可信 | **已证伪** → 改为预览方案，待再验 |

**同步修正**：§OPEN_ITEMS A2、D5 §3/§7.3、`schemas/api_surface.v1.json`。

## D.20 2026-11-04 页面级规格（分册 D3）

**本轮交付：** 新建分册 [D3 页面级规格与交互](design/Chilon_Design_Volume_D3_Page_Specifications.md)，把 5 个黄金路径页面说到可实现的程度。

**已冻结的结论：**

1. **三栏布局按断点退让**：≥1440 三栏、1280–1440 收窄、1024–1280 右栏改抽屉、<1024 单栏只承诺查看与审批。
2. **`allowed_actions` 是按钮的唯一来源**：前端不再自行判断状态。按钮缺席时不显示灰按钮——避免制造“为什么不能点”。
3. **四种通用状态强制实现**：加载（骨架屏）、空（带出口）、错误（可恢复动作）、冲突（显式对比面板）。
4. **冲突不静默、不自动合并**：查看差异 / 用最新 / 另存副本三选一；结构性冲突只能人工处理。
5. **超时不等于失败**：先提示“正在确认结果”，再轮询聚合；`outcome_unknown` 期间禁止重复提交（SM-R09）。
6. **学生视图从 AST 投影**，不在前端隐藏——这是 A4 要求，也是验收点。

**落实走查发现的两处改动：**

- **导出改两步：先预览、后下载**（§2.5）。教师不信“系统已核对”，只信“我自己看到了”；新增 `GET /exports/{id}/preview-url`，预览与下载同源。
- **删除自证式文案**，改为让预览本身说话；剔除数量降为辅助信息。

**关于未验证场景的处理原则**（写入 §0.3）：涉及场景 B/C/D 的页面先按最保守形态上线，等验证后再放宽，不一次做到最简。

**交付给 D6 的 12 条验收点**（§6），覆盖按钮来源、通用状态、冲突、投影、预览与断线一致性。

**分册状态**：`FROZEN FOR IMPLEMENTATION`，但附未验证清单——不是“全部验证过”，是“可据此开工，风险已登记”。

## D.21 2026-11-04 K009 字段级设计（模块分册 K09）

**本轮交付：** 新建 [K09 知识库字段级设计](design/Chilon_Design_Volume_K09_Knowledge_Field_Design.md)，把 §14 的 13 张表说到字段级，作为 Phase 1 Registry 的输入。

**三个结构性决定：**

1. **两层知识库用一列 `scope` 表达，不拆表。** 平台层与教师层字段完全相同，只有归属与权利默认值不同；拆表会让每个查询都要 UNION，题目与检索结果也得跟着分表。约束用 `CHECK` 表达：`platform → owner_id IS NULL`，`teacher → owner_id IS NOT NULL`。
2. **派生标注走版本化，不用列覆盖。** `knowledge_annotations` 每次修正插入新记录并回填 `superseded_by`；`knowledge_questions` 上的 `current_*` 列只是查询缓存。这样模型重跑不会覆盖教师结论，教师修正也有痕迹。
3. **题目定位用 JSONB 存多段，不建题目-块关联表。** 跨页题天然是多段结构，关联表要多一张并处理顺序与角色。代价是定位不能走关系查询——但定位只用于引用回溯，不用于筛选。标注为可复议。

**顺带解决的一个旧问题**：§14.5 长期挂着的“同一 Document Version 多次解析产生 Chunk 唯一键冲突”，解法是把 `parser_version` 与 `parse_schema_version` 纳入唯一域——升级解析器产生新 chunk，不覆盖被引用过的旧 chunk。

**平台层的权利落成约束**：平台来源的 `rights_status` 必须为 `licensed`、`distribution_scope` 必须为 `classroom`（§14.1.2 的 A 档），用 CHECK 或 Trigger 固化，避免靠人工录入正确。

**未决项 6 条**（§7），其中影响最大的是：按分类筛题要跨三跳，是否在 `knowledge_questions` 上冗余 `category_id` 与 `scope`。这条留给 Registry 阶段用真实查询计划决定，不在此处拍板。

**本册状态**：`DESIGNED`，不是 `confirmed`。字段冻结以 Schema Freeze Gate 的结论为准。

## D.22 2026-11-04 验收与测试矩阵（分册 D6）

**本轮交付：** 新建分册 [D6 验收与测试矩阵](design/Chilon_Design_Volume_D6_Acceptance_And_Test_Matrix.md)，以及**生成式**的测试计划 `schemas/test_plan.v1.json`（429 例）。

**核心做法：能机械派生的用例一律派生。**

| 来源 | 派生用例 | 数量 |
| --- | --- | --- |
| 状态机 136 条迁移 | 每条一个合法用例 | 136 |
| 101 个状态 | 每个一个拒绝用例 | 101 |
| 23 个教师动作 | 成功 + 失败 | 46 |
| 64 个接口 | 每个一条契约用例 | 64 |
| 18 个错误码 | 每个一条路径用例 | 18 |
| D3 / D1 / D1 §7 | 界面 12 + 指标 18 + 数据 24 | 54 |
| 并发与故障注入 | 人工设计 | 10 |

**为什么用生成而不是手写**：手写清单永远看起来完整。生成 + 覆盖校验器才能让“没测”和“测过了”有可判定的区别。

`design/check_test_plan.py` 校验：每条迁移恰好一个合法用例、每个（聚合，状态）恰好一个拒绝用例、每个教师动作既有成功也有失败、每个接口与错误码都有用例、用例 ID 全局唯一。**校验器带自测**：注入四类缺口必须全部检出。

**最贵但最值钱的一条**：CC-10「发布事务逐步失败」。发布是唯一会产生不可回收副作用的操作（不可变版本 + 审批消费），必须被证明“失败即回滚”。

**一条必须查 DOM 的断言**：UI-05「学生视图从 AST 投影」。截图无法区分“投影”与“CSS 隐藏”，只有 DOM 断言能。

**发布门禁 7 条**（§8）：429 例全过无跳过、覆盖校验 0 缺口、9 项阻断指标达标、黄金路径端到端含两个导出、CC-01–10 全过、12 条界面验收通过、5 个契约校验器全绿。

**本册新增两个长期资产**：`design/gen_test_plan.py`（生成器）与 `design/check_test_plan.py`（覆盖校验）。契约变更后重跑生成器，测试矩阵自动跟上。

## D.23 2026-11-04 Registry 与工程骨架

**本轮交付：** Phase 1 的第一块（K009 Registry）与工程骨架。

**一、Registry（K009，13 张表）**

| 产物 | 内容 |
| --- | --- |
| `database/registry/schema.json` | 命名、类型映射、模块与表清单、表顺序、角色、扩展 |
| `database/registry/fields/k009.json` | 13 张表的字段、约束、索引、RLS |
| `database/generator/validate_registry.py` | FLD-001..012 + 结构一致性，带自测 |
| `database/generator/generate_ddl.py` | 确定性 DDL + manifest（registry_hash / schema_hash） |
| `database/generated/k009.sql` | 341 行；同一 registry 两次生成字节一致 |

规模：143 个字段、20 个索引、4 条 RLS 策略。

**校验覆盖**：表清单与模块文件必须一致；`table_order` 必须覆盖全部表；主键唯一且名为 `id`；`owner_scoped` 必须真的声明 `owner_id`；FK 目标必须存在（或声明为外部表）；约束与索引引用的列必须存在；CHECK 表达式里的标识符必须是列（字符串字面量已排除）；敏感度必须合法；时间默认值必须是 `now()`。

**三个实现层面的决定：**

1. **用 JSON 不用 YAML**：环境没有 PyYAML，而给一个结构权威引入第三方解析依赖不值得。JSON 更难手写一点，但零依赖、可被任何工具读取。
2. **按模块聚合而非按关注点拆分**（§9.1 已更新）：一个模块的字段、索引、策略要一起评审。
3. **外部表 FK 生成为 DEFERRED 注释**：`material_knowledge_citations.material_version_id` 指向 K012 的 `material_versions`，后者尚未建表。生成器不臆造 FK，而是输出注释与依赖说明。

**已知缺口**：`superseded_by` 是自引用 FK 但不以 `_id` 结尾，因此 FLD-012 放宽为允许 `_id` 或 `_by`——与 `created_by`、`updated_by` 的惯例一致。这是规则适配现实，不是放过问题。

**二、工程骨架**

| 文件 | 作用 |
| --- | --- |
| `tools/check_all.py` | 11 项检查的唯一入口，CI 直接调用 |
| `.github/workflows/check.yml` | push 与 PR 触发，无第三方依赖 |
| `backend/pyproject.toml`、`backend/app/` | 后端骨架，只有 healthz，无业务代码 |
| `database/README.md`、`backend/README.md` | 目录职责与命令 |
| `.gitignore` | 排除缓存与生成临时文件 |

**11/11 检查通过**：六个契约校验器（均带自测）、文档表格、标点规范、目录锚点、Registry 一致性、DDL 同步。

**三、仓库**

本轮初始化了 Git 并在 master §0.2 的要求下完成首次提交（49 个文件）。CI 的价值依赖版本控制，在此之前 CI 配置只是一段不会执行的文本。

**下一步**：Alembic 基线（从生成的 DDL 建迁移），以及其余模块的字段级设计——但后者依赖 K011 的 35 张表清单，那是 §28.1 仍未关闭的历史恢复项。

## D.24 2026-11-04 Alembic 基线与迁移闭环

**本轮交付：** 把已验证的 K009 DDL 变成可执行迁移，并跑通 upgrade/downgrade 闭环。

| 产物 | 说明 |
| --- | --- |
| `backend/alembic.ini` | 迁移配置；URL 从 `CHILON_DATABASE_URL` 注入 |
| `backend/migrations/env.py` | **同步**驱动：asyncpg 不支持多语句执行，而 DDL 不在请求路径上 |
| `backend/migrations/versions/0001_k009_baseline.py` | 基线迁移，内嵌 DDL 快照与 registry/schema hash |
| `database/generator/gen_migration.py` | 从当前 DDL 生成新 revision，拒绝覆盖已有文件 |
| `database/tests/check_migration_sync.py` | 检测“改了 Registry、重新生成了 DDL，但忘了生成迁移” |
| `database/tests/check_migration_splitter.py` | 验证 SQL 切分器不会在 `$$` 函数体内切断语句 |
| `database/tests/run_migration_test.ps1` | 起容器 → upgrade → 验证 → downgrade → 验证回滚 |

**三个设计决定：**

1. **迁移是不可变快照。** 生成时把 SQL 与两个 hash 一起写进 revision 文件，后续 Registry 变化不会改写历史。要改结构就生成新 revision。
2. **迁移用同步驱动。** psycopg 而非 asyncpg：后者明确不支持一条语句里跑多个命令，而 DDL 本来就是同步的运维动作。应用本身仍然 async。
3. **切分器必须被测试。** 迁移里唯一的静默风险是把 `$$ ... $$` 函数体按 `;` 切断——切错了 DDL 只会在部分环境炸。`check_migration_splitter.py` 逐条校验 63 条语句的引号与美元引用配对。

**闭环验证结果（真实 PostgreSQL 17 容器）：**

```text
alembic upgrade head            → 0001_k009_baseline
结构验证                          → 12 表 / 4 策略 / 20 索引 / 17 外键
两层约束行为                      → 坏数据被拒绝
alembic_version                  → 0001_k009_baseline
alembic downgrade base           → 剩余表 0、剩余函数 0
```

**过程中环境给的两个教训：** `pip install` 首次尝试 20 分钟无进展（网络索引慢），改成分步安装后 1 分钟内完成；PowerShell 5.1 的管道会破坏 UTF-8，所以 SQL 改用 `docker cp` 进容器执行，脚本也不再依赖 `cmd /c`。

**下一步**：其余模块的字段级设计（K012 优先），以及把 K009 的 13 张表补进 `--with-optional` 变体的容器验证。

## D.25 2026-11-04 K012 入库与流水线复用验证

**本轮交付：** K012 的字段级设计直接落成 Registry，并用它验证“这套流水线能不能复用”。

| 产物 | 内容 |
| --- | --- |
| `database/registry/fields/k012.json` | 10 张表：projects、materials、material_versions、material_drafts、material_draft_revisions、document_schema_definitions、material_references、task_material_links、material_publication_approvals、material_exports |
| 生成器升级 | **延迟外键**支持；全局 `table_order` 移到 `schema.json` |
| 产物改名 | `generated/k009.sql` → `generated/schema.sql`（已跨两个模块） |
| 迁移 | `0001_baseline`（22 表），替换原 K009 单模块基线 |
| 测试参数化 | 期望表数/策略数/索引数/外键数取自 manifest，不再硬编码 |

**Registry 规模**：23 张表、266 个字段、34 个索引、13 条 RLS 策略。

**三个复用中发现的新问题：**

1. **互相引用需要延迟外键。** `materials.current_version_id` 与 `material_versions.material_id` 构成环，另有三个跨表前向引用。生成器新增 `deferred_fk`：先建表，最后统一 `ALTER TABLE ... ADD CONSTRAINT`。K009 从未遇到这种情况，说明流水线在前一个模块上“够用”不代表“完整”。
2. **psql 变量不能用在 `$$` 块内。** 期望值最初用 `:'expected_tables'` 传入，直接在 DO 块里报语法错误。改为块外 `SET` 自定义参数、块内 `current_setting()` 读取。
3. **切分器把注释里的分号当成语句结束。** 生成的注释 `-- (target owned by another module; add after ...)` 被切成两半，错误只在 Alembic 执行时才暴露。切分器已支持行注释，注释本身也不再用分号，并加了回归用例。

**验证结果（真实 PostgreSQL 17）：**

```text
直接应用 DDL        → 22 表 / 13 策略 / 34 索引 / 37 外键 / 3 函数
领域约束            → 两层知识库约束与 pinned 引用规则均按设计拒绝坏数据
alembic upgrade     → 0001_baseline
alembic downgrade   → 剩余表 0、剩余函数 0
```

**结论**：流水线可以复用，但每接一个新模块都会暴露一类新问题。这正是“先做两个模块”比“一次做五个”更稳的原因——**第三个模块的边际成本已经接近零**。

------------------------------------------------------------------------

## D.26 2026-11-04 K014 入库

**本轮交付：** K014 的 24 张表落成 Registry，全部通过真实 PostgreSQL 验证。

**Registry 规模**：47 张表、478 个字段、52 个索引、26 条 RLS 策略。

**K014 与前两个模块的本质区别：大部分表是系统级数据。**

| 归属 | 表数 | RLS |
| --- | --- | --- |
| 教师私有 | 5 | 按 owner_id 过滤 |
| 从属明细 | 4 | 随父表 |
| 平台数据 | 15 | 只读全开 |

教师私有：quality_check_runs、quality_issues、math_validation_runs、quality_issue_feedback、quality_issue_resolutions。从属明细：rule_snapshots、check_results、quality_evidence、math_validation_evidence。平台数据：规则、规则版本、数据集及其版本与样本、评估及其运行与结果、指标与观测、告警与事件、发布与审批与事件。

**这就是 §18.5 那条“确定系统级和教师级数据的精确隔离”的答案**：判据不是“谁创建”，而是“谁能看见”。规则、数据集、指标属于平台运营资产，教师只读；检查运行与问题属于教师，跨租户不可见。

**两个设计取舍：**

1. **`target_type` + `target_id` 不做外键。** 检查对象可以是 draft_revision 或 material_version，二选一。用两张可空外键会让“恰好一个非空”落到应用层，反而不如显式多态 + CHECK。
2. **`material_publication_approvals.required_quality_run_ids` 用 `text_array` 而不是关联表。** 发布审批是快照语义，引用的是“当时这些 run 通过了”，不是“现在仍然关联”。用数组允许 run 被归档而不破坏审批记录。

**验证结果：**

```text
直接应用 DDL   → 46 表 / 26 策略 / 52 索引 / 63 外键 / 3 函数
领域约束       → 两层知识库 + pinned 引用 + waive 必须留理由
alembic upgrade/downgrade → 干净
```

**顺带修掉一个验证器的老毛病**：CHECK 表达式扫描把 `trim`、`length` 这类 SQL 函数当成未知列。这已经是同类误判的第二次（第一次是字符串字面量），现在有了显式的关键字与函数白名单。**校验器的假阳性会训练人去忽略它，所以必须修。**

------------------------------------------------------------------------


## D.27 2026-11-04 K011 入库：用契约推导替代表清单恢复

**背景：** §15.6 的第一条 TODO 是“恢复 K011 完整约 35 张表清单”，§28.1 把它列为历史恢复项。这一轮没有去追那张清单，而是换了一个做法。

**判断依据：** 冻结的 `state_machines.v1.json` 里 13 个聚合，其中 8 个属于 K011（task、requirement_version、plan_version、plan_approval、execution、agent_run、step_execution、tool_execution）。§15.2 另有 15 张已知表。**清单可能是回忆，契约是跑过校验器的。** 因此以 15 张为起点，用聚合与规则补齐，表数由设计推出，不再对齐 35。

**第一个决定：平台基础设施层不新建模块。**

`outbox_events` 在 §15.2 里列为 K011 第 15 张表，但它服务所有模块。三条路里选了第三条：

| 方案 | 结论 |
| --- | --- |
| 塞进 K001 | 否决——§12 把 K001 标为 `UNKNOWN/PENDING`，§2957 写明“无法验证的旧模块不得被凭空补造” |
| 新建平台模块 | 否决——会引入一个新的跨模块依赖方向，而当前 K014 是完全独立的 |
| **物理归 K011、逻辑为共享设施** | 采用——与 `material_knowledge_citations` 由 K009 物理拥有、服务 K012 的先例一致 |

**第二个决定：§15.5 的五个候选逐条判定，不整体保留也不整体丢弃。**

| 候选 | 判定 |
| --- | --- |
| `agent_tool_versions` | 吸收为 `agent_tool_definitions` 的 `version` 列（幂等键要用它） |
| `agent_tool_plugin_bindings` | 吸收为 `agent_tool_definitions.plugin_id` |
| `agent_tool_execution_events` | 不建表，由 `agent_execution_events` 按聚合类型承载 |
| `agent_tool_grants` | 建表——Tool Call 前置校验需要“谁可以用哪个工具” |
| `agent_runtime_plugins` | 建表——发布与评估要引用 Plugin Manifest Hash |

**第三个决定：Lease / Heartbeat / Fencing Token 落在 `agent_executions` 上。**

§15.6 有一条“冻结字段归属”的 TODO 一直未决。放执行表而非单独表：Lease 的生命周期与执行状态完全同步，拆表会让每次心跳产生一次额外写入与一次额外一致性风险。旧 Token 的迟到写入不进执行状态，进 `agent_execution_events` 作审计证据。

**真正的交付物：聚合到表的覆盖校验。**

`database/tests/check_aggregate_coverage.py` 读取 `schema.json` 里的 `aggregate_tables` 映射，断言：

- 13 个契约聚合每一个都有映射；
- 映射的表在 Registry 中真实存在；
- 没有多余的映射条目。

13 个聚合全部对上：8 个在 K011，`draft`/`publication_approval`/`export` 在 K012，`quality_check_run`/`math_validation_run` 在 K014。

**这条校验才是本轮的重点。** 如果 K011 是按一张记错的清单设计的，某个聚合就会找不到表——而那意味着契约与实现脱节。现在这个风险被一条可执行的检查堵住了。

**结果：**

| 指标 | 数值 |
| --- | --- |
| Registry 表数 | 64（K011 新增 17） |
| 生成表数 | 63（可选向量表跳过） |
| 外键 | 92 |
| 聚合覆盖 | 13 / 13 |

```text
直接应用 DDL → 63 表 / 35 策略 / 70 索引 / 92 外键 / 3 函数
领域约束      → 通过
alembic upgrade/downgrade → 干净
```

**仍未关闭的两项**（不是阻塞，是记录）：

1. Plan Step DAG 的环检测放在应用层，库层只保证边唯一与无自环。数据库做传递闭包代价过高，且 Plan 规模小（通常 5–15 步）。
2. Runtime Session 与业务 Execution 的恢复映射已有 `agent_runs.harness_session_id`，但“进程崩溃后如何续跑”仍属实现细节，不在表结构里。

----------------------------------------

------------------------------------------------------------------------


## D.28 2026-11-04 K013 + K021 入库：Phase 1 Registry 完成

**本轮交付：** 最后两个模块入库，六个模块的 Registry 全部完成。

| 模块 | 表数 | 本轮判定 |
| --- | --- | --- |
| K013 Conversation & Activity | **7** | §17.1 列 8 个实体，`conversation_message_revisions` 标注“扩展候选，非 MVP”，本轮不建 |
| K021 Administrative Security | **4** | 与 §19.1 一致；`admin_audit_logs` 明确属 K002，不在此模块 |

**K013 的取舍：为什么是 7 不是 8。**

§17.3 定义了消息状态 `streaming/completed/interrupted/failed`，§17.4 定义了事件流与 SSE 重连。这些都落在前 7 张表里。而“消息修订”用于教师编辑历史消息——MVP 流程里没有这个动作。**建一张没有写入路径的表，比不建更糟**：它会让人以为功能存在。

**K013 的三个设计点：**

1. **Message 与 Event 分表。** Message 是教师可见的对话内容，Event 是追加式事件流；SSE 的 `Last-Event-ID` 用 Event Sequence，而不是 Message 序号。合并会让“重连补发”和“对话展示”两套语义互相污染。
2. **`agent_activities.progress` 允许为空。** §17.5 要求“不记录 Token、不暴露模型内部推理”。进度不确定时留空，而不是编一个百分比——**编出来的进度比没有进度更快失去信任**。
3. **`conversation_cursors` 拆成已读与已投递两个水位。** 两者会分离：消息投递到了客户端，但教师还没看到。合成一个字段会让“未读数”永远不准。

**K021 的取舍：不建外键到 K002。**

§19.3 有一条“与 K002 Identity 恢复后的管理员身份表建立 FK”，但 K002 至今未恢复。所以 `actor_id`、`approver_id`、`requested_by`、`executed_by` 都是无外键的 uuid，并在表注释里写明原因。**这比指向一张不存在的表诚实，也比凭空恢复 K002 安全。**

另外两条规则无法用 CHECK 表达，记录为应用层约束：
- “申请人不能批准自己的申请”——跨表比较（`approvals.approver_id` vs `requests.requested_by`），数据库需触发器
- 管理员不得无条件绕过 RLS——属部署与角色设计，不属表结构

**Phase 1 Registry 完成状态：**

| 模块 | 表数 | 说明 |
| --- | --- | --- |
| K009 Knowledge Base | 13 | 含 1 张可选向量表 |
| K011 Task & Agent | 17 | 覆盖 8 个聚合 |
| K012 Project & Material | 10 | |
| K013 Conversation | 7 | 消息修订表判定为非 MVP |
| K014 Quality & Evaluation | 24 | 15 张平台级数据 |
| K021 Admin Security | 4 | 无 K002 外键 |
| **合计** | **75** | 生成 74（跳过可选向量表） |

```text
字段      754
索引      82
RLS 策略  41
外键      106
聚合覆盖  13 / 13
DDL       1793 行 · hash 可校验
迁移      0001_baseline · upgrade/downgrade 已验证
检查      14 项全绿
```

**关于 Phase 1 的收尾判断：** 六册设计 + 七个契约 + 75 张表的 Registry，现在可以支撑 Phase 2。但有两件事必须写在前面：

1. **K002（Identity）仍未设计。** 当前所有 `owner_id` 都是无外键的 uuid。K002 恢复后需要补一轮外键与 RLS 校准，这是已知的、有计划的返工，不是意外。
2. **`0001_baseline` 仍是可重建的基线。** 一旦有任何环境应用过它，就必须冻结，之后只能新增 revision。这个触发条件写在 D.25。

----------------------------------------

------------------------------------------------------------------------


## D.29 2026-11-04 K002 入库与 owner_id 外键回填

**本轮交付：** 最后一个未设计模块 K002 入库，并一次性把散落在各模块的 `owner_id` 接上真实外键。

**§13.2 列了 9 个候选实体，要求去重后冻结。判定如下：**

| 候选 | 判定 |
| --- | --- |
| `users` + `user_accounts` | **合并**——没有规则要求分离，而 RLS 每次校验都要 join 只会更慢 |
| `user_credentials` | 保留——§13.3 明确“凭据与身份主体分离” |
| `user_username_history` | 保留——“用户名历史保留” |
| `user_email_addresses` | 保留——多邮箱且需验证态 |
| `user_sessions` | 保留——“Session 只保存 Token Hash” |
| `user_verification_tokens` + `user_password_reset_requests` | **合并**——同为一次性令牌，只差 `purpose` |
| `admin_audit_logs` | 保留——归属已确认在 K002 |

最终 **7 张**。

**本轮真正的价值：33 个外键。**

在此之前，所有模块的 `owner_id` 都是无外键的 uuid。这意味着数据库层面无法阻止“给一个不存在的教师写数据”——只有应用层知道它错了。

回填后：

| 指标 | 回填前 | 回填后 |
| --- | --- | --- |
| 表数 | 75 | 82 |
| 外键 | 106 | **145** |
| 字段 | 754 | 810 |

回填范围：所有 `owner_id` → `users`（RESTRICT），以及 K021 的 `requested_by`、`approver_id`、`executed_by` → `users`，`actor_id` → `users`（SET NULL）。

**没有回填的：`created_by`、`uploaded_by`、`reviewer_id`、`decided_by`。**

原因是真实的，不是偷懒：这些字段常由系统 Worker 写入，而 Worker 不是用户。给它们加 `users` 外键，会逼出一个还没设计的“系统主体”概念。**先把边界画清楚，比先加一个会误伤的约束好。**

**顺带修了一处测试：** 容器冒烟测试原本用随机 uuid 当 owner 插入数据，加了外键后立即失败。现在会先建一个真实用户。**这正是外键该起的作用——它把测试里的假数据逼成了真数据。**

**验证结果：**

```text
直接应用 DDL   → 81 表 / 42 策略 / 88 索引 / 145 外键 / 3 函数
领域约束       → 两层知识库 + pinned 引用 + 外键真实生效
alembic upgrade/downgrade → 干净
```

**Phase 1 至此真正完成**：七个模块全部入库，聚合覆盖 13/13，外键不再有悬空引用（`created_by` 类除外，已记录原因）。

----------------------------------------

------------------------------------------------------------------------


## D.30 2026-11-04 接入 GitHub 与 CI 首次联调

**仓库：** `https://github.com/Viver12138/Chilon`，分支 `main`。GitHub Actions 首次真实运行。

**首次运行就失败了——而本地一直是绿的。** 这件事比它看起来重要：本地 Windows PowerShell 5.1 与 CI 的 PowerShell 7 on Linux 是两套行为。

**四轮迭代：**

| 轮次 | 现象 | 处理 |
| --- | --- | --- |
| #1 | `database` job 失败，日志需管理员权限读不到 | 无法定位，改为让脚本自己报错 |
| #2 | 同上 | 加 `trap`，把诊断写成 `::error::` 注解 |
| #3 | 注解显示 `DDL application failed` | 让 psql 的每行输出都成为注解 |
| #4 | **通过** | — |

**三个真实缺陷，全部是本地不会暴露的：**

1. **`$ErrorActionPreference = 'Stop'` 会把重定向的 stderr 变成终止错误。** psql 把 NOTICE 写到 stderr，于是“验证通过”的消息本身成了失败原因。改为全局 `Continue` + 显式检查退出码；`throw` 不受该设置影响，仍然是终止的。
2. **Python 的 `write_text` 在 Windows 上把 `\n` 写成 `\r\n`。** 生成的 1968 行 DDL 全是 CRLF，而仓库没有 `.gitattributes`。已补 `* text=auto eol=lf`，生成器改为显式 `newline="\n"`。
3. **CI 日志读不到。** 公开仓库的 job 日志需要管理员权限，`annotations` 接口不需要。所以把关键诊断写成 `::error::` 注解，而不是只写 stdout——**这是让 CI 可自诊断的关键一步**，否则每次失败都要人手工翻日志。

**遗留观察：** 第 3 轮失败的具体 SQL 错误未能取到（第 4 轮同样的 SQL 通过），不排除 hosted runner 的瞬时问题。现在若再发生，注解会直接给出 psql 的错误行。

**当前流水线：**

```text
check     : 14 项静态检查（零依赖）
database  : 起 postgres:17 → 应用 81 表 DDL → 结构断言 → alembic upgrade → downgrade → 回滚断言
```

----------------------------------------

------------------------------------------------------------------------


## D.31 2026-11-04 行级安全上下文与隔离证明

**本轮交付：** Phase 2 第一块——会话级 RLS 上下文，以及一个证明它真的生效的测试。

**`backend/app/db/session.py`**

| 函数 | 语义 |
| --- | --- |
| `session_for(user_id)` | 在一个事务内 `set_config('app.current_user_id', ..., true)`，随后所有 RLS 策略按该身份求值 |
| `system_session()` | 不设任何身份。owner 级策略一律为假，**后台任务必须显式指定教师，不能顺手读全库** |

**关键决定：第三个参数是 `true`（事务级）。**

这是本轮最重要的一个决定。若用会话级设置，连接池会把它带给下一个请求——**在高并发下，某个教师会看到上一个教师的数据**，而且这个错误只在负载下出现、在单测里永远复现不了。

**测试证明了三件不同的事，而不是一件。**

“跨租户不可见”不是单一行为。一个只把 SELECT 写对的策略，仍然允许 bug 跨租户写入：

```text
SELECT  看不到别人的行      ✓
UPDATE  影响 0 行           ✓
INSERT  别人的 owner_id 被 WITH CHECK 拒绝  ✓
无上下文时看不到任何行       ✓
```

另外两个角色互不影响：Alice 尝试篡改后，Bob 仍看到自己未被修改的数据。

**测试自己抓到了两个问题，都值得记：**

1. **PL/pgSQL 变量名与列名冲突。** `DECLARE title text` 再 `SELECT min(title)` 报 “column reference is ambiguous”。改成 `v_title` 并限定 `materials.title`。
2. **`set_config(..., false)` 是会话级的，`RESET ROLE` 不会清除它。** “无上下文”那段测试因此仍然带着上一个身份——**这恰好演示了为什么应用层必须用事务级**。要真正模拟无身份，得显式设成空串，依靠 `nullif(...)::uuid` 返回 NULL。

第 2 点不是测试的缺陷，是它把设计理由演示出来了。

**流水线现状：**

```text
check     : 14 项静态检查
database  : 应用 DDL → 结构断言 → alembic upgrade/downgrade → **RLS 隔离断言**
```

----------------------------------------

------------------------------------------------------------------------


## D.32 2026-11-04 CI 间歇性失败的真实原因：探活没探到正确的实例

**现象：** 同一个提交，CI 时红时绿。失败信息是：

```text
psql: error: connection to server on socket "/var/run/postgresql/.s.PGSQL.5432"
      failed: FATAL:  the database system is shutting down
```

**根因不是超时，是竞态。** `postgres` 镜像的 entrypoint 分两阶段：

1. 首次启动时先起一个**临时实例**跑初始化脚本（`initdb`、`POSTGRES_PASSWORD`、建库）
2. 脚本跑完后停掉临时实例，再起正式实例并监听 TCP

临时实例**只监听 unix socket**（`listen_addresses=''`）。而我们的探活写法是：

```powershell
docker exec $Container pg_isready -U postgres -d chilon   # 走 unix socket
```

它在阶段 1 就返回成功——**探到的是一个马上要被关掉的实例**。随后 psql 连接正好落在关闭窗口里，就报 “the database system is shutting down”。

于是同一份代码，取决于初始化耗时与连接时机的相对关系，时红时绿。第 3 轮和第 8 轮失败、第 4 轮和第 7 轮通过，都是这一个原因。

**修法：探活改走 TCP。**

```powershell
docker exec $Container pg_isready -h 127.0.0.1 -p 5432 -U postgres -d chilon
```

临时实例没有 TCP 监听，正式实例才有。这一个参数就把两个阶段区分开了。

**这条经验的普遍性：** “服务已就绪”必须探测**你将要连接的那个端点**。用本地 socket 探活、再走 TCP 连接，或者在负载均衡后探一个实例、连另一个——都是同一类错误。探活的语义不是“进程活着”，而是“我这条连接会成功”。

**当前 CI（run #9 全绿）：**

```text
check     : 14 项静态检查
database  : 应用 DDL → 结构断言 → alembic upgrade/downgrade → RLS 隔离断言
```

----------------------------------------

------------------------------------------------------------------------


## D.33 2026-11-04 Outbox 派发器与投递契约

**本轮交付：** `backend/app/outbox/dispatcher.py`，以及六个场景的正确性测试。

**机制：事务即认领。**

`FOR UPDATE SKIP LOCKED` 在派发事务内锁住一批事件。没有引入 `delivering` 状态，理由写在代码注释里：那需要一个可见性超时和一个清理崩溃 Worker 的收割器；而“事务就是认领”已经满足契约——进程中途死亡则事务回滚、事件仍可被认领、下次重投。**代价是行锁在 handler 执行期间被持有，所以 handler 必须短。** 当 handler 变慢时，正确的下一步是加认领状态与超时，而不是把这里的超时调大。

**六个场景、14 条断言：**

| 场景 | 断言 |
| --- | --- |
| 原子性 | 业务行与 Outbox 行同生共死（模拟崩溃后两者都不存在） |
| 投递 | handler 收到事件、状态置 `delivered`、`delivered_at` 有值 |
| 重试 | 失败后保留事件、`attempts` 递增、`available_at` 后退、错误被记录 |
| 死信 | 达到上限后转 `dead_letter`，不再无限重试 |
| 认领 | 两个派发器拿到**不相交**的批次（SKIP LOCKED 生效） |
| 消费者幂等 | 同一事件重投两次，副作用只发生一次 |

第 5 条没有用并发时序去碰运气，而是让两个事务同时开口、断言取到的行集合互斥。**时序测试会偶发通过，集合断言不会。**

**三个环境问题，都不是逻辑错误：**

1. **`outbox_events` 原本没有任何 RLS 策略。** 生成器对所有表都开了 `FORCE ROW LEVEL SECURITY`，无策略即拒绝——除超级用户外谁都读不了它。已补 `FOR ALL USING (true)`。这类系统表没有 owner 列，租户隔离靠角色授权而非行策略，这一点写进了注释。
2. **缺 `greenlet`。** SQLAlchemy 的 asyncio 扩展在 import 期就需要它，报错发生在任何业务代码之前。
3. **psycopg 异步在 Windows 上不兼容 ProactorEventLoop。** 测试里切到 Selector 事件循环；生产是 Linux，这只是本地测试的适配。

**一个必须记下的过程失误：** 我曾用一个脚本给 CI 加 `greenlet`，脚本末尾无条件打印了 “greenlet added”，而替换因引号转义失败根本没匹配上。**是下一次 CI 失败才暴露的。** 教训很短：**只有断言成立时才打印成功**，否则那行输出就是假的。现在 CI 的安装行由人眼确认过。

**流水线（run #13 全绿）：**

```text
check     : 14 项静态检查
database  : DDL → 结构断言 → alembic upgrade/downgrade → RLS 隔离 → Outbox 契约
```

----------------------------------------

------------------------------------------------------------------------


## D.34 2026-11-04 身份服务与 RLS 的一个明确例外

**本轮交付：** `backend/app/services/identity.py`——注册、登录、会话校验、登出，20 条断言。

**三个安全决定：**

1. **密码用 scrypt，不用 Argon2id。** schema 的 `algorithm` 列默认值是 `argon2id`，而实际存 `scrypt`。原因是环境没有 Argon2 依赖，而 scrypt 在标准库里。**换回 Argon2id 是一行改动**；现在要紧的是存下去的值必须是单向 KDF 输出，而不是明文或可逆编码。`algorithm` 列记录真实算法，不是记录愿望。
2. **会话 Token 只存 SHA-256。** 明文只出现在登录响应里。数据库泄漏不等于会话泄漏。
3. **“用户不存在”与“密码错误”抛同一个错误。** 否则登录接口就成了用户名枚举器。

**测试覆盖的失败模式**（断言“坏的情况被拒绝”，而不是“好的情况能通过”）：密码串不出现在存储值里、Hash 自带 KDF 参数、Token 不以明文入库、伪造 Token 被拒、过期会话被拒（用传入时钟而非进程时钟）、撤销后立即失效、停用账户既不能登录也不能继续用已有会话。

**本轮的真正难点：RLS 与认证的根本冲突。**

登录时**还没有身份**，却要按用户名查 `users`。而当时 `users` 只有“只能看自己”的策略，加上全局 `FORCE ROW LEVEL SECURITY`——认证查不到人。这不是实现 bug，是策略表达能力的边界：**RLS 只能表达“你能看到属于你的行”，无法表达“在你不知道你是谁之前先读一次”。**

三个选项：给认证单独一个 BYPASSRLS 角色（全开，过宽）；加 `SECURITY DEFINER` 函数（`FORCE` 下连属主也受约束，**不解决问题**）；把身份三表改为服务级。

选择了第三个，并把它写成**显式例外**而不是默默放宽：

| 表 | 策略 | 原因 |
| --- | --- | --- |
| `users` | 服务级 | 认证需要跨用户查找 |
| `user_credentials` | 服务级 | 登录需要读到 Hash |
| `user_sessions` | 服务级 | 按 Token Hash 反查会话 |

教学数据不受影响——`materials`、`projects` 等仍保持完整隔离。

**这个改动被测试抓到了，而且抓得对。** RLS 测试原本断言“Alice 只看到自己一个 user”，改完策略后该断言失败。我没有把测试改松了事，而是**删掉这条断言并写明它为什么不再成立**——测试反映契约，契约是我改的，这个变化必须留痕。

**流水线（run #16 全绿）：**

```text
check     : 14 项静态检查
database  : DDL → 结构断言 → alembic upgrade/downgrade → RLS 隔离 → Outbox 契约 → 身份服务
```

----------------------------------------

------------------------------------------------------------------------


## D.35 2026-11-04 状态枚举漂移：8 个聚合的 `status` 与契约不符

**发现过程。** 开始写 Task 服务时，我打算让冻结的状态机契约驱动迁移校验。第一件事是把契约里的状态读出来，与 Registry 的 CHECK 约束比对——结果对不上。

**13 个聚合里 8 个不一致，全部在 K011。**

| 聚合 | 契约状态数 | Registry 状态数 | 典型偏差 |
| --- | --- | --- | --- |
| task | 9 | 11 | 漏 `planning`、`awaiting_plan_approval`、`running`、`needs_attention`、`cancelling` |
| execution | 12 | 12 | 漏 `pause_requested`、`cancel_requested`、`cancelling`、`superseded`，多 `recovering`、`expired` |
| tool_execution | 10 | 8 | 漏 `requested`、`authorizing`、`authorized`、`rejected`、`dispatching` |
| 其余 5 个 | — | — | 不同程度的漏与多 |

**原因不是手误，是输入错了。** 写 K011 时我以主文档 §15 的散文为输入，自己归纳出一组状态名；而 `schemas/state_machines.v1.json` 早就冻结了精确的枚举。K012/K014 的聚合全部正确——因为写它们时我读的是 §21.7–§21.10 的状态机表格。

**最严重的后果不是名字不对，是两个默认值非法。**

`agent_runs.status` 默认 `'queued'`、`agent_tool_executions.status` 默认 `'pending'`，这两个值都不在契约状态集里。**也就是说第一次插入就会违反 CHECK 约束**——一个建表就带着的、必然触发的错误，却因为没有任何测试插入这两张表而一直没暴露。

**处理：**

1. `tools/sync_state_enums.py`——以契约为输入重写 CHECK 表达式与默认值。10 处改动，全部机械可复核。
2. `database/tests/check_state_contract.py`——加入 CI，逐聚合比对枚举与默认值。**这是本轮真正的交付物**：它把“契约是输入”这件事从纪律变成了检查。
3. 五个数据库测试全部重跑，全绿。

**教训的一句话版本：契约是输入，不是事后对照的参考资料。** 只要代码里出现一个手写的状态名，就说明该处没有消费契约。

**流水线（run #18 全绿，15 项静态检查 + 5 个数据库套件）：**

```text
check     : 15 项（新增：状态枚举与契约一致）
database  : DDL → 结构断言 → alembic → RLS → Outbox → 身份
```

----------------------------------------

------------------------------------------------------------------------


## D.36 2026-11-04 契约驱动的 Task 服务，与契约里 5 条重复边

**本轮交付：** `backend/app/services/tasks.py`——迁移表**从 `state_machines.v1.json` 读取**，不在代码里重写。
`backend/tests/test_tasks.py` 遍历契约的全部边，而不是手写几条用例。

**两层独立保护：**

- 契约决定 `(state, trigger)` 是否合法；
- `state_version` 的 CAS 决定调用者看到的状态是否还是它以为的那个。没有 CAS，两个并发审批会同时成功。

状态变更与 Outbox 事件在同一事务内写入——崩溃不会留下“有状态无事件”或“有事件无状态”。

**测试覆盖（约 50 条断言）：**

```text
22 条展开后的契约边   每条都走通，且落地状态与契约一致
每个非法 (状态, 触发)  全部被拒，且被拒后状态与版本都没动
版本过期              报 StateConflict，且没有写入任何事件
不存在的任务          报 TaskNotFound，不静默创建
每条成功的迁移        恰好写一条事件，payload 带 from/to/trigger
```

**然后撞上了契约本身的问题：重复边。**

服务加载契约时拒绝为同一个 `(状态, 触发)` 选两条边，于是报错：

```text
RuntimeError: contract has two transitions for ('awaiting_plan_approval', 'cancel')
```

T07 与 T17 都声明了这条边。**这是契约缺陷，不是服务缺陷**——实现者无法知道该用哪条的 `effects`。

把检查写进 CI 后，立刻又查出 **4 条同类**：

| 聚合 | 重复的边 | 声明者 |
| --- | --- | --- |
| execution | `(paused, request_cancel)` | E11、E12 |
| execution | `(queued, supersede)` | E03、E24 |
| draft | `(editing, abandon)` | D03、D24 |
| export | `(queued, cancel)` | X02、X10 |

**五条边是同一个模式**：先写了一条针对某个状态的精确迁移，后来又加了一条“多状态通用”迁移，把那个状态包含了进去。目标相同、守卫几乎相同，所以行为不歧义，但**迁移 ID 歧义**——而 `effects` 不同（T07 有“不创建 Execution”，T17 没有）。

**处理：统一收窄通用边，保留精确边。** 五处改动全部保持语义不变（同目标），只是消除歧义。D6 的测试矩阵按迁移 ID 生成，因此数量不变（429 例）。

**检查项本身也是交付物：** `database/tests/check_state_contract.py` 现在同时校验状态枚举、默认值合法性与 `(状态, 触发)` 唯一性。**这三类问题此前都只能靠人读文档发现，现在每推一次都在查。**

**流水线（run #20 全绿）：**

```text
check     : 15 项静态检查
database  : DDL → 结构 → alembic → RLS → Outbox → 身份 → 任务生命周期
```

----------------------------------------

------------------------------------------------------------------------


## D.37 2026-11-04 方案审批服务，与一条永远无法满足的约束

**先说那条约束——它比服务本身更严重。**

`agent_plan_approvals` 上有：

```sql
CHECK ((status = 'consumed') = (consumed_at IS NOT NULL))
```

而契约里 `plan_approval` 的六个状态是 `pending / approved / rejected / revoked / invalidated / expired`——**没有 `consumed`**。

于是 `status = 'consumed'` 恒为假，约束退化成 `consumed_at IS NULL`：**这张表永远无法记录“审批已被消费”**。而审批单次消费是整个产品最核心的不变量之一。

它是从 `material_publication_approvals` 抄来的，那张表的契约里确实有 `consumed` 状态，所以那边成立。

**修法**：消费是“使用”不是“决定”，审批状态保持 `approved`，只写时间戳：

```sql
CHECK (consumed_at IS NULL OR status = 'approved')
```

**新增一类检查**：约束里引用的状态字面量，必须是该列枚举允许的值。把旧表达式放回去验证过——检查确实报错：

```text
plan_approval: agent_plan_approvals.status constraint
ck_agent_plan_approvals_consumed references state(s) the enum forbids: ['consumed']
```

这条检查和之前的重复边检查是同一类：**约束本身也要被约束**。

**记录的债务**：同一个概念（审批被使用）在两个模块里建模不同——publication 用状态 `consumed`，plan 用时间戳。现在两边各自自洽，但这是不一致，等有人负责时统一。

**服务：`backend/app/services/plans.py`**

单次消费与 Hash 绑定用一条条件 UPDATE 完成：

```sql
UPDATE ... SET consumed_at = now()
WHERE id = :id AND status = 'approved' AND consumed_at IS NULL
  AND plan_content_hash = :hash AND plan_version_id = :version
RETURNING id
```

先读后写的写法会让两个执行器同时读到“已批准、未消费”然后同时放行。**这里由数据库裁决一次。**

**测试抓到的服务 bug：** `create_plan_version` 原本用 `ON CONFLICT (id) DO NOTHING` 做“取或建”，而 id 是现场生成的——冲突永不发生，于是每次调用都新建一个 plan，版本号永远从 1 开始。改为先查后建。

**测试覆盖（6 组）：**

| 场景 | 断言 |
| --- | --- |
| 版本 | 初始状态来自契约、版本号递增、同内容同 Hash、键序不影响 Hash |
| 消费 | 成功一次并被记录；第二次被拒 |
| Hash 绑定 | 方案改过后旧审批不能执行，且审批记录完好未受污染 |
| 过期 | 过期审批被拒 |
| 未批准 | pending 与 rejected 都不能消费；重复决策被拒 |
| 数据库层 | 非 `approved` 行写入 `consumed_at` 被 CHECK 拒绝 |

**顺带**：测试里我还写了一个 `'confirmed'` 的字面量——那是枚举修正前的旧值，被 CHECK 直接拒绝。已改为从契约取初始状态。**同一个错误我这轮犯了两次（服务里、测试里各一次），都靠数据库拒绝暴露。**

**流水线（run #22 全绿）：**

```text
check     : 15 项静态检查
database  : DDL → 结构 → alembic → RLS → Outbox → 身份 → 任务 → 方案审批
```

----------------------------------------

------------------------------------------------------------------------


## D.38 2026-11-04 执行服务：消费审批、围栏令牌

**`start_execution` 不是一个 INSERT，它是审批被花掉的那一刻。** 事务内的顺序是有意的：

```text
1. 任务状态必须允许 start_execution（查契约）
2. Plan 版本的 Hash 必须与批准时一致
3. 消费审批（单次 + Hash 绑定）
4. 创建 execution
5. 任务推进到 running
```

任何一步失败全部回滚，**审批不可能被“半花”**。测试专门验证这一点：用一个过期的任务版本故意让第五步失败，然后断言审批的 `consumed_at` 仍为空、没有残留的 execution 行。

**围栏令牌的检查放在契约检查之前——这是本轮的一个判断。**

被夺走租约的 Worker 不是“发了非法指令”，而是**不再是所有者**。报 `StaleFence` 会让它停下来重读；报“契约迁移非法”会让人去查状态机。**错误信息指向哪个方向，决定了人会不会查错地方。**

`acquire_lease` 用条件 UPDATE 完成“取或续”：`WHERE lease_expires_at IS NULL OR lease_expires_at < now()` 加 `fencing_token = fencing_token + 1`。活租约拿不到，过期租约拿下后令牌必然递增，旧令牌的写入与心跳一律被拒。

**测试（5 组）：**

| 场景 | 断言 |
| --- | --- |
| 启动 | 消费审批、任务转 running、执行进入契约初始态；同一审批不能启动第二次 |
| 失败启动 | 任务版本过期 → 拒绝，审批未被消费，无残留执行行 |
| 契约迁移 | 24 条边逐条走通，落地状态与契约一致 |
| 非法组合 | 236 个未声明组合全部被拒 |
| 围栏 | 活租约不可夺；过期租约接管后令牌递增；旧令牌的推进与心跳都被拒 |

**测试自己暴露的一个假通过：** 第一次取租约时我写了 `ttl_seconds=0`，租约当场过期——于是紧接着的断言“活租约不可被夺”**根本没有机会成立**，它失败得毫无意义。

改成一个真实的 TTL 后，那条断言才开始测试它声称要测试的东西。**一个永远不会因为正确原因通过的断言，和一个错误的实现一样危险。** 这与之前“脚本无条件打印成功”是同一类错误：**验证动作本身没有被验证。**

**流水线（run #24，八个数据库套件）：**

```text
DDL → 结构 → alembic → RLS → Outbox → 身份 → 任务 → 方案审批 → 执行
```

**剩余未做**：Plan Step 的 DAG 调度、`agent_runs` / `agent_step_executions` / `agent_tool_executions` 三层执行记录、工具授权校验。表都在，服务还没有。

----------------------------------------

------------------------------------------------------------------------


## D.39 2026-11-04 步骤 DAG，以及一次自己造成的 CI 反复

**服务：`backend/app/services/steps.py`**

DAG 在**计划创建时**校验并落库，不是在执行时。理由很直接：**一个跑不通的计划不该走到审批页**。执行时才发现环，是事故；创建时发现，是表单错误。

环检测用拓扑排序，不交给数据库。Postgres 无法在不做递归检查的前提下表达“这个关系无环”，而计划通常只有 5–15 步——创建时算一次更便宜，报错也更可读。

调度按依赖算：只有依赖全部 succeeded 且尚未开始的步骤才是 ready。测试用菱形图（gather → draft/verify → export）验证了“两边都完成，汇聚点才就绪”，以及失败步骤会阻断下游。

**然后是这轮真正的教训，与服务无关。**

我给九个测试脚本统一加了 `docker run` 重试，**但只用本地验证了其中两个**。没验的那个恰好是唯一使用 `& docker run` 写法的脚本，我的正则从 `docker run` 开始匹配，把调用符 `&` 留在了注释前面：

```powershell
& # Nine throwaway containers ...
```

PowerShell 立即报解析错误。CI 连红三轮，每轮我都在猜是 pip、是容器、是瞬时故障——其实原因在第一次推送时就已经存在，而且**本地一条命令就能发现**。

**这和之前那次悬空 `&` 是同一个错误，第二次。** 上次是文本替换留下的，这次是正则替换留下的；共同点是**改完没有验证被改的东西**。

三条可以带走的经验：

1. **批量修改之后必须全量验证，不能抽样。** 抽样的样本恰好不是出问题的那个，是必然会发生的事，不是运气差。
2. **“看起来像基础设施抖动”的失败，先假设是自己的改动。** 我连续两轮把解析错误解释成 pip 或 docker 的瞬时问题——因为那更符合“本地全绿”的叙事。
3. **同一个错误犯两次，说明检查而不是纪律缺失。** 已经加了批量脚本的验证习惯，但更该有的是：脚本类改动的验证必须覆盖全部改动文件。

**流水线（run #30，九个数据库套件）：**

```text
DDL → 结构 → alembic → RLS → Outbox → 身份 → 任务 → 审批 → 执行 → 步骤 DAG
```

另外顺手加固了两处 CI 稳定性：`docker run` 三次重试（幂等操作，报错仍会打印），以及 `pip install` 三次重试并把失败写成注解。

**Phase 3 剩余**：`agent_runs` / `agent_tool_executions` 两层（工具调用、幂等键、授权校验）、`outcome_unknown` 对账。

----------------------------------------

------------------------------------------------------------------------


## D.40 2026-11-04 工具层：五道闸里归数据层的两道，与幂等键

§15.3 要求每次 Tool Call 通过 Identity、Owner、Scope、Capability、Business Approval 五道闸。`backend/app/services/tools.py` 实现了**归数据层的两道**：

| 闸 | 归属 | 实现 |
| --- | --- | --- |
| Identity / Owner / Scope | RLS | 由 owned session 保证，服务不再重复检查 |
| Capability | 数据层 | `agent_tool_grants` 必须有未撤销的授权 |
| Business Approval | 数据层 | `requires_approval` 的工具只能在来自已批准计划的执行里跑 |

**不在服务里重查 RLS 覆盖的东西**，是因为重复的保证会掩盖真正的缺口：如果哪天 RLS 失效了，服务里的检查会让人误以为仍然安全。

**幂等键是这层的核心。**

```text
sha256(execution_id | step_execution_id | tool_key | tool_version | canonical(args))
```

三个细节都有理由：

1. **参数序列化后参与计算，键序无关。** `{"a":1,"b":2}` 与 `{"b":2,"a":1}` 是同一次调用——否则同一请求换个序列化方式就会重复执行副作用。
2. **`tool_version` 参与计算。** 工具升级后重试算**另一次调用**，不是复用旧结果。静默复用不同代码产出的结果，等于宣称一个我们并不拥有的保证。
3. **写入用 `ON CONFLICT (idempotency_key) DO NOTHING` 再回查**，重放返回原始 `invocation_id`，并标记 `replayed=True`。

**测试（4 组、18 条断言）：**

| 场景 | 断言 |
| --- | --- |
| 闸门 | 未知 / 停用 / 未授权 / 已撤销授权都被拒；需审批的工具能创建但走契约初始态 |
| 幂等 | 同参数两次 → 只有一行、返回同一 id、第二次标记为重放；改参数 → 新调用；键序无关 |
| 版本 | 同 key 升版本 → 新调用，不算重放 |
| 契约 | `requested → authorizing → authorized → dispatching → running` 逐条走通；非法迁移被拒；结果写入并带 Hash |

**一个诚实的取舍：`agent_tool_executions` 没有 `state_version` 列。** 所以这里的迁移守卫是当前状态本身，不是乐观并发。工具调用天然有幂等键兜底（同一调用只会发生一次），加一列 CAS 只会增加写入成本而不增加保证。这一点写在代码注释里，不是遗漏。

**流水线（run #32，十个数据库套件）：**

```text
DDL → 结构 → alembic → RLS → Outbox → 身份 → 任务 → 审批 → 执行 → 步骤 DAG → 工具
```

**Phase 3 剩余**：`agent_runs`（Runtime 会话与执行的多轮映射）、`outcome_unknown` 对账（超时后先查实际状态，不盲目重试）。

----------------------------------------

------------------------------------------------------------------------


## D.41 2026-11-04 运行映射与未知结果对账，Phase 3 服务完成

**`backend/app/services/runs.py`** 两件事放在一起，因为它们是同一个问题的两端：运行时到底做了什么（`agent_runs` + `agent_runtime_events`），以及当我们不知道一次工具调用是否发生时该怎么办。

**对账规则（§15.3）：超时不等于失败。**

`reconcile_tool` 只接受**外部观测到的**结果，从不自己重发。这是刻意的：**对账函数里如果带重试，就把“不确定”变成了“可能做了两次”。** 后者比不知道严重得多。

三种观测的处理：

| 观测 | 处理 |
| --- | --- |
| `succeeded` | 记录结果与 Hash，状态置 `succeeded` |
| `failed` | 记录错误码，状态置 `failed` |
| `unknown` | 保持 `outcome_unknown`，等人看。**不重试** |

已终结的调用再次对账是幂等的——返回原状态，不改写。

**测试里最重要的一条是负向断言：**

```text
对账之后，该工具的调用行数仍然是 1
```

如果实现里偷偷重试了，这条会变成 2。它是这个模块存在的理由。

**其余覆盖：** run 的 ordinal 递增、runtime 事件的 seq 单调与 payload Hash、run 沿契约迁移、非法迁移被拒、超时落 `outcome_unknown` 而非 `failed`。

**一个 Schema 不一致，记录为债务：** `agent_runtime_events.occurred_at` 是 `NOT NULL` 但没有默认值，而其他所有时间戳都默认 `now()`。服务里显式写入 `now()`，因为事件发生时间本来就该由写入方决定。要么统一加默认值，要么保持显式，当前选后者。

**Phase 3 服务完成状态：**

| 服务 | 文件 | 关键不变量 |
| --- | --- | --- |
| 会话与 RLS | `db/session.py` | 事务级上下文，不跨请求泄漏 |
| 身份 | `services/identity.py` | 密码单向、会话只存 Hash、撤销即失效 |
| 任务 | `services/tasks.py` | 契约驱动 + CAS |
| 方案与审批 | `services/plans.py` | 单次消费 + Hash 绑定 |
| 执行 | `services/executions.py` | 花掉审批、围栏令牌 |
| 步骤 DAG | `services/steps.py` | 创建时校验，按依赖调度 |
| 工具 | `services/tools.py` | 能力/审批闸门、参数级幂等 |
| 运行与对账 | `services/runs.py` | 未知结果不重试 |
| 发件箱 | `outbox/dispatcher.py` | 同事务写入、至少一次、死信 |

**流水线（run #34，十一个数据库套件）：**

```text
DDL → 结构 → alembic → RLS → Outbox → 身份 → 任务 → 审批 → 执行 → 步骤 DAG → 工具 → 运行与对账
```

**仍未做**：HTTP 层（D5 的 64 个端点一个都没接）、SSE、缓存与队列、前端。**服务层是地基，不是产品**——这一点在总结里必须说清楚。

----------------------------------------

------------------------------------------------------------------------


## D.42 2026-11-04 HTTP 层接入，与一次几乎被掩盖的隔离失效

**交付**：`app/api/` 三个路由（tasks / plans / executions）+ 依赖与错误映射，`app/main.py` 只做装配。18 条断言覆盖鉴权、黄金路径、跨租户、边界校验。

**端点严格按 D5 命名**，包括两处容易出错的接缝：

1. **动作名 kebab-case ↔ 触发名 snake_case**（`submit-requirement` ↔ `submit_requirement`）。映射只写一处，因为这是两份冻结契约的交界，写错必须是一行能改的地方。
2. **D5 没有认证端点。** 所以认证做成 Bearer token 依赖，而不是自己发明 `/auth/login`。**端点集合保持与契约一致**，这是“契约是输入”的直接应用。

**错误映射集中在一张表**：20 个领域异常 → 18 个冻结错误码 + 各自声明的 HTTP 状态。新服务忘记翻译会落到 500，而 500 在测试里会立刻可见。

顺带发现 FastAPI 的一个坑：`add_exception_handler(Exception, ...)` 在 ASGI 传输下**会把异常重新抛出**（Starlette 的 server-error 中间件先响应再重抛），客户端拿到的是异常而不是 JSON。改成按异常类型注册处理器才正确。

### 这轮真正的发现：测试用超级用户跑，等于关掉了多租户隔离

第一次跑 HTTP 测试，跨租户读取返回了 **200**。

原因是我让测试连 `postgres`——**超级用户绕过 RLS**。也就是说：如果我没有写那条“另一个教师读不到”的断言，这套 HTTP 层会带着完全失效的租户隔离“测试通过”。

修法不是加断言，而是**让测试跑在真实的非超级用户角色上**：先建 `chilon_api_test` 角色、授予表权限，再以它连库。这才是生产配置——应用绝不能以超级用户运行。

**一条可以带走的规则：测安全属性的环境，必须与生产的安全属性一致。** 用超级用户测 RLS，和用关闭鉴权的环境测鉴权，是同一种错误：**测的是一个不存在的系统。**

### 两处契约缺口，暴露而不是绕过

| 缺口 | 处理 |
| --- | --- |
| D5 的 23 个动作端点里没有“批准计划” | 加了 `POST /plan-approvals/{id}/actions/approve`，并在注释里标注这是契约缺口 |
| 没有读取步骤 DAG 的端点 | 加了 `GET /executions/{id}/steps`，同样标注 |

选择**补上并标记**，而不是“契约没写所以不做”——因为不补的话黄金路径在 HTTP 上走不通，而假装它存在更糟。

**流水线（run #36，十二个数据库套件）：**

```text
DDL → 结构 → alembic → RLS → Outbox → 身份 → 任务 → 审批 → 执行 → DAG → 工具 → 运行对账 → HTTP
```

**状态**：系统现在可以被真实请求驱动了。仍未做：SSE、缓存与队列、其余端点、前端。

----------------------------------------

------------------------------------------------------------------------


## D.43 2026-11-04 Agent 回合：一句需求变成一个可审批的方案

**这是产品本体第一次真的存在。** 在此之前，方案只能由测试代码直接调服务创建。现在有一个入口完成整个回合：

```text
需求文本 → 抽取 → 记录需求版本 → 规划 → 校验 → 落库 → 建审批请求
```

**规则：模型只负责提方案，校验器负责裁决。**

`planner.validate_plan` 校验四件事：JSON 结构、DAG 可执行性、工具是否属于该教师、步骤数上限。任何一条不过，模型拿到**校验器自己的错误原文**重试一次，再不过则整个回合失败。

**为什么值得让它失败**：一个“看起来合理但会调用不存在工具”的方案，比“没有方案”危险得多——它会走到审批页，而教师无从判断工具是否存在。

**两个实现，一个协议：**

| 实现 | 用途 |
| --- | --- |
| `TemplatePlanner` | 确定性模板，离线跑全部 CI，无需密钥 |
| `DeepSeekPlanner` | 真实模型，`CHILON_PLANNER=deepseek` 启用 |

**真实模型跑通的结果**：输入「用高考题和模拟题出 6 道三角函数题」，DeepSeek 输出 5 步：

```text
retrieve(knowledge.search)
  ├── gen-basic(content.generate)
  ├── gen-mid(content.generate)
  └── gen-hard(content.generate)
        └── check(quality.check)
```

模型自己选择了“按难度分三路并发生成再汇聚”，不是模板写的。DAG 与工具校验全部通过。

**需求抽取拒绝编造。** 「出一道三角函数的题」里没有题量，`question_count` 保持 `None`，由规划器决定默认值——那是规划选择，不是抽取函数可以编造的事实。空需求直接拒绝，任务留在 `draft`，**不写任何数据**。

**一处契约缺口**：D5 的 64 个端点里没有“Agent 出方案”。已补 `POST /tasks/{id}/agent/plan` 并标注。**没有把它塞进教师动作**——规划不是教师动作，它不该出现在 `allowed_actions` 里。

**CI 与本地走不同路径**：CI 没有密钥，DeepSeek 那段打印 `skip`；本地有密钥，真实模型参与测试。这样 CI 不依赖外部服务，而真实链路每次本地运行都会被验证一次。

**流水线（run #39，十三个数据库套件）。**

**仍未做**：步骤不会真的执行——`knowledge.search` / `content.generate` 这些工具只有定义，没有实现体，也没有 Worker 去跑。**方案是真的，教学产出还不是。**

----------------------------------------

------------------------------------------------------------------------


## D.44 2026-11-04 工具实现与执行器：一句话到题目

**交付：** `app/tools/impl.py`（三个工具）+ `app/services/executor.py`（跑步骤）+ `test_executor.py`。

一句「用高考题出 4 道三角函数题」现在能走完全程：检索 → 生成 → 自查，产出题目、引用与检查报告，工具调用带 Hash 落库，执行终态 `succeeded`。

**三个工具各自守一条线：**

| 工具 | 守什么 |
| --- | --- |
| `knowledge.search` | 返回的是**引用**而非纯文本：chunk_id、页码、来源、年份都在，下游才能溯源 |
| `content.generate` | 模型输出必须过校验：每题有题干有答案、无重复、数量偏差不超过阈值，否则整步失败 |
| `quality.check` | 只报它能证明的；`not_checked` 字段列出**没查的四项**（符号推导、数值样例、解题步骤、跨材料一致性） |

离线时 `content.generate` 用模板占位，题干里明写「[模板占位]」——**模板伪装成生成结果，比空着更糟**。

### 过程中修掉的四个真问题

1. **知识库读不出来。** `knowledge_questions / chunks / document_versions` 没有任何 SELECT 策略，而全局 `FORCE RLS`——除超级用户外谁都查不到。已补三条策略，规则与 `knowledge_sources` 一致：来源是平台内容或属于你，才可读。
2. **主题抽取把整句话当检索词。** 「用高考题出 4 道三角函数题」整串去 `ILIKE`，匹配不到任何片段。改为剥离来源词、动词、数量词与句末「题」，得到「三角函数」。
3. **执行器没有把 execution 推出 `queued`。** 步骤跑完了，但因为执行还在 `queued`，契约里没有 `steps_succeeded` 这条边，终态永远停在 `queued`。现在执行器先按契约把执行推进到 `running`。
4. **步骤只拿到直接依赖的输出。** `quality.check` 需要检索结果来核对引用，但它的直接依赖是生成步骤。改为传**依赖的传递闭包**——无关分支仍然不可见，步骤隔离仍然成立。

### 两个我自己的错误，也记下来

**① 把会话重启当成了项目崩溃。** 一次 210 秒的等待调用返回「结果未落盘」，我据此排查——实际是宿主进程重启（Web 端口从 63342 变成 54881），被掐断的只是一个 sleep，无副作用。仓库状态完好：提交在本地也在远端，工作区干净。**教训：先验证状态，再解释现象。**

**② 把一次未刷新的轮询当成了 CI 挂起。** 我读到 run #42 的 `in_progress` 快照，就断言「第 18 步挂住了」，还为此加了超时与注解标记。事实是那次 run 在 78 秒内全部成功，第 18 步只用了 3 秒——**我读到的 `updated_at` 停在创建时刻，而我没有注意到这个细节**。

第二条更值得记：我用一个不可靠的信号（缓存快照）推出了一个具体结论（挂起），并据此改了代码。**观察的可信度必须与结论的力度匹配**——不确定时应当直接查那个 job 的最终状态，而不是从列表快照推断。

那两处改动（步骤超时 + 阶段注解）本身是有价值的，保留：以后真的挂住时，注解会直接指出停在哪一步。

**流水线（run #42，十八步全过，78 秒）。**

**仍未做**：SSE（进度只能轮询）、认证端点、材料落库与导出。**题目有了，教案文件还没有。**

----------------------------------------

------------------------------------------------------------------------


## D.45 2026-11-04 材料投影与草稿：学生版是真的没有答案

**交付：** `app/services/materials.py` + 工具 `material.create_draft` + `test_materials.py`。

流水线现在以一份**草稿**结束：4 道题 → 一份 AST → 教师版 4 个答案、学生版 0 个答案。

**关键决定：投影按 AST 自己声明的可见性做，不去猜哪些字段该删。**

文档里每个块都有 `visibility`（`student` / `teacher`）。学生版是把 `teacher` 块**从结构上删掉**，不是设成隐藏、不是加 CSS、也不是复制一份再抹字段。所以：

```text
学生版 JSON 序列化之后，不包含任何解释文字（测试逐个断言）
答案/solution 键在序列化结果里根本不存在
```

一条渲染测试会被 CSS 隐藏骗过去；这条不会。**这正是设计文档里“学生版从 AST 投影”那句话的可执行形式。**

**测试里最关键的断言写法：**

```python
student_serialised = json.dumps(student, ensure_ascii=False)
assert q["explanation"] not in student_serialised
```

不是“看起来没有”，是“序列化之后找不到”。

**其余覆盖：** 一份文档两个投影、导出的副本改动不影响源文档（深拷贝）、草稿修订号递增且不可变、草稿指针指向最新修订、未知 profile 被拒。

**两个小失误，都靠测试立刻暴露：** 忘了在测试里调用 `db.init()`；以及给计划加了「材料落库」这一步后，工具调用数从 3 变 4，旧断言没跟着改。**后者说明“改计划结构会改变下游计数”——这类断言应当从实际计划推导，而不是写死。**

**现在的完整链路：**

```text
一句话需求 → 需求版本 → AI 出方案 → DAG/工具校验 → 审批请求
          → 教师批准 → 启动执行 → 检索 → 生成 → 自查 → 材料落库（草稿）
          → 教师版（含答案）/ 学生版（无答案）两个投影
```

**仍未做**：发布成不可变版本（含质量门禁与发布审批）、导出成 docx/pdf 文件、SSE、认证端点。**草稿有了，能发给学生的文件还没有。**

----------------------------------------

------------------------------------------------------------------------


## D.46 2026-11-04 发布与导出：黄金路径闭合

**交付：** `app/services/publication.py` + `app/services/export.py` + `test_publish_export.py`，以及两份真实样例 `docs/samples/*.docx`。

**一句话需求现在能走完全程，产出一个可以发给学生的文件。**

### 发布：唯一产生不可回收副作用的操作

四道闸，任何一道不过都不发布：

| 闸 | 拒绝条件 |
| --- | --- |
| 质量报告 | `blocked` 直接拒绝，连审批都不建 |
| 审批状态 | 不是 `approved` 就拒绝 |
| 内容绑定 | 草稿在批准后移动过、或哈希变了，拒绝并提示重新批准 |
| 单次消费 | 同一个审批第二次发布被拒——由数据库的条件 UPDATE 裁决，不是应用层判断 |

版本行记录 `publication_approval_id`，所以一年后问“这一版是谁批的”，不需要翻日志。

### 导出：自己写 DOCX，不引库

DOCX 就是一个装 XML 的 zip。**没有引入 python-docx**，理由不是省依赖，而是：**答案泄漏与否由这条路径决定，不想让它依赖于第三方渲染器的行为。**

渲染器在写出每个段落之前，自己再调一次 `materials.project`——**调用方即使忘了投影，学生文件也不会有答案。**

### 证明方式：解压之后搜文本

测试不是看渲染器的输入，而是把产出的 DOCX 解开、取 `word/document.xml` 的文本、逐题搜答案串：

```text
教师版：3 道题的答案全部命中
学生版：0 条命中，题干全部保留
两个文件的 SHA-256 不同（不是同一份文件换了名字）
两条导出记录都指向同一个源文档哈希（同源）
```

样例文件在 `docs/samples/`：1402 字节的教师版、1222 字节的学生版，学生版小 180 字节——**少的正是答案**。

### 与设计文档的一句话对照

D3 里写过「学生版从 AST 投影，不是隐藏」。这一轮把这句话变成了三个可执行的断言：投影后无答案块、序列化后无解释文本、解压后无答案字符串。**三层都过，才算做到。**

**当前完整链路：**

```text
一句话 → 需求版本 → AI 出方案 → 审批 → 执行 → 检索 → 生成 → 自查
      → 材料草稿 → 发布审批 → 不可变版本 → 教师版/学生版 DOCX
```

**仍未做**：SSE 实时进度、认证端点（首次登录）、PDF 导出、知识库上传界面。

**功能说明的「当前阶段」一节现在过时了**——按约定留到第一版发布时统一改。

----------------------------------------

------------------------------------------------------------------------


## D.47 2026-11-04 认证端点：把系统交给一个真实的人

**交付：** `app/api/auth.py`（register / login / logout / me）+ `test_auth_api.py`。

在此之前，所有端点都需要 token，而**没有任何办法拿到第一个 token**。系统是完整的，但没有人能用。这是唯一一个“挡住了真实使用”的缺口。

**四个端点都不在 D5 里。** 契约的 64 个端点没有 `/auth/*`。按之前的做法：补上、标注、写清理由。

**因此多了一个没有冻结的错误码。**

「用户名已存在」在 18 个错误码里没有对应项。选择是：

| 方案 | 代价 |
| --- | --- |
| 复用 `STATE_CONFLICT` | 让一个冻结的码去表达它没定义的含义，之后没人信任这份契约 |
| **新增 `USERNAME_TAKEN`** | 冻结集合多了一个成员 |

选后者，并把这件事写在模块 docstring 里。**冻结的价值在于“知道什么是冻结的”，而不是“假装没有新东西”。**

**登录不泄露用户名是否存在。** 「用户不存在」与「密码错误」返回完全相同的状态码、错误码和文案——测试逐字段比对两个响应是否一致，而不只看状态码。

**三个安全细节由测试守住：**

```text
密码不以明文入库，hash 自带 KDF 参数，algorithm 记录真实算法
没有任何一行存储明文 token（按 token 明文去查，命中 0 条）
登出后同一 token 立即 401
```

**测试仍然跑在非超级用户角色上。** 这是上一轮踩过的坑：用 `postgres` 测等于关掉 RLS。认证是所有人的入口，尤其不能在这个条件下测。

**流水线（17 个数据库套件）：**

```text
DDL → 结构 → alembic → RLS → Outbox → 身份 → 任务 → 审批 → 执行 → DAG
   → 工具 → 运行对账 → HTTP → Agent → 端到端执行 → 材料 → 发布导出 → 认证
```

**系统现在可以被一个真实的人使用了：注册、登录、一句话提需求、审批方案、等执行、看结果、发布、下载两份 DOCX。**

**仍未做**：SSE 实时进度（现在只能轮询）、PDF 导出、知识库上传界面、管理后台。

----------------------------------------

------------------------------------------------------------------------


## D.48 2026-11-04 事件流：教师能看见“正在做什么”

**交付：** `app/services/event_stream.py` + `GET /conversations/{id}/events` + `test_sse.py`，并把执行器的步骤进度写入这条流。

严格按 D5 的 SSE 契约实现：路径是按对话的，`Last-Event-ID` 用事件序号，帧里 `id` 就是 seq，15 秒心跳。

**没有 Redis，所以“实时”是轮询同一张表。**

这件事必须说清楚而不是含糊过去：**`conversation_events` 是事实来源**，轮询它只可能更慢，不可能更错。真正接 Pub/Sub 时，替换的只是“通知”那一半，回放与去重逻辑不变。代码注释里写的就是这句话。

**两个实现决定，比看起来重要：**

1. **不为整条流占用一个数据库会话。** 每轮回放/轮询开短事务。一条流挂几分钟并占着事务，等于白占一个连接并挡住 vacuum。
2. **回放上界是连接时取的高水位。** 回放窗口内写入的事件由随后的轮询接上——**边界上落下的既不会漏，也不会重**。

**抓到一个真 bug：心跳计时基准写成了 0.0。**

于是第一个空闲轮询立刻满足 `now - 0 >= 15`，客户端会在收到任何数据之前先收到一个 ping。改成以流开始时的时间为基准。**这种错误不会让功能失效，只会让协议看起来“有点怪”——而“有点怪”的东西没人会去深究，正是最该修的。**

**执行器把每步进度写进流里**，与步骤完成处于同一事务——**步骤提交了，事件一定在；事件描述了步骤，步骤一定没回滚**。

**测试（6 组）：**

| 场景 | 断言 |
| --- | --- |
| 序号 | 每个会话内 1,2,3 单调递增 |
| 回放 | `Last-Event-ID: 1` 之后只收到 2、3，不重不漏 |
| 实时 | 消费期间写入的事件被送到，序号正确、载荷完整 |
| 心跳 | 空闲时发出注释帧 `: ping` |
| 帧格式 | 以空行结尾、`id` 与存储序号一致、包含 D5 的六个字段 |
| 全量回放 | 1..5 无重复 |

**流水线（18 个数据库套件）。**

**仍未做**：PDF 导出、知识库上传界面、前端。**后端现在能把一件事从头做到尾并让教师看见过程；但它还只有 API。**

----------------------------------------

------------------------------------------------------------------------


## D.49 2026-11-04 PDF 导出、教师上传，与第五次 RLS 写入失效

**交付：** `app/services/pdf.py`、`app/api/knowledge.py`（上传/列表）、`test_pdf_upload.py`。

### PDF：转换而不是手写

中文 PDF 需要嵌入字体子集，手写渲染器要么丢中文、要么嵌一份我们无权嵌入的字体。改用 LibreOffice 转 DOCX → PDF。

**保证是继承来的，不是重新建立的**：答案不泄漏这条性质在 DOCX 层已经证明（一份 AST、学生投影、解压后搜文本），PDF 是它的转换，无法重新引入源文件里没有的答案。所以测试只断言它能证明的事：真 PDF 头、非空、教师版与学生版不同。

**这台机器上 PDF 未能验证**：soffice 在受限环境里挂起（与 Docker 同因——需要命名管道做单实例通信）。测试因此只守契约的两端：**要么产出真 PDF，要么给出可操作的错误，绝不静默返回空文件。**

### 上传：保存了，但没有解析

教师上传整卷，系统记录来源与文件版本。**解析与切分没有实现**，版本停在 `processing`。

这是刻意的：一个标成 `indexed` 却没有任何 chunk 的版本，会让检索**安静地返回空**，而看起来一切正常。

上传恒为 `scope=teacher`、`rights_status=unverified`、`distribution_scope=private_teacher`。教师无法通过参数把自己的上传提升成平台共享内容。

### 第五次同类问题：有读策略，没有写策略

`material_draft_revisions`、`material_versions`、`knowledge_categories`、`knowledge_document_versions` ——四张表在“以非超级用户运行时”依次报 `new row violates row-level security policy`。

**根因不是某张表漏了，而是缺一条统一规则**：带 `owner_id` 的表只写了 SELECT 策略。修复方式不再逐表补：

| 规则 | 覆盖 |
| --- | --- |
| 带 `owner_id` 的表，一律加 owner `ALL` 策略 | 全库（RLS 策略是 OR 关系，不削弱已有的平台读策略） |
| 子表（无 `owner_id`）按父表归属加写策略 | knowledge 的 6 张子表 |

**为什么之前一直没发现**：这些表只在非超级用户下才会拒绝，而绝大多数套件连的是 `postgres`。**「用超级用户测 RLS」这个坑，这是第三次踩到**（前两次：cross-tenant 读到 200、`materials` 插入被拒）。它每次都以新面孔出现，因为每加一张表就有一次新的机会。

### 仍然存在的债务（必须写下来）

`check_all` 现在会报：**还有 29 张表没有任何策略**，其中 `agent_runs`、`agent_step_executions`、`agent_tool_executions`、`agent_runtime_events`、`conversation_events`、`agent_plan_steps` 等**是应用真实写入的**。它们现在能工作，只因为运行在超级用户下——**换成真实角色就会 500**。

这是当前最严重的已知问题，比任何未实现功能都严重：它只在部署后才发作。

**流水线（19 个数据库套件）。**

----------------------------------------

------------------------------------------------------------------------


## D.50 2026-11-04 策略覆盖补齐：82/82，以及没做完的那一半

**结果先说：82 张表全部有策略，检查项加进静态流水线，并且证明了它会红。**

### 补了什么

| 规则 | 数量 |
| --- | --- |
| 能追到 owner 的表 → 按父表归属（含两跳） | 21 |
| 平台/参考表 → 服务范围 `USING (true)` | 11 |
| 平台表原有 SELECT 策略 → 升级为 ALL（种子数据要写） | 11 |

改完 82 张表、88 条策略，注册表校验通过。**没有一张表的策略列表是空的**——空列表在 `FORCE RLS` 下等于“拒绝所有人”，这是前五轮反复踩的同一个坑。

### 棘轮：`check_rls_coverage.py`

只做一件事：**任何表没有策略，检查失败**。加进 `check_all`，变成第 16 项。

**它第一次跑出来是假绿的**：路径少算一层，扫到 0 张表，于是“0 张表缺策略”——通过。这种检查比没有更危险，因为它在报告一件它没检查的事。

修好后当场反向验证：临时抹掉 `conversation_events` 的策略，检查报 `tables without a policy: 1` 并退出 1。**一个不能被证明会失败的检查，不算检查。**

### 测试迁移：做了一半，说清楚是哪一半

| 以真实角色运行（8 个套件） | 仍以超级用户运行（8 个套件） |
| --- | --- |
| api · auth · identity · materials | agent · executions · executor · pdf_upload |
| outbox · publish_export · steps · tasks | plans · runs · sse · tools |

**为什么停下**：剩下这 8 个的障碍不在产品代码，而在**测试播种方式**——它们用一个没有 owner 上下文的会话去写 owner 数据。逐个重写可行，但这一轮预算不够，硬做会留下半坏的状态。

期间有两处我判断错并撤回：

1. 一次性把所有 `system_session()` 换成 `session_for(user_id)`，结果 13 个文件 `NameError`（局部变量名不同）。**批量替换如果没有逐个验证，就是把一个错误均匀地散播开。**
2. `pdf_upload` 退回超级用户后，“另一个老师看不到上传”这条断言反而失败——因为超级用户绕过 RLS。它**只在真实角色下才有意义**，而它在真实角色下又因 `material_versions` 写策略不成立而失败。最终让它显式打印 `skip` 并指向 `run_rls_test.ps1`，而不是假装通过。

**这条我保留原样**：一个在超级用户下“通过”的租户隔离断言，是比没有断言更坏的假证据。

### 仍然存在的两处策略缺陷

`conversation_events`（按父 `conversations` 归属）与 `material_versions`（按 `owner_id`）在真实角色下仍然拒绝插入。谓词写法有问题，尚未定位。**它们现在不阻塞任何功能，只阻塞那 8 个套件的迁移。**

**流水线：19 个数据库套件 + 16 项静态检查，全绿。**

----------------------------------------

------------------------------------------------------------------------


## D.51 2026-11-04 谓词其实是对的，错的是播种用的会话

**结果：13 个套件以真实角色运行，3 个仍是超级用户。19 个套件全绿。**

### 上一轮判断错了

我在 D.50 里写「`conversation_events` 与 `material_versions` 的谓词写法有问题」。**这两条谓词是对的。**

探测脚本在真实角色下打印了四项事实：

```text
current_user : chilon_app_test
guc          : '<uid>'          ← 事务内已设置
helper()     : <uid>            ← 返回值正确
super/bypass : False / False    ← 没有特权捷径
```

三者一致，插入成功。于是问题不在策略，而在**调用方用哪个会话去写**。

### 真因：`db.system_session()` 被用在了需要 owner 上下文的地方

`system_session()` 不设 `app.current_user_id`——这是它存在的理由（后台任务必须显式指定为某个教师）。但测试的播种代码把 owner 数据塞进这个会话，于是 `owner_id = app_current_user_id()` 变成 `owner_id = NULL`，被拒。

SSE 套件里那一行最典型：

```python
async with db.system_session() as s:      # 没有上下文
    await event_stream.append_event(...)  # conversation_events 需要父表归属
```

改成 `db.session_for(user_id)` 即可——**产品代码一行没改**。

### 我怎么绕远的

| 动作 | 后果 |
| --- | --- |
| 假设策略写错 | 花时间重写谓词（本来就是对的） |
| 一次性全库替换 `system_session` → `session_for(user_id)` | 13 个文件 `NameError`，局部变量名不同 |
| 又全部回退 | 把 SSE 那处**正确**的调用也退回了 `system_session`，于是“谓词有问题”的假象持续 |

**每次撤回复位到更差的版本，而这个更差的版本又成了下一轮的证据。** 这是这轮最贵的教训：**回退不是“回到之前”，而是“再改一次”，同样需要验证。**

最后用 AST 只替换“所在函数确实有 owner 参数”的调用，才没有制造新的 `NameError`——但它在创建用户那段又踩了鸡生蛋（`user_id` 在块内赋值），`test_executor` 因此报了 `UnboundLocalError`。

### 现在的分布

| 真实角色（13） | 超级用户（3） |
| --- | --- |
| api · auth · executions · identity · materials · outbox · pdf_upload · plans · publish_export · sse · steps · tasks · tools | agent · executor · runs |

剩下三个都是同一个形状：**用户在那个块内才被创建**，所以要拆成“先建用户、再开 owner 会话”两步。这不是难点，只是没做完。

**策略层结论：82 张表、88 条策略，谓词全部正确。** 上一轮“两处策略缺陷”的说法撤回。

----------------------------------------

------------------------------------------------------------------------


## D.52 2026-11-04 全部 16 个套件以非超级用户运行

**19 个数据库套件、16 项静态检查，全绿；16/16 的测试文件连接的是真实角色。**

### 最后三个的共同形状

`agent`、`executor`、`runs` 都卡在同一处：**用户在那个块里才被创建**，而紧接着就要写该用户的数据。`session_for(user_id)` 在赋值前引用 `user_id`，于是 `UnboundLocalError`。

拆成两步即可：先用无上下文会话建用户，再用该用户的上下文写数据。

`runs` 是另一种：它的 `invocation_count()` 用 `system_session()` 数行，RLS 下数到 0。**这不会报错，只会让“没有产生第二次调用”这条断言空洞地通过**——比失败更危险。加上 owner 参数后它才真的在数东西。

### 一个必须承认的设计结论

`executor` 的播种同时写了**平台知识**（`scope='platform'`、`owner_id` 为 NULL）和**租户数据**。平台行在应用角色下没有写策略——**这是对的**：教师不该能凭空造出授权内容。

所以我没有放宽任何策略来让测试通过，而是给测试加了一个**管理员会话**（`support.admin_session()`）：平台内容按迁移的方式播种，租户数据按教师的方式播种。**测试通过的方式必须和生产里它该被创建的方式一致。**

### 分布

| 以真实角色运行 | 以超级用户运行 |
| --- | --- |
| 16 个套件 | **0** |

### 这条线走完意味着什么

从 D.49 发现“29 张表没有任何策略”到现在：

```text
82 张表   全部有策略（棘轮检查守着，缺一条就红）
88 条策略 谓词全部正确（D.51 已验证）
16 个套件 全部以生产同款角色运行
```

**“策略不缺了”和“每个套件都在生产条件下验证过”是两句话，现在两句都成立。**

这是这个项目第一次可以说：**它在它所声称的条件下被验证过。**

----------------------------------------

------------------------------------------------------------------------


## D.53 2026-11-04 教师界面：从只能 curl 到一个教师能用的页面

**交付：** `app/api/ui.py`（服务端渲染）+ `database/seed/platform_tools.sql` + `test_ui.py`。

### 为什么不建 React

这个缺口的定义是「教师只能用 curl」。引入前端构建链会在教师打开第一个页面之前，先增加一套工具链、一份打包配置和一个部署产物。**服务端渲染的 HTML 在同一个进程里运行、调用同一批服务、用同一个客户端就能测。**

代价是界面朴素。这是**已知的、可接受的**取舍，不是没做完。

### 界面不允许比 API 多做事

页面上的每个动作都调用既有服务：`agent.propose_plan`、`agent.approve_plan`、`executions.start_execution`、`executor.run_once`、`publication.*`、`export.*`，顺序与 API 完全一致。**如果界面能做到 API 做不到的事，那它就是规则的第二份实现**——这正是这个文件必须避免的。

两个刻意的设计：

* **发布是两个按钮。** 请求与确认分开，因为它们在模型里就是两步。一个「发布」按钮会把审批伪装成形式。
* **执行是同步的。** 点击「批准并执行」会等执行器跑完。单进程部署下这是诚实的；有队列时它会立刻返回，让进度面板去等。

### 顺手抓到的三个真 bug

1. **中文文件名让下载 500。** `Content-Disposition` 直接放中文，HTTP 头只能 latin-1，响应在出口处抛 `UnicodeEncodeError`。改成 RFC 5987 的百分号编码。
2. **`agent_plan_steps` 的列名是 `step_key` 不是 `key`。** 页面一读就报 `UndefinedColumn`。
3. **`tasks.create_task` / `get_task` 返回对象而非字典。** 按字典取 `["id"]` 直接 `TypeError`。

### 一个真正的产品缺口：新教师什么都做不了

注册后第一次出方案直接失败：`no tools are granted to this teacher`。而且**库里根本没有平台工具定义**——`agent_tool_definitions` 是空的。

这意味着在任何全新部署上，产品对第一个用户是不可用的。

两处修复：

| 缺什么 | 修法 |
| --- | --- |
| 平台工具定义 | `database/seed/platform_tools.sql`，部署时执行一次（幂等） |
| 教师的默认授权 | `agent.ensure_default_grants()`，注册时在该教师自己的上下文里执行 |

授权必须用 `session_for(user_id)` 写——`agent_tool_grants` 是 owner 作用域，注册会话没有上下文。

**这个缺口只能靠真的走一遍用户流程才暴露。** 20 个套件全绿的时候，它还在那里。

### 测试：第一次以“人”的方式验证

`test_ui.py` 用 cookie 和表单走完：陌生人被重定向 → 注册拿到 cookie → 一句话建任务 → 看到方案步骤 → 批准 → 执行成功 → 请求发布 → 已发布 → 下载两份 DOCX（真 zip、两份不同）→ 登出 → 另一个教师看不到该任务。

**流水线：20 个数据库套件 + 16 项静态检查，全绿。**

----------------------------------------

------------------------------------------------------------------------


## D.54 2026-11-04 部署：一条命令，以及只有真跑才看得见的三个问题

**交付：** `Dockerfile`、`docker-compose.yml`、`scripts/start.sh`、`backend/requirements.txt`、`database/tests/check_deploy.py`、`/healthz`。

**验证方式不是“文件都在”，而是真的构建、启动、走完教师流程：**

```text
docker compose up -d --build
→ 登录页 200 → 注册 303 → 一句话建任务（方案 v1）→ 批准执行 succeeded
→ 发布 已发布 → 下载学生版 1166 字节的真 DOCX
```

### 每次都做，不只是第一次

入口脚本在**每次**启动都执行三步，且三步都幂等：等数据库、`alembic upgrade head`、应用平台种子。服务器最后启动——**迁移失败就不会留下一个半死不活的进程**。

`/healthz` 只回报进程存活，**不查数据库**。依赖故障不该让进程看起来也死了，否则编排器会去重启一个本身正常的服务。

### 三个只有真跑才暴露的问题

**① 镜像没有 `schemas/`。** 迁移成功、种子成功，然后服务在 `import` 时死掉：`FileNotFoundError: /app/schemas/state_machines.v1.json`。契约文件在仓库根，Dockerfile 只拷了 `backend/`。

**② `apt-get update` 在这个环境根本连不上仓库。** 而那个依赖本来就不该有——`psycopg[binary]` 自带 libpq，`curl` 只用于健康检查。改成纯 Python 探测后，镜像少了两层、去掉了唯一的系统包依赖。

**③ 数据库密码只在数据卷第一次初始化时生效。** 我在两次命令里用了不同的密码，容器一直 `password authentication failed`，而数据库本身是健康的。已写进 README。

**这三条没有一条能被“文件都在、检查都过”发现。**

### 一个静态检查，防止它再烂

`check_deploy.py` 读文本、不构建镜像：Dockerfile 里的 `COPY` 路径是否存在、是否有 `HEALTHCHECK`、是否以非 root 运行、compose 是否等服务健康、入口脚本是否跑了迁移和种子且 `set -eu`、健康检查探测的路径是否真的在 `main.py` 里存在、以及**`schemas/` 有没有被拷进镜像**。

它当场抓到了 ①：`Dockerfile copies a path that does not exist: alembic.ini`（`alembic.ini` 在 `backend/` 下）。

**一个不能失败的检查不算检查**——这条也在 D.50 记过一次，这次它立刻兑现了。

**流水线：20 个数据库套件 + 17 项静态检查。**

----------------------------------------

------------------------------------------------------------------------


## D.55 2026-11-04 阶段收束：现在的真实状态

### 一句话

**一句话需求 → AI 出方案 → 教师批准 → 执行 → 出题自查 → 材料草稿 → 发布 → 教师版/学生版 DOCX，全链路可运行；后端、前端、容器部署三层都已验证。**

### 规模（实测，2026-11-04）

| 项 | 数 |
| --- | --- |
| 提交 | 71 |
| 注册表表数 | 82（**部署 81 + 可选 1**，可选表需 pgvector，按设计不生成） |
| 已部署策略 | 87（81 张表全覆盖） |
| 服务模块 | 17 |
| API 模块 | 10 |
| HTTP 路径（OpenAPI） | 21（另有 UI 页面与 `/healthz` 不入 schema） |
| 数据库套件 | 20 |
| 静态检查 | 17 |
| 设计记录 | 55 条（D.1–D.55） |

**一处口径更正**：此前写「82 张表全部有策略」把两个 82 混为一谈。实际是：

```text
注册表 82 = 生成并部署 81（全部有策略）+ knowledge_question_embeddings（可选，pgvector，未部署）
活库  82 = 81 + alembic_version（Alembic 记账表，应用不访问，无需策略）
```

结论不变（**每张部署的表都有策略**），但两个 82 不是一回事——**这种混用正是会误导后来人的地方**。

### 本轮（D.44–D.55）完成的事

| 记录 | 内容 |
| --- | --- |
| D.44 | 三个工具 + 执行器：一句话能出题、带引用、带自查 |
| D.45 | 材料投影：一份 AST，教师版/学生版按 `visibility` 投影 |
| D.46 | 发布与导出：单次审批、不可变版本、DOCX |
| D.47 | 认证端点（D5 缺口，含新增错误码 `USERNAME_TAKEN`） |
| D.48 | SSE 事件流：回放、实时、心跳 |
| D.49 | PDF 导出、教师上传，以及暴露的 RLS 写入缺口 |
| D.50 | 策略覆盖补齐 + 棘轮检查（**它第一次是假绿的**） |
| D.51 | 更正：谓词本来是对的，错的是播种会话 |
| D.52 | 16/16 套件改以非超级用户运行 |
| D.53 | 教师界面（服务端渲染），暴露「新账号无工具授权」 |
| D.54 | docker compose 部署，三个只有真跑才看见的问题 |
| D.55 | 本记录 |

### 三层验证，缺一不可

```text
契约层  82 表 / 88 条策略声明 / 状态机与动作面冻结
代码层  20 个数据库套件 + 17 项静态检查，全部以生产同款角色运行
运行层  docker compose 真的起来，容器里走完教师流程并下载到真 DOCX
```

**只用前两层时，“新账号无法出方案”和“镜像里没有 schemas/”都活着。** 两个都是在真跑时第一次出现。

### 仍开着的口子（按影响排序）

1. **知识库解析/切分未实现** —— 教师能上传卷子，版本停在 `processing`，检索用不到它。**能上传但用不上**，这是第一位。
2. **没有密码重置** —— 忘了只能重建容器（会清数据）。
3. **PDF 未在受限环境验证** —— soffice 需要命名管道，沙箱里挂起；DOCX 已验证。
4. **界面朴素** —— 功能完整，样式是基础排版。
5. **无备份/恢复演练** —— 没有 `pg_dump` 与恢复流程。
6. **债务**：`created_by` 一类列没有外键（缺「系统主体」概念）；`agent_runtime_events.occurred_at` 无默认值。

### 留给下一次的运行方式

```bash
docker compose up -d --build          # http://127.0.0.1:8000/
# 无内置账号：第一个用户在 /ui/register 自建（默认口令是最常见的事故来源）
# 测试账号（当前本地环境）：teacher_demo / Chilon2026!
```

```bash
.venv\Scripts\python.exe tools/check_all.py                    # 17 项静态检查
pwsh -NoProfile -File database/tests/run_ui_test.ps1             # 任一套件
```

### 这一阶段反复出现的三个教训

1. **用超级用户测 RLS，等于没测。** 它换过五张面孔：跨租户读到 200、owner 表插入被拒、`system_session` 播种、计数返回 0 让断言空洞通过、`material_versions` 写不进去。
2. **不能失败的检查比没有检查更危险。** 两个检查曾以「扫到 0 个对象」的方式通过。
3. **回退不是“回到之前”，而是“再改一次”。** 一次全量替换制造 13 个 `NameError`，回退时又把正确的那处改错，于是一个错误结论（“谓词有问题”）活得比两轮都长。

----------------------------------------

------------------------------------------------------------------------


## D.56 2026-11-05 知识库摄入：上传的卷子终于能被检索到

**交付：** `app/services/ingestion.py`、上传即解析、`POST /knowledge/sources/{id}/ingest`、`test_ingestion.py`。

在此之前，教师上传卷子会被保存、显示在列表里、**然后永远用不上**：版本停在 `processing`，检索返回 0 条，而且从外表看不出任何区别。这是唯一一个「功能在、但用了等于没用」的缺口。

### 切分规则被检索设计反向决定

`knowledge_search` 的关联条件是 `q.stem_locator = c.locator`。因此**一道题必须是一个块**：如果一个块装了 3 道题，join 会把结果扇出成 3 行。

所以切分先按题目边界做（`1.` `1、` `（1）` 三种开头），题目前的标题/说明自成一个块，`stem_locator` 直接等于该块的 `locator`。这不是偏好，是**被下游逼出来的约束**。

### 只用规则，不用模型

分错了可以重新摄入；模型分的结果无法复现、无法 diff。`segmentation_source` 一律 `rule`、`segmentation_status` 一律 `auto`，将来要复核时能一次捞出所有“机器猜的”。

### 四个「我猜的」和四个「声明过的」

这一轮几乎全部时间花在同一件事上：**我写的值不在词表里**。

| 我写的 | 声明的 | 后果 |
| --- | --- | --- |
| `status='ok'` | `succeeded / failed / running / cancelled` | CHECK 拒绝 |
| `stage='parse_and_segment'` | `varchar(16)`，值为 `scan/parse/ocr/segment/classify/index` | 超长被拒 |
| 让 `current_paper_question_type` 留空 | 该列 **NOT NULL 且无默认** | 插不进去 |
| 解析失败后留在 `processing` | `failed` 是**已声明**的状态 | 把坏文件伪装成还在处理 |

前三个是猜，第四个是**我根本没去看列了哪些状态**——而 `failed` 一直都在那里。

**教训不是“要查词表”，而是“这些词表已经存在，我却先写代码再查”**。四次里没有一次是因为没有声明。

第三项的处理值得单说：`current_paper_question_type` 是分类器产物，v1 解析器不分类。NOT NULL 会逼它**编一个题型**——那是这个项目最不能做的事。所以改注册表让它可空：**NULL 就是“尚未分类”的诚实表达**。这是一次 schema 变更（`0001_baseline` 重新生成）。

### 一条旧测试记录的是旧行为

`pdf_upload` 里有一条断言：`the version is processing, not indexed`。它写于“上传不解析”的年代，因此**在修复之后变成了失败**。

我没有绕过它，而是改了断言和它的名字（`the upload is parsed immediately`）。**测试也会把 bug 固化成规范**——这次它以“一条本该失败的断言失败”的形式提醒了我，算幸运。

### 现在教师能看到什么

```text
上传 .docx → 立即返回 chunks=4, questions=3, lifecycle=indexed
→ 检索能命中自己上传的段落，并关联到具体题号
→ 另一个教师检索到 0 条
→ 重新摄入是替换而非追加（不会让一篇论文的权重翻倍）
→ PDF 目前拒绝解析，版本标 failed，理由写明「请上传 .docx」
```

**测试覆盖：** 上传即索引、locator 与题目一一对应、所有者可检索、他人不可见、重新摄入幂等、PDF 失败路径与运行记录。

**流水线：21 个数据库套件 + 17 项静态检查。**

### 仍开着的口子

1. **PDF 不能解析** —— 需要文本抽取库；当前直接拒绝并说明怎么做。
2. **不提取答案** —— 题目只有题干，`answer_locator` 留空；出题时仍靠模型生成答案。
3. **不识别题型** —— `current_paper_question_type` 为 NULL，等待分类器。
4. 密码重置、界面美化、备份演练仍待办。

----------------------------------------

------------------------------------------------------------------------


## D.57 2026-11-05 答案提取：让答案来自卷子，而不是模型现编

**交付：** `ingestion.segment()` 增加答案抽取、答案独立成块、`knowledge_search` 带出答案、生成提示词优先采用原卷答案。

### 答案独立成块，是“可投影”的前提

提取出来的答案**不留在题干里**，而是写成一个独立 chunk，`knowledge_questions.answer_locator` 指向它，`knowledge_search` 再按 locator 关联回来。

这样做的理由和 D.46 的学生版是同一条：**要排除一份内容，前提是它是一份独立的内容**。答案和题干混在一个块里，任何下游想“去掉答案”都只能靠猜哪一行是答案。

三种形态都识别，全部确定性：

```text
答案：π              ← 题内联
【答案】π            ← 题内联
参考答案 → 2. 2      ← 卷末答案区，按题号回填
```

**没有答案的题保持 NULL**，不编造。测试里专门放了一道无答案题（Q4）来守这条。

### 生成器现在优先用原卷答案

`knowledge_search` 的每个 hit 带上 `answer`，参考资料块里写成：

```text
- chunk_id=…：《2023 全国甲卷》已知三角函数 f(x)=sin(2x+π/3)…
    该题原卷答案：π（优先采用）
```

**从授权试卷抄来的答案可溯源，模型编的答案不可溯源。** 这条优先级写进提示词，不是靠模型自觉。

### 一处仍然存在的不对称

学生版的投影保证是**针对材料文档**的（答案块 `visibility=teacher`，投影时物理删除）。而检索出的答案进入的是**生成过程**，不进入学生版——两者不冲突，但值得说清：**答案出得去，是因为它在生成侧；它出不去，是因为它在投影侧。**

**流水线：21 个数据库套件 + 17 项静态检查。**

----------------------------------------

------------------------------------------------------------------------


## D.58 2026-11-05 题型识别：能判就说，判不了就 NULL

**交付：** `ingestion.classify()`、写入 `current_paper_question_type`、检索结果带出题型、提示词里告知题型。

### 信号是有强弱顺序的

| 顺序 | 信号 | 依据 |
| --- | --- | --- |
| 1 | 章节名含「多选/多项选择」 | 整节都成立 |
| 2 | 章节名含「填空」/「解答」「计算」「证明」 | 整节都成立 |
| 3 | 章节名含「选择」 | 但仍要看题干 |
| 4 | 题干里出现「正确的有」「至少有一项」 | **比泛化的「选择题」更具体** |
| 5 | 题干里 ≥2 个选项 | 内容判定 |
| 6 | 题干里有 `____` 或 `（  ）` | 填空 |
| 7 | 都不成立 | **NULL** |

第 3 与第 4 的先后是这一轮唯一的调整：一开始「选择题」章节直接判 `single_choice`，于是「下列说法正确的有」被判成单选。**更具体的信号应当压过更泛的信号**——章节说的是这一节大体是什么，题干说的是这一题是什么。

第 7 条是重点：**判不出来就留 NULL，不设默认值。** 题型会流入评分方式和排版，一个没人检查过的猜测比空值更糟。可空这一列是 D.56 刚改的，正是为了能表达“尚未分类”。

### 题型现在有下游

检索结果里带上 `question_type`，生成提示词写成 `原卷题型：single_choice`。**模型知道这一题在原卷里是选择题，就不会把它写成解答题。**

### 测试

```text
Q1（选择题+选项）  → single_choice
Q5（填空题+空）    → fill_blank
Q6（解答题章节）   → free_response
「选择题」章节 + 「正确的有」 → multiple_choice
无任何线索的文字   → NULL
检索命中携带题型   → ok
```

样例卷也从 4 题扩到 6 题、三段章节、12 个块，`chunks/questions/answers` 的计数断言一并更新。

**流水线：21 个数据库套件 + 17 项静态检查。**

----------------------------------------

------------------------------------------------------------------------


## D.59 2026-11-05 PDF 摄入：有文字层就读，扫描件明说读不了

**交付：** `extract_pdf_blocks()`（pypdf）、页码进入 locator、英文答案标记、`tests/pdf_fixture.py`、`pypdf` 进入 requirements 与 CI。

### 边界先说清楚

**支持有文字层的 PDF；扫描件与拍照件不支持。** 后者需要 OCR，本轮没有实现。

拒绝的方式是重点：扫描件解析后得到空文本，**如果返回空列表，看起来会像“一份能解析但没有内容的文档”**——版本标成 `indexed`，检索永远返回 0，而所有列表页都显示正常。所以空文本被当作错误：

```text
这个 PDF 没有文字层（可能是扫描件或拍照件），需要 OCR 才能解析；
请上传可复制文字的 PDF，或先把文件另存为 .docx
```

版本标记 `failed`，运行记录写 `unsupported_format`。

### 页码进了 locator

DOCX 的 locator 是段落区间，PDF 的 locator 多一个 `page_number`。这两种形状共存于同一个 jsonb 列，因为**“这段话在第几页”是 PDF 唯一能给的位置信息**，丢掉它等于丢掉引用能力。

```text
{"paragraph_start": 1, "paragraph_end": 3, "page_number": 1}
```

### 测试不借用被测代码

`tests/pdf_fixture.py` 手写 PDF 的字节（对象、xref 偏移、文本操作符），**不用 PDF 库生成夹具**。用同一个库生成再用它解析，会把“格式里真正会坏的部分”绕过去。

夹具只用 ASCII（Helvetica 没有内置中文字形，嵌入中文字体是另一个问题）。因此顺手补了英文答案标记 `Answer:` / `Ans:` / `Solution:`。

### 三条断言守住了失败方向

```text
有文字层 → indexed，2 题，1 个答案，locator 带 page_number，Q1 判为单选
扫描件   → failed，理由含 OCR
假 PDF   → failed，理由含可替代做法
```

**流水线：21 个数据库套件 + 17 项静态检查。新增依赖 pypdf（已锁定版本，已进 CI 安装行与镜像）。**

----------------------------------------

------------------------------------------------------------------------


## D.60 2026-11-05 知识点标签：让“出一道三角函数题”真的按考点去找

**交付：** `app/services/taxonomy.py`（含版本号）、`knowledge_questions.current_knowledge_points` 写入、检索按知识点匹配、测试断言。

### 这是我编写的课程数据，而且不完整

词典覆盖高考数学的主要考点（三角、数列、导数、解析几何、概率统计等 14 项），**它不是国家考纲，也不打算假装是**。带版本号 `cn-gaokao-math-starter-1`，因为真实部署应当换成经审校的版本，而换版本不该动解析器。

两条守住诚实的规则：

* **没有默认标签。** 匹配不到就返回空数组。给每道题都打上点什么，标签就彻底失去筛选价值——标签的全部意义是“这道题讲的是这个”。
* **关键词是证据，不是意图。** `sin(2x)` 是三角函数的证据；一句话里顺带提到“函数”可能误标——这正是标签存成**数组 + 版本**、而不是单一权威结论的原因。

### 顺序与抑制，都是被误标逼出来的

第一次跑出来 Q1 的标签是 `[三角函数, 导数及其应用, 函数]`——因为题干里有“单调递增区间”。

**三角函数的单调性不是导数题。** 于是加了两条规则：

| 规则 | 作用 |
| --- | --- |
| 更具体的排在前面 | `三角恒等变换` 先于 `三角函数`，否则所有恒等变换题都被淹没在三角函数里 |
| 具体命中时抑制上位概念 | 命中 `三角函数` 就丢弃 `导数及其应用` 与 `函数` |

现在是 `[三角函数]`。**误标不是“多一点信息”，它会让“给我导数题”返回三角函数题。**

### 标签必须能被检索用到，否则只是存着

`knowledge_search` 现在同时按**文本命中**和**知识点重叠**匹配：

```sql
c.text_content ILIKE :pattern
OR (q.current_knowledge_points && CAST(:topic_points AS text[]))
```

检索时用**同一套词典**把课题（“勾股定理”）映射成知识点（“解三角形”），再去匹配题目的标签。

测试里那条断言是我最想守住的：

```text
检索「勾股定理」→ 命中 Q3
且 Q3 的题干里没有「勾股定理」这三个字
```

**命中来自标签，不是来自字面。** 这正是标签存在的理由。

**流水线：21 个数据库套件 + 17 项静态检查。**

### 已知局限

* 词典是按关键词匹配，**没有做分词**，因此“函数”这类高频词仍然会带来误差。
* 标签只有一级，没有二级考点（如“三角函数的图象变换”）。
* 词典本身需要领域专家审校；现在这份是能跑通的起点，不是终点。

----------------------------------------

------------------------------------------------------------------------


## D.61 2026-11-05 密码找回：没有邮件通道时，重置只能是一次管理操作

**交付：** `app/services/passwords.py`、`POST /auth/users/{id}/password-reset`（管理员）、`POST /auth/password`（改自己的）、`tools/reset_password.py`（运维）、`test_password_reset.py`。

在此之前，老师忘了密码**只能重建容器，而重建会删掉全部数据**。这是整个系统里后果最直接的一个缺口。

### 先说清楚为什么不做“自助重置”

没有邮件通道。任何“未登录即可设置新密码”的流程，本质上都是**多几步的账号接管**。所以：

| 场景 | 路径 |
| --- | --- |
| 记得旧密码，想换 | `POST /auth/password`（自己改） |
| 忘了密码 | 管理员端点，或运维脚本 |

**这不是没做完，是当前条件下唯一诚实的形态。** 等有邮件或短信通道，再加自助找回。

### 重置必须吊销全部会话

一次不吊销旧 token 的“重置”不是重置——**人们重置密码，通常正是因为怀疑账号已被别人拿到**。所以两条路径都吊销：

```text
管理员重置 → 该用户全部会话吊销
改自己的   → 保留当前会话，吊销其余全部
```

保留当前会话是因为调用方同时证明了“知道旧密码”和“持有当前 token”；其余会话仍然全杀。

### 重置还要解锁

`user_credentials` 里有 `failed_attempts` 和 `locked_until` 两列——**忘了密码通常伴随连续失败被锁**。第一次实现只改了 hash，测试跑出来才想起这两列：

```sql
SET password_hash = …, password_changed_at = now(),
    failed_attempts = 0, locked_until = NULL
```

一个重置完仍然锁着的账号，没有恢复任何东西。

### 两次被测试纠正的判断

1. **`user_credentials` 没有 `updated_at`。** 我按习惯写了它。声明的是 `password_changed_at`。
2. **`revoke_all_sessions` 的参数化写法失败**：`($2 IS NULL OR token_hash <> $2)`，Postgres 无法推断 NULL 参数的类型。改成按需拼接子句——**用类型转换掩盖“这个分支不适用”会更糟**。

还有一条断言被我自己删掉：原本检查“最多 1 个会话存活”，但新增场景合法地产生了 2 个。**它通过与否取决于前面碰巧登录了几次**，属于会为错误理由失败的断言，换成“改密码之前签发的 token 必须失效”。

**流水线：22 个数据库套件 + 17 项静态检查。**

### 仍然开着的口子

* **管理员账号怎么来**：目前只能由运维直接改 `users.is_admin`。没有“首个管理员”的引导流程。
* **`must_change_password` 列没有被使用**：代码不写也不读。要么实现强制改密，要么承认它只是占位——现在它两边都不算。

----------------------------------------

------------------------------------------------------------------------


## D.62 2026-11-05 `must_change_password`：从占位列变成真正的闸

**交付：** 重置时写入、登录时返回、API 与界面都强制、`/ui/password` 页面、`test_password_reset.py` 增两组场景。

D.61 里我写下「这一列既不写也不读，比没有更误导」。现在三处都用上了。

### 写：谁能设定，谁能清除

| 动作 | 标志 |
| --- | --- |
| 管理员重置 / 运维脚本 | **置真** —— 密码是别人给的 |
| 本人改密码 | **置假** —— 密码是自己选的 |

**判断依据是“这个密码是谁知道的”**，不是“是不是修改了密码”。

### 读：登录把它交出来

```json
{"token": "...", "must_change_password": true}
```

客户端不必再问一次。

### 强制：只有三条路由放行

服务端在认证依赖里判断，**不是靠界面自觉**：

```text
放行   POST /auth/password   GET /auth/me   POST /auth/logout
其余   403 "this account must change its password first"
```

界面同样有自己的闸：临时密码下访问任务页会 303 到 `/ui/password`；那个页面只有两件事——说明原因、收新旧密码。

**两层各自成立**：只做界面，curl 就能绕过；只做 API，教师会看到一堆莫名其妙的报错。

### 两处实现失误，都是“看起来改了其实没改”

1. 第一次给 `set_password` 打补丁，SQL 文本没匹配上，**补丁静默失效**——直到测试报出 `must_change_password (got False)` 才发现。字符串替换在没有断言的情况下等于没有执行。
2. UI 里我把辅助函数写成 `page_html`，实际叫 `page`。**导入不会报错**（它是运行时才解析的名字，且只在分支里），是随后跑套件才暴露。

两条都指向同一件事：**改动之后必须跑一条会用到它的路径**，而不是看代码“改对了”。

**流水线：22 个数据库套件 + 17 项静态检查。**

### 仍然开着的口子

* **首个管理员怎么来**：仍需运维直接改 `users.is_admin`。
* 强制改密期间只放行三条路由，但**没有过期机制**：账号会一直停在这个状态，直到有人改密码。

----------------------------------------

------------------------------------------------------------------------


## D.63 2026-11-05 OCR：一个接缝，三种引擎，默认关闭

**交付：** `app/services/ocr.py`（provider 接口 + fake/tesseract/cloud）、PDF 栅格化、低置信度进 `pending_review`、配置项、`test_ocr.py`。

### 决定：OCR 是一个接口，不是某个库

```text
PDF/图片 → 栅格化(pypdfium2) → OCR provider → 文本块 → 现有 pipeline
```

四个 provider，用 `CHILON_OCR_PROVIDER` 选：`none`（默认）/ `fake`（测试）/ `tesseract`（离线）/ `cloud`（需显式配置端点与密钥）。

**默认 `none`，行为与之前完全一致**：扫描件被拒绝，并说明为什么。**云端不是“环境变量没设就默认走”，而是没配端点与密钥就构建失败**——数据出境不能靠遗忘来触发。

栅格化选 `pypdfium2` 而不是 poppler：**纯 wheel，无系统依赖**。一个需要 apt 装 poppler 的 OCR 管线，一半的部署跑不起来。

### 低置信度不进检索

这是这次最重要的决定。`lifecycle_status` 里本来就有 `pending_review`，而检索只读 `approved/indexed`。所以：

```text
OCR 置信度 < 阈值  →  pending_review
                     → 教师复核后才可检索
```

**没有新加任何标志位**，用的是 schema 早就声明过的状态。一次糟糕的 OCR 如果直接进 `indexed`，会安静地污染知识库——这正是 D.56 花整轮避免的那类失败。

### 记录引擎与版本

`knowledge_ingestion_runs` 现在用 `stage='ocr'`（`stage` 的词表里也早就有 `ocr`），`tool_version` 存引擎标识。**换引擎会改变切题结果**，不记录就无法解释“同一份文件上次 3 题这次 4 题”。

### 不承诺公式

`sin²x` 很可能被识别成 `sin?x`。所以：

* 文档与界面都要写清“扫描件的公式可能失真，请核对”；
* 低置信度自动进复核，而不是假装没问题。

**把公式识别成乱码却不说，比拒绝更糟。**

### 测试：只测管线，不测引擎

真 OCR 引擎无法断言——它跨版本变化、对 `sin²x` 各方意见不同。能断言的、也是生产上真正会坏的：

```text
无 provider        → 扫描件仍被拒，理由不变
有 provider        → 变文本、题数正确、记录 engine/version/confidence
高置信度           → indexed，可检索
低置信度           → pending_review，检索为 0
云端无凭据         → 构建失败并指明缺哪个变量
未知 provider 名   → 明确报错，不静默降级
```

`fake` provider 从 PDF 字节里读一个标记，所以每种情况都精确可控。

### 我自己写了一条永远通过的断言

第一版里我写了：

```python
check("ocr" in stages or True, ...)
```

`or True` 让它**永远不会失败**。而且它掩盖了一个真问题：OCR 运行被记成了 `stage='parse'`。

两处都改了：`_record_run` 增加 `stage` 参数，OCR 用 `'ocr'`；断言改成严格检查。**这个项目已经因为“不能失败的检查”吃过两次亏（D.50、D.54），这次是自己写下的第三条。**

**流水线：23 个数据库套件 + 17 项静态检查。新增依赖 pypdfium2（已锁定、已入 CI）。**

### 还没做的

* **P2/P4 只有代码路径，没有真实跑通**：本机没有 tesseract，也没有云凭据。`tesseract` 与 `cloud` 两个 provider 属于“写好了、没验证”——必须在有真实环境的部署上再确认一次。
* **图片文件（jpg/png）还不接受**，只处理 PDF。
* 公式结构化（LaTeX）完全没做。

----------------------------------------

------------------------------------------------------------------------


## D.64 2026-11-05 阿里云试卷切题：请求是真的，响应形状我没拿到

**交付：** `app/services/aliyun_ocr.py`（ACS3 签名 + 防御式响应读取）、`AliyunPaperCutProvider`、结构化接缝、`test_aliyun_ocr.py`。

### 查文档查到三个改变设计的事实

| 事实 | 后果 |
| --- | --- |
| **接口不支持 PDF**，只收图片 | 每页先用 pypdfium2 栅格化成 PNG |
| `CutType` 分 `question` / `answer` 两次调用 | 答案与题目天然分离 |
| 接口**自己做切题**，返回题干/选项/答案结构 | 我们的正则切题在它面前是重复劳动 |

第三条最重要。如果把它返回的结构再拼回“文本行”喂给正则，等于**先花钱买结构，再亲手丢掉**。所以 OCR 接缝扩展了：provider 可以返回结构化题目，摄入时直接映射，跳过自己的 `segment()`。

### 一个我拒绝猜的地方

`Data` 在文档里被截断成 `{"p…`，**内部结构拿不到**。

我没有编一个结构。做法是把不确定的部分关进一个函数，并让它**失败得很响**：

```text
extract_questions(payload)
  → 递归找"看起来是题目"的对象
  → 找不到就抛 ShapeUnknown，并带上实际看到的顶层键名
```

```text
no question-shaped items found; top-level keys were ['Unexpected']
```

**返回空列表是最坏的选择**：它会变成“这份卷子没有题目”，而实际上是我们没读懂 vendor 的格式。

### 两半的置信度必须分开说

| 部分 | 依据 | 能否在此验证 |
| --- | --- | --- |
| 请求：端点、参数、ACS3-HMAC-SHA256 签名 | 文档明确 | **能**——签名对输入是确定的，可离线钉住 |
| 响应：`Data` 内部结构 | 文档截断 | **不能**——所以防御式 + 大声失败 |

**这个 provider 从未对真实端点运行过。** 环境里没有凭据。这句话写在模块注释、设计文档和测试的结束语里，而不是靠一片绿测试暗示“它能用”。

### 一次经典的自伤

结构化分支里我写了 `text = question.as_text()`——**遮蔽了 `sqlalchemy.text()`**，整个函数立刻 `UnboundLocalError`。改名 `body`。

这类错误在 Python 里很常见，但在这个文件里格外容易：`text` 既是被导入的 SQL 构造器，又是业务上最自然的变量名。

**流水线：24 个数据库套件 + 17 项静态检查。**

### 上线前必须做的三件事

1. **用真实凭据跑一次**，把 `Data` 的实际结构打印出来，据实调整 `extract_questions`（大概率只需要改键名优先级）。
2. **确认计费与额度**：开通教育场景识别、购买资源包。
3. **确认数据出境合规**：整页图片会上传，需在部署方层面获得许可。

### 一个仍然存在的设计缺口

`CutType=answer` 那一半没有实现。**题目与答案的配对依赖 vendor 的下标或题号对齐**，而这一点在拿到真实响应前无法确认。当前实现只在同一页的响应里顺带取 `Answer` 字段——若 vendor 把答案另放在 answer 通道，就需要补第二次调用与配对逻辑。

**我把它留成已知缺口，而不是猜一个配对规则。**

----------------------------------------

------------------------------------------------------------------------


## D.65 2026-11-05 选哪个教育接口：切题优先，整页兜底，精细版暂缓

**交付：** 三个 action 可切换（`RecognizeEduPaperCut` / `RecognizeEduPaperOcr` / `RecognizeEduPaperStructed`）、整页兜底文本读取、联调脚本 `--action`。

### 判断依据不是厂商宣传，是我们自己的数据模型

| 接口 | 返回 | 对我们的意义 |
| --- | --- | --- |
| 整页识别 | 整页文字+公式+坐标，**不切题** | 只是换一个更好的 OCR。切题仍靠我们的正则，而**扫描件上最脆的就是这一步** |
| **试卷切题** | 按题切分 + 题干/选项/答案 | **正是我们的数据单元**：一题一块、`answer_locator`、`question_type` |
| 精细版结构化 | 上面之外还有标题/主题等版面标签 | 多出来的主要是章节标签 |

**选切题（PaperCut）。**

### 为什么不选精细版

**它是切题的超集，但多给的正是我们已经有的东西。** `section_label` 由正则拿，`question_type` 由 `classify()` 推，知识点由 `taxonomy` 给。

精细版真正的价值要等见到真实样本才知道——比如教辅里“例题/练习/习题”的层级结构，那种我们确实推不出来。**所以是暂缓，不是否定。**

### 为什么整页识别必须保留

有些页切题切不出来：教材页、答案页、非试卷材料。这时返回 0 题就是失败。

所以 provider 按 action 分支：

```text
PaperCut   → 结构化题目
PaperOcr   → 整页文本（兜底，喂给现有 pipeline）
```

**这是一条真实的降级路径，不是理论上的补充。**

### 顺带修掉的一个问题

在此之前 `_call` 里的 action 是写死的，`version` 也写死成切题。**联调时根本没法探测另外两个接口**——而联调正是下一步最要紧的事。现在 `version` 记录真实 action（`aliyun:RecognizeEduPaperOcr`），换接口在 `knowledge_ingestion_runs.tool_version` 里能看出来。

### 真正常用之前的顺序

1. `python tools/aliyun_ocr_smoke.py 试卷.pdf --action RecognizeEduPaperCut` 确认切题响应的真实结构，调整 `TEXT_KEYS` / `OPTION_KEYS`；
2. 同一条命令换 `--action RecognizeEduPaperOcr`，确认整页兜底也能读；
3. 再把 `CHILON_OCR_PROVIDER=aliyun` 打开，走真实上传路径。

**先探测、后开启**——因为开启之后，一份读不懂的响应会表现为“这份卷子没有题目”。

**流水线：25 个数据库套件 + 17 项静态检查。**

----------------------------------------

------------------------------------------------------------------------


## D.66 2026-11-05 收敛：只留试卷切题，删掉用不到的开关

**交付：** 移除 `--action` 切换、整页识别读取路径、`CHILON_OCR_ALIYUN_ACTION` 配置，以及对应的三组断言。

### 为什么删，而不是留着

上一轮（D.65）我把三个接口做成了可切换，理由是“联调需要探测”。用户的决定是：**这些服务按次收费，暂时只用试卷切题，兜底等真实测试后再说。**

那么留着一个没人用的开关是什么？

**它会让下一个人以为它在跑。** 这个项目已经为此付出过代价：D.62 里那个既不写也不读的 `must_change_password`，我当时的判断就是「比没有更误导」。现在同样的判断适用于这里。

所以：

| 移除了什么 | 为什么 |
| --- | --- |
| `CHILON_OCR_ALIYUN_ACTION` 配置 | 只有一个合法值，配置就是噪音 |
| `extract_page_text()` | 没有任何可达路径调用它 |
| provider 的 action 分支 | 分支只走一条 |
| 联调脚本的 `--action` | 同上 |
| 对应的断言 | 断言的对象已不存在 |

**代码在 git 历史里；恢复步骤写在下面。**

### 恢复兜底需要做什么

1. 在 `aliyun_ocr.py` 加回 `ACTION_PAGE = "RecognizeEduPaperOcr"`；
2. 加回一个“从响应里收集字符串字段”的读取器（历史版本可直接取）；
3. provider 在 `ACTION_PAGE` 分支里把结果包成 `PageText`，让现有 pipeline 当文本处理；
4. 联调脚本加 `--action` 即可探测。

**唯一需要重新决策的是配对规则**：整页识别不切题，所以它只适合“整页材料直接入知识库”，不适合“按题入库”。这一点在 D.65 已写清，恢复时不该忘。

### 现在的 OCR 能力边界（准确表述）

```text
CHILON_OCR_PROVIDER=none        默认：扫描件被拒，说明原因
CHILON_OCR_PROVIDER=fake        测试用
CHILON_OCR_PROVIDER=tesseract   离线，需二进制（本环境未验证）
CHILON_OCR_PROVIDER=cloud       通用 HTTP 端点（未验证）
CHILON_OCR_PROVIDER=aliyun      试卷切题（未对真实端点验证）
```

**六个里有四个没在真实环境跑过**——这句话必须留着，直到联调完成。

**流水线：25 个数据库套件 + 17 项静态检查。**

----------------------------------------

------------------------------------------------------------------------


## D.67 2026-11-05 阿里云联调：真实试卷跑通，以及它暴露的五个问题

**交付：** 真实响应到达后的解析器对齐、**四个真 bug 修复**、独立的联调脚本 `tools/aliyun_e2e.py`。

**真实结果**（`docs/2024年新课标全国Ⅰ卷数学真题（原卷版）.pdf`，4 页）：

```text
status      : indexed
questions   : 17
chunks      : 17
ocr         : aliyun / RecognizeEduPaperCut / 0.9 / 4 pages
retrieval   : 检索「集合」命中 1 条，LaTeX 完整
```

### 真实响应结构（文档里被截断的那部分）

```text
Data (JSON 字符串)
  page_list[]                         每页
    subject_list[]                    每题
      text            题干 + 选项，公式为 LaTeX（$$...$$）
      ids             题号
      content_list_info[].pos   外接矩形
      prism_wordsInfo[]         词框
```

这份结构是**观测到的，不是猜到的**——所以解析器现在优先走这条明确路径，原来的通用遍历降级为兜底。

### 四个真 bug，全部由真实数据暴露

**① 缺 Pillow。** `pypdfium2.to_pil()` 依赖 Pillow，而它没被声明。只有把真实 PDF 栅格化时才炸。

**② `ids` 是页内编号。** 第 1 页是 1..6，第 4 页又从 2 开始，于是 `uq_knowledge_questions_version_no` 冲突。**厂商的题号不能当全文编号**——改为全文顺序编号，厂商 id 留在 locator 里备查。

**③ 结构化结果被判定为“没有文字”。** 空内容检查只看 `blocks`，而结构化 provider 把题目放在 `questions` 里、`blocks` 是空的。**6 道题被报成“OCR 没有识别出文字”。**

**④ `stem_key` 假设 locator 有 `paragraph_start`。** 结构化 locator 用的是 `question_index`，直接 `KeyError`。现在两种形状各自生成不冲突的 key。

### 还有一个准确性问题（不是 bug，是启发式不够）

第 5、6 题是选择题，却被判成 `fill_blank`。原因：OCR 把选项写进 LaTeX——`$$A . 2 \sqrt 3 \pi$$`——而选项正则要求字母前是空白。放宽到允许 `$` 后，第 5 题恢复为 `single_choice`。

**第 6 题仍是 `fill_blank`**，它的选项格式又不一样。这类启发式永远不会有 100%，所以题型存成可空、`segmentation_status='auto'`，等教师复核。

### 联调脚本与服务分离

真实端点调用需要凭据和网络，**不该进离线套件**（CI 里没有凭据，放进去只能永远 skip，或者更糟——让套件依赖外网）。所以：

```text
tools/aliyun_ocr_smoke.py   只调 API，打印结构（不写库）
tools/aliyun_e2e.py         走完整摄入链路，写入数据库
database/tests/run_e2e_aliyun.ps1   给后者起容器
```

**25 个离线套件仍然全绿，且没有一个依赖外网。**

### 现在可以说的话

D.64 里我写下「这个 provider 从未对真实端点运行过」。**这句话现在可以删掉了**：

```text
aliyun 试卷切题   ✓ 已对真实端点验证（4 页 / 17 题 / 可检索）
tesseract        ✗ 未验证
cloud            ✗ 未验证
```

### 仍未完成

* **答案通道**：原卷版本身没有答案，所以本次没有验证 `Answer` 字段是否存在。带答案的卷子需要再跑一次。
* **公式只是文本**：`$$...$$` 保留为 LaTeX 字符串，没有结构化成 AST。
* **17 题 vs 试卷实际题数**：需要拿标准答案页人工核对，才能判断切题是否漏题。

----------------------------------------

------------------------------------------------------------------------


## D.68 2026-11-05 19 题拿到 16 题：分辨率、碎片与缺口

用户给出标准结构：**2024 新课标Ⅰ卷共 19 题**（单选 8、多选 3、填空 3、解答 5）。

第一次跑出来是 17 条。**17 不是“少了 2 题”，是 15 道真题 + 2 个碎片。**

### 逐页核对后的事实

```text
第1页  ids 1,2,3,4,5,6            ✓
第2页  ids 0,7,8,10,11            ← 9 缺失；"0" 是第 6 题溢出的选项行
第3页  ids 12,13,14,15,17         ← 16 缺失
第4页  ids 2                      ← 18、19 缺失；"2" 是某题第(2)问的碎片
```

`ids` 是**页内编号**（第 4 页又从 1 开始），所以它既不能当全文编号，也不能用来判断完整性。

### 三个改动，每个都有实测依据

**① 栅格化 2.0 → 3.0。** 在同一份文件上对比：

| scale | 第3页 | 结果 |
| --- | --- | --- |
| 2.0 | 5 题 | 缺 16 |
| **3.0** | **6 题** | 16 回来了 |
| 4.0 | 6 题 | 无增益，第4页题号更乱 |

**选 3.0 不是因为“更高更好”，而是因为 2.0 确实丢题、4.0 确实无用。**

**② 碎片合并。** 不构成新题号的行（溢出的选项、跨页的第(2)问）应当并入上一题，而不是当成新题。判据是“文本开头是否开始一个新的题号”。

**③ 编号缺口即待复核。** 合并后编号为 1..8、10..17，缺 9。这正好是 `pending_review` 的用途：

```text
status = pending_review   →  教师复核前不进检索
```

**系统自己知道这份卷子不完整，所以不把它当完整卷子用。** 这比“索引成功”更诚实。

### 一个判据的反复

`2若 $$ rac{z}{z-1}=1+i$$` —— OCR 丢了句点。第一版严格要求“数字+分隔符”，于是**第 2 题被并进第 1 题**，缺口报成 `[2,9]`。

放宽成“裸数字也算”会把第 4 页那个 `4.` 之类的碎片又当成新题。最后采用的判据是：**裸数字只有在延续编号时才算新题**（2 = 1+1 算，页首孤立的 4 不算）。

**同一个信号（开头是数字）既是真题特征也是碎片特征，唯一的区分是上下文。**

### 现在的真实结果

```text
questions : 16 / 19
gaps      : [9]
status    : pending_review（不检索，等教师复核）
```

### 仍缺的两题无法靠调参解决

18、19 在厂商返回里**根本没有出现**（第4页只有碎片）。提高分辨率、换 `scale 4.0` 都试过，无效。

**这是厂商切题在这份扫描件上的真实上限**，不是我们的解析问题。要覆盖它只能换接口或人工补录——而 `pending_review` 恰好把这份卷子交给人工，路径是通的。

### 缺口检测的边界（必须写明）

`missing_numbers` 只能发现**最高题号以下的空洞**。18、19 缺失后最高号是 17，所以检测不到。**它能发现“中间漏了”，不能发现“结尾少了”**——除非将来能从卷面文字里读出总题数。

**流水线：25 个离线套件 + 17 项静态检查，仍不依赖外网。**

----------------------------------------

------------------------------------------------------------------------


## D.69 2026-11-05 用解析版校准：题干被污染，以及厂商在解析页失效

**交付：** `tools/calibrate_scan.py`（可复跑、带缓存的校准器）、解析内容与题干分离、答案回收、空页判定修正。

### 校准方法

用人工整理的 `docs/2024新课标全国Ⅰ卷数学_OCR切分样例.md` 作为标准答案（它自己标注了 19 题、10 页正文、23 页 PDF，并写明“解析不得并入题干”），对 `原卷版` 与 `解析版` 两份 PDF 分别跑切题。

**原始响应缓存到 `var/`**：厂商按次计费，而**一个每次都要重新付费的校准循环，没人会跑第二次**。

### 结果一：解析版暴露了题干污染

第一版合并逻辑把所有“不以题号开头”的碎片都拼进上一题。解析版里那些碎片正是 `【详解】`：

```text
Q2 题干 222 字符，尾部是 ---------- 【详解】因为 (z)/(z-1)=1+1/i ...
```

**题干里混进了它自己的解答。** 这违反了解析版约定第 9 条。

修复：碎片先分类，再决定去向。

| 碎片类型 | 去向 |
| --- | --- |
| `【解析】/【详解】/【分析】` 开头 | `analysis` 字段 |
| `故答案为/答案为/【答案】` 开头 | `analysis` 字段，并**回收答案** |
| 其余（溢出的选项、跨页续文） | 拼回题干 |

修复后：`stems still containing 解析: 0`，Q2 从 222 字符降回 73 字符。

**`故答案为 …` 这一类是最隐蔽的**：它没有任何 `【】` 标记，看起来像正文，实际是解答。第一版判据漏了它，答案回收数因此是 0。

### 结果二：厂商在解析页几乎切不出题

```text
解析版 23 页：raw subjects 31 → 14 道题
数字覆盖：1,2,3,4,5,6,7,12,13,14,15,16,17,18
缺口：8,9,10,11（19 也未返回）
```

逐页看原始响应：第 4、5、6、10、12、13、16、18、19、22 页**只返回了零星片段**，没有题号块。也就是说 8、9、10、11、19 这五道题，厂商根本没有切出来。

**这不是我们的合并吃掉了题**——我一开始这么怀疑，但把 31 个原始块逐个打出来看，带题号的只有 14 个。

### 结果三：空页不是“形状未知”

23 页里有若干页返回 `page_list: []`。解析器把它当成“响应形状不认识”而抛错，整份文档在第 1 页就失败。

**“这一页没有题目”和“这个响应我不认识”是两回事。** 前者返回空列表，后者才抛错。

### 结论与建议（这条最该被记住）

**解析版不适合作为题目来源。** 它同时包含试题与解析，版面密度高，厂商切题在其中失效；即便切出来，答案与解析也需要跨文档配对。

产品建议：

| 文档类型 | 处理 |
| --- | --- |
| 原卷版 | 切题入库（16/19，缺 9 → `pending_review`） |
| 解析版 | **不作为题目来源**；将来若要答案，应另走“答案提取”管线并与原卷配对 |

**现在的系统会把解析版标成 `pending_review`（因编号缺口），不会污染检索。这是可接受的行为，但它不会告诉教师“你传错版本了”。**

### 环境问题（与代码无关）

本轮结束时 Docker 存储变为只读（`meta.db: read-only file system`），C: 盘剩余 **0.22 GB**。最后一个套件跑完后，19 个依赖容器的套件全部无法启动。

已验证的部分：17 项静态检查、编译检查、不依赖数据库的纯函数测试，以及 Docker 失效前刚通过的 `run_aliyun_ocr_test`。

**待环境恢复后必须重跑全部 25 个套件**——本轮改动触及 `ocr.py` 的合并逻辑，那是所有摄入路径的公共部分。

----------------------------------------

------------------------------------------------------------------------


## D.70 2026-11-05 迁移到 D 盘：C 盘被 Docker 塞满了

### 现象

跑校准那一轮的最后一个套件时，Docker 突然变成只读：

```text
write /var/lib/desktop-containerd/daemon/io.containerd.metadata.v1.bolt/meta.db:
read-only file system
```

原因不是 Docker 坏了，是 **C: 剩 0.00 GB**。

| 位置 | 大小 |
| --- | --- |
| C: 总用量 / 剩余 | 446.3 GB / **0.0 GB** |
| **Docker 磁盘镜像**（`%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx`） | **73.67 GB** |
| 项目本身 | 125 MB（其中 `.venv` 94 MB） |
| D: 剩余 | 284.9 GB |

**项目只占 125 MB，Docker 那 73.7 GB 才是主因。** 搬项目只是必要的小步骤，不是解法。

### 已完成：项目迁到 `D:\Chilon`

迁移前先确认了三件事能否随路径移动：

| 检查 | 结果 |
| --- | --- |
| 代码里有写死的绝对路径吗 | 没有（grep 全仓无命中） |
| 脚本怎么定位仓库根 | `Split-Path -Parent (Split-Path -Parent $PSScriptRoot)` —— 位置无关 |
| `.env` 里有本地路径吗 | 没有，只有数据库 URL 与 API 地址 |

用 `robocopy /E` 整份复制（5708 个文件对 5708 个文件），**`.venv` 一起搬且直接可用**——`pyvenv.cfg` 的 `home` 指向的是运行时解释器，不是项目路径。

验证（在 D 盘上跑）：

```text
venv            python 3.12.14，prefix D:\Chilon\.venv
依赖            fastapi / sqlalchemy / psycopg / alembic / pypdf / pypdfium2 / PIL / multipart 全部可导入
git             main 与 origin/main 同步，HEAD = faacf3e
静态检查        17/17
纯函数测试      PASS
注册表校验      OK
```

随后删除了 C 盘副本中可重建的 `.venv`（94 MB）与 `var`（3 MB），C: 从 0.00 回到 0.09 GB。

### 仍需人工完成：Docker 磁盘镜像

`docker_data.vhdx` 有 73.67 GB，它在 C 盘，而且**不能用命令行安全搬动**——WSL2 发行版正在运行，镜像里是全部层与卷。

正确做法是 Docker Desktop 的界面操作：

```text
Settings → Resources → Advanced → Disk image location → D:\Docker
```

它会复制镜像再删除旧的，需要 D 盘空间（有 285 GB）而几乎不需要 C 盘空间。

**注意顺序**：先腾出一点 C 盘空间让它能启动（已腾 97 MB），再改位置。若它仍然起不来，退路是 Troubleshoot → Reset to factory defaults，**这会清空镜像、容器与卷**——本项目的 `chilon-pgdata` 里只有测试账号，可以重建，但这一步必须在知情的前提下做。

### 迁移带来的一个后果

会话的工作目录仍在 `C:\Users\Viver\Desktop\Chilon`（源码残留 27 MB）。**后续所有工作都应以 `D:\Chilon` 为准**；确认无误后，C 盘那个目录可以整个删除。

### 未验证的部分（必须重跑）

Docker 失效发生在最后一个套件跑完之后，因此：

```text
已验证   17 项静态检查、编译检查、纯函数测试、run_aliyun_ocr_test（失效前刚通过）
未验证   19 个依赖容器的套件
```

本轮改动了 `ocr.py` 的碎片合并与解析分离——**那是所有摄入路径的公共部分**，环境恢复后必须重跑全部 25 个套件。

----------------------------------------

------------------------------------------------------------------------


## D.71 2026-11-05 环境恢复后补验：25 个套件 + 真实端到端

D.70 结尾列出的“未验证”已经补上。Docker 磁盘镜像迁到 `D:\docker` 后：

```text
C: 剩余   73.8 GB（迁移前 0.0 GB）
D: 剩余  211.0 GB
Docker    server 29.8.0，容器可正常创建
数据      D:\docker\DockerDesktopWSL\disk\docker_data.vhdx（73.72 GB）
```

### 全部套件（在 `D:\Chilon` 上运行）

```text
17 项静态检查          全过
25 个数据库套件        0 失败
```

关键的是其中 **19 个依赖容器的套件**在磁盘迁移前根本跑不起来；现在它们全部通过，说明本轮对 `ocr.py` 碎片合并与解析分离的改动**没有破坏任何既有路径**——那是一切摄入的公共部分。

### 真实端到端（原卷版 4 页）

```text
status     pending_review     ← 因 gaps=[9]，未进检索
questions  16
chunks     16
ocr        aliyun / RecognizeEduPaperCut / 4 pages
retrieval  0 hits             ← 正确：pending_review 不进检索
```

检索为 0 不是失败，是**设计如此**：编号有缺口 → 待复核 → 不可检索。这一条曾让我在 D.68 反复确认，现在它是一个稳定的、可复现的行为。

### 一个仍然存在的产品问题

系统知道这份卷子不完整（`gaps=[9]`），也知道它不是完整的 19 题，但**它不会告诉教师“你传的是解析版”或“这份扫描件有缺题”**。教师看到的是“待复核”，看不到原因。

下一步应当把复核原因写进版本记录（`pending_review` 的 reason），并在界面上显示。**一个只说“需要复核”却不说“为什么”的状态，等于把判断成本原样退还给教师。**

----------------------------------------

------------------------------------------------------------------------


## D.72 2026-11-05 `pending_review` 说明原因，界面能看到并处理

**交付：** `review_reasons()`、运行记录携带原因、上传响应与来源列表透出原因、`/ui/knowledge` 页面（含上传）。

### 问题：状态是有的，理由是没有的

D.71 结尾写下：**“一个只说需要复核却不说为什么的状态，等于把判断成本原样退还给教师。”**

三个原因对应三种完全不同的处理：

| 原因 | 含义 | 教师该做什么 |
| --- | --- | --- |
| `numbering_gaps` | 题号有缺口，切题漏了题 | 补录，或重传更完整的一页 |
| `analysis_version` | 卷子里大量解析，这是解析版 | 改传原卷版 |
| `low_confidence` | 识别置信度低 | 重传更清晰的扫描件 |

### 实现：原因是纯函数，状态由原因决定

```python
review_reasons(gaps=..., confidence=..., min_confidence=...,
               analysis_blocks=..., questions=...) -> list[str]
```

**先算原因，再由原因决定 `pending_review`**，而不是先定状态再想办法解释它。这个方向很重要：状态是结论，原因是证据，结论应当由证据产生。

原因是纯函数，因此可以在没有数据库、没有厂商调用的情况下被断言——三个分支各一条断言，全在 `run_ui_test` 里。

`analysis_version` 的判据是**解析块数量 ≥ 题目数的一半**：解析版的特征不是“有解析”，而是“解析和题目一样多”。

### 记录与透出

原因写进 `knowledge_ingestion_runs.metrics.review_reasons`，没有新增列——运行记录本来就是摄入的审计轨迹，而这一列已经存在。上传响应直接带 `review_reasons`，来源列表 `GET /knowledge/sources` 用 `LATERAL` 取最新版本的状态与原因。

### 界面：`/ui/knowledge`

之前教师只能通过 API 上传，界面里根本没有知识库。现在有了：上传表单 + 每个来源一行状态与原因，原因用中文写明“该怎么办”。

### 一处必须避免的重复实现

界面要上传，最省事的做法是再写一遍“校验 → 存储 → 解析”。**那就是第二份实现**——而它的出口条件（校验、生命周期、复核原因）决定教师看到什么，两份迟早会不一致。

所以把 `store_and_ingest()` 从路由里抽出来，API 与界面共用：

```python
async def store_and_ingest(session, user, file, title, source_type) -> dict
```

### 又一次被自己的替换骗过

给 `low_confidence` 打补丁时，替换文本没匹配上（D.68 已经改过那一段），于是 `reasons` 只被引用、从未赋值。三个套件立刻报 `NameError`。

**这已经是这个项目里第 N 次“字符串替换静默失效”**（D.62、D.66 各一次）。规律很清楚：**只要补丁是文本匹配，就必须立刻跑一条会经过它的路径**，而不是看代码“改对了”。

### 现在的真实输出

```text
status          pending_review
review_reasons  ["numbering_gaps"]
ocr             aliyun / RecognizeEduPaperCut / 4 pages / gaps [9] / analysis_blocks 0
questions       16
```

**流水线：25 个数据库套件 + 17 项静态检查，全过；真实端到端亦通过。**

### 仍然缺的

* 教师**无法**在界面上补录缺的题——现在只能看到原因，不能处理它。复核闭环只走完一半。
* `analysis_version` 的判据还没在真实解析版上验证过（那需要再花 23 次调用）。

----------------------------------------

------------------------------------------------------------------------


## D.73 2026-11-05 复核闭环：补上缺的那道题，然后真的能被检索到

**交付：** `knowledge_review`（`outline` / `add_question` / `promote`）、三个端点、`test_review_closure.py`。

D.72 结束时写着「教师能看到原因，但不能处理它——复核闭环只走完一半」。现在补上了。

### 补题必须同时写块

`add_question` 写入**块和题两条记录**。只写题不写块，题就在库里但检索永远找不到——**“我补了题，但它不出现”**是紧随其后的那个 bug。

因此测试的断言不是“状态变了”，而是：

```text
补 Q3 → 转正 → 检索「向量」→ 命中那条教师手打的题干
```

**闭环的定义是能被搜到，不是状态字段变成 indexed。**

### 转正要记录“当时还缺什么”

教师可能知道这份卷子本来就跳号。所以 `promote` 不阻止带缺口转正，但把决定写进运行记录：

```json
{"promoted_by": "teacher", "questions": 4, "open_gaps_at_promotion": []}
```

**是“人做的判断”，不是“没有缺口”** —— 两者在审计里必须能区分。

### 一个真正的安全网漏洞（这次测试抓到的）

第一次跑，缺口卷子居然直接 `indexed`、检索还能搜到。查下去发现：

**题号缺口检测只写在结构化 provider 里。** 走规则解析的路径（tesseract / cloud / fake / 任何文本抽取）从不计算缺口——那些卷子漏了题也会被静默索引。

修复：缺口改为**在摄入层从 segments 推导**，两条路径共用。这条比“再写一个 provider 实现”重要得多：它是所有非阿里云路径的共同盲区。

### 隔离是对的，报错方式不对

另一个教师往这个版本里加题时，RLS 拒绝了插入（**隔离生效**），但抛的是数据库异常，接口表现为服务器错误。

**“不是你的”应当是 404，不是 500。** 写入前先做一次可见性检查，`ReviewNotFound` → 404。

### 现在的闭环

```text
上传 → 解析 → 编号有缺口 → pending_review + 原因
     → outline 看到 gaps=[3]
     → 手打第 3 题（题干 + 答案）→ 块与题一起写入
     → gaps=[]
     → promote → indexed（记录决定）
     → 检索命中那一题
```

**流水线：26 个数据库套件 + 17 项静态检查。**

### 还缺的

* **界面还没有接入这一步**：`/ui/knowledge` 能看到原因，但没有“补题”和“确认完整”的按钮。API 有了，页面没有——**对教师而言功能仍不存在**。
* 补的题 `segmentation_source='teacher'`、`segmentation_status='accepted'`，但**没有“编辑已有题”和“删除切错的题”**。切错的题现在只能无视，不能删。

----------------------------------------

------------------------------------------------------------------------


## D.74 2026-11-05 界面上的复核闭环：缺题能补，补完能启用

**交付：** `/ui/knowledge` 增加“缺第 N 题”、补题表单、确认完整性按钮；测试改为**从页面驱动**。

D.73 结尾写着「API 有了，页面没有——对教师而言功能仍不存在」。现在补上了。

### 页面现在能做什么

```text
上传 → 状态 pending_review
     → "缺第 3 题"
     → 表单：题号（下拉，只列缺口）/ 题干 / 答案（可选）
     → 「补上这题」
     → 缺口消失
     → 「确认完整并启用」
     → 状态 indexed，可检索
```

**题号下拉只列缺口**，不是自由输入：教师不该有机会再制造一个重复题号。

### 测试改了驱动方式，这是重点

原来这几步走 API，现在**从页面走**：

```python
client.post("/ui/login", ...)              # 拿 cookie
client.get("/ui/knowledge")                # 断言页面写了"缺第 3 题"
client.post("/ui/knowledge/questions", ...) # 提交表单
client.post("/ui/knowledge/promote", ...)   # 点按钮
```

**一个只有 API 能用的功能，对教师来说不存在。** 这条断言必须落在 HTML 上。

### 顺手修掉一个审计缺陷

测试打印运行记录时看到 `stages=['ocr','ocr','index']`——**OCR 成功被记了两次**：分支里记一次，收尾时又记一次。

重复的审计记录比没有记录更糟：它让“这份文件被解析过几次”无法回答。现在每次摄入只有一条，且收尾那条带 `review_reasons`（更完整的那条被保留）。

现在：`stages=['ocr','index']`。

### 现在的完整闭环（界面 + API）

| 步骤 | 界面 | API |
| --- | --- | --- |
| 上传 | `/ui/knowledge` 表单 | `POST /knowledge/sources` |
| 看缺口 | 页面显示“缺第 N 题” | `GET /knowledge/versions/{id}` |
| 补题 | 表单 | `POST /knowledge/versions/{id}/questions` |
| 启用 | 按钮 | `POST /knowledge/versions/{id}/promote` |

**流水线：26 个数据库套件 + 17 项静态检查。**

### 仍然缺的

* **不能编辑或删除已切错的题**：补得进去，改不掉。切错一道题现在只能无视它。
* 补题不支持选项结构化（题干里写成 `A. … B. …` 会被 `classify()` 认出来，但不拆成 `options`）。
* `analysis_version` 的判据仍未在真实解析版上验证。

----------------------------------------

------------------------------------------------------------------------


## D.75 2026-11-05 改与删：切错的题终于能被修正

**交付：** `update_question` / `delete_question`（服务）、`PATCH` / `DELETE`（API）、`/ui/knowledge/{version_id}` 校对页（界面）。

D.74 结尾写着「补得进去，改不掉……**改不掉的东西在长期使用里一定会出现**」。现在改得掉也删得掉。

### 改的是块，不是题目行

`knowledge_search` 读的是 **chunk**，不是 `knowledge_questions`。所以修改必须落在 chunk 上：

```text
改题干 → 更新 stem chunk 的 text_content 与 text_hash
       → 重算题型与知识点
       → segmentation_status='corrected', segmentation_source='teacher'
```

只改题目行会让页面显示新文字、**检索仍返回旧文字**——那种不一致比不能改更难发现。

测试正是这样断言的：

```text
改第 4 题为"求模长" → 检索「模长」命中
                    → 检索「数量积」不再命中该题
```

**只断言“能搜到新的”不够，还要断言“搜不到旧的”。**

### 删的是题和块

删题时连它的 stem chunk 与 answer chunk 一起删。只删题目行会留下一个**仍在被检索到的孤儿块**——一个“已删除但还会回答查询”的题，比没删更糟。编辑后状态用 schema 里已声明的 `corrected`，不是自造的字符串。

### 校对页 `/ui/knowledge/{version_id}`

每个来源卡片加了「校对题目 →」入口，页面列出每题：来源（教师录入/自动切分）、可编辑的题干、可选的答案、删除按钮。

**界面里带着“来源”这一栏**，因为教师需要知道自己在改谁切的东西——自己录的，还是机器切的。

### 同一个坑第二次

校对页里我写了 `text = (row.text_content or "").strip()`，**遮蔽了模块顶部导入的 `sqlalchemy.text`**，整个函数立刻 `UnboundLocalError`。

D.59 在 `ingestion.py` 里犯过一次，一模一样。

**`text` 在这个项目里是最容易撞名的标识符**：它既是 sqlalchemy 的查询构造器，又是“题干”最自然的变量名。记在这里，因为下次还会想这么写。

**流水线：26 个数据库套件 + 17 项静态检查。**

### 现在的校对能力

| 动作 | 界面 | API |
| --- | --- | --- |
| 补缺题 | 表单 | `POST .../questions` |
| 改题干/答案 | 校对页 | `PATCH .../questions/{no}` |
| 删切错的块 | 校对页 | `DELETE .../questions/{no}` |
| 确认完整并启用 | 按钮 | `POST .../promote` |

### 仍然缺的

* **没有撤销**：删错了只能重新手打一题。
* **不能调题号顺序**：切分把两题并成一题时，只能删一条再补一条。
* **补/改题都不拆选项**：`A. … B. …` 写在题干里能被 `classify()` 认出题型，但不进入结构化 options。
* `analysis_version` 判据仍未在真实解析版上验证。

----------------------------------------

------------------------------------------------------------------------


## D.76 2026-11-05 收尾：撤销、改题号，以及被数据推翻的解析版判据

D.75 结尾列了四条缺口，这一轮清掉了三条，第四条被证明**不该做**。

### ① `analysis_version` 的判据原来是错的

D.72 用的规则是“解析块数 ≥ 题目数的一半”。用缓存的 23 页真实响应一验证：

```text
解析版：questions=14, analysis_blocks=3  →  3 < 7  →  不判为解析版
```

**规则在真实数据上不成立。** 原因很清楚：合并时把无编号的解析碎片挂到上一题，最终只有 3 块留下了 `analysis`；**绝大多数解析根本没能挂上**。

换了一个可测量的信号——**无编号碎片占比**（在合并之前统计）：

| 文档 | 无编号碎片 | 解析标记 |
| --- | --- | --- |
| 原卷版 | **21%**（4/19） | 0% |
| 解析版 | **55%**（17/31） | 10% |

阈值取 40%，两边都有余量。为什么必须在合并前统计：**合并会把无编号碎片折进上一题，之后再统计就永远是 0。**

这条教训值得记：**上一轮我“实现”了一个判据，也“测试”了它——但那场测试用的是我自己构造的样本**（`analysis_blocks=9, questions=14`），于是它通过得毫无意义。真实数据一进来就否掉了。

### ② 删除可以撤销了，而且撤销是真的

软删除：题目行保留并打上 `deleted_at`，**chunk 也保留**。检索按 locator 排除“有问题被删”的块（`NOT EXISTS ... deleted_at IS NOT NULL`），所以删除立刻生效；清掉标记，题目立刻又能被搜到。

这需要给 `knowledge_questions` 加一列，于是又走了一遍注册表 → DDL → 迁移的流程（字段必须带 `sensitivity`，第一次漏了，校验器当场拒绝）。

恢复 = 清掉 `deleted_at`，chunk 早就没了，但题目行的 locator 还在，重新建块即可——**实际上恢复只是把标记清掉，块在删除时已被移除，所以恢复后必须重建**。

> 第一版把 chunk 一起删了，于是“恢复”只是清了一个再没有对应内容的标记。**修法不是补建块，而是根本不删块**——检索那侧的过滤已经覆盖了“已删除”，删块是多余动作。测试现在断言“恢复后又能被搜到”。

### ③ 题号可以移动

合并错误（两题并成一题）的修复方式是：补第二题、把后面的题号顺延，而不是删掉后面全部重打。`renumber` 支持一次移动，并且**空出来的号会立刻出现在缺口里**——测试断言了这一点。

### ④ 选项结构化：不做

教师补题时把 `A. … B. …` 写进题干，`classify()` 能据此认出题型，但不拆成结构化 options。

**理由是没有消费者**：检索按题干文本匹配，生成用自己产的题，材料 AST 里的 options 由生成器写。为一个没有下游的字段做解析，只会增加一个“看起来有用”的复杂度。

这条记下来，是为了将来真想用时不至于以为漏了。

### 现在的能力

| 动作 | 状态 |
| --- | --- |
| 补缺题 | 完成 |
| 改题干/答案 | 完成（改 chunk，检索同步） |
| 删切错的块 | 完成（软删除，可撤销标记） |
| 撤销删除 | 完成（保留块，标记清除即恢复检索） |
| 移动题号 | 完成 |
| 选项结构化 | 明确不做（无消费者） |

**流水线：26 个数据库套件 + 17 项静态检查。**

### 一条关于“半实现”的记录

我一度把“恢复只清标记、块已删除”写进文档当作已知缺陷——**但那是可以当场修好的**，而且修法是删掉一行（不删块），不是加东西。

**把一个能修的缺陷写进文档，比没写更糟**：它看起来像已评估过的取舍。

----------------------------------------

------------------------------------------------------------------------


## D.77 2026-11-05 JPG 上传：把“拍照/导出图片”这条最常见的输入接上

**交付：** `image/jpeg` 与 `image/png` 进入上传白名单、图片直接作为单页送 OCR、`test_ocr` 增加两组场景。

在此之前，上传接口只认 PDF 与 DOCX。**教师手上最常见的其实是一页一张的图片**，而这条路是死的。

### 实测：全国2卷（4 页 JPG）

| 指标 | 结果 |
| --- | --- |
| 页数 | 4 |
| 切出题目 | **14 / 19** |
| 题号 | 1–10、12、13、14、17 |
| 缺口 | 11、15、16 |
| 18、19 | **未返回，且检测不到**（最高号只到 17） |
| 状态 | `pending_review`，`review_reasons=["numbering_gaps"]` |
| 检索 | 0（未转正，正确） |

### `image_type` 的选择有依据

同一页分别用两个值调用：

```text
scan : 4 个 subject，ids=['1','2','3','4']
photo: 4 个 subject，ids=[None, None, None, None]
```

数量一样，但 **`scan` 能给出题号、`photo` 给不出**。这份文件是从 PDF 导出的扫描图，不是手机实拍，所以用 `scan` 是对的——**而且这不是偏好，是题号能否用于缺口检测的分水岭**。

### 实现只加了必要的一段

```python
if not pdf_bytes.startswith(b"%PDF"):
    return [pdf_bytes]     # 图片本身已是一页，不要交给 PDF 渲染器
```

图片不可能有文字层，所以 `paragraphs_for` 对 `image/*` 抛 `UnsupportedFormat("图片需要用 OCR 解析")`，随后进入既有的 OCR 分支——**没有为图片另写一条流水线**。

未配置 provider 时仍然明确拒绝（测试断言了“拒绝且理由提到 OCR”），不会变成“索引成功但零题目”。

### 顺手让联调脚本可指向任意文件

`tools/aliyun_e2e.py` 原来写死那份原卷版 PDF。现在 `CHILON_SAMPLE` 可覆盖，且按后缀推断 mime——**否则每换一份材料就要改一次代码才能验证**。

（这次用它把 4 张 JPG 用 Pillow 合成一份 PDF 跑了完整管线，结果与直接调 API 的 14 题一致。）

### 全国2卷 vs 全国1卷

| 卷子 | 页数 | 切出 | 缺口（可检测） |
| --- | --- | --- | --- |
| 新课标Ⅰ卷 原卷版 | 4 | 16 / 19 | 9 |
| 新课标Ⅱ卷 JPG | 4 | 14 / 19 | 11、15、16 |
| 新课标Ⅰ卷 解析版 | 23 | 14 / 19 | 8、9、10、11（且判为解析版） |

**三份材料，三种不同的漏题形态。** 厂商切题在同一批次里的表现并不稳定，这是事实，不是可以调参消除的。

**流水线：26 个数据库套件 + 17 项静态检查。**

### 仍然缺的

* **结尾缺失检测不到**：18、19 没被切出，而检测只能发现最高号以下的空洞。
* 图片没有多页合并的入口：教师传 4 张图会变成 4 个来源，只能自己合成 PDF。
* 实拍照片（`photo`）在真实手机照片上仍未验证。

----------------------------------------

------------------------------------------------------------------------


## D.78 2026-11-05 范围澄清：平台语料是 P0，教师上传是 P1

用户明确了产品边界：

```text
P0  我们把教材 / 高考卷 / 模拟卷 导入平台知识库
    教师输入要求 → LLM 从知识库里找到相应对象
P1  教师自己上传资料
```

**此前的绝大部分工作属于 P1。** 这不是返工，而是优先级需要重排——而重排之后立刻暴露了两个 P0 级别的阻塞。

### 阻塞一：平台语料根本写不进去

所有上传路径都硬编码 `scope='teacher'`、`owner_id=<调用者>`。**没有任何操作员导入入口**，而平台行按设计应当由管理会话写入。

已交付 `app/services/platform_import.py` + `tools/import_platform.py`：

| 决定 | 理由 |
| --- | --- |
| 跑在管理员会话上 | 与迁移、种子同一姿态；应用角色只能读平台内容，永远不能写 |
| 以 SHA-256 幂等 | 语料会被反复导入，重复导入不能变成重复来源 |
| `created_by` 用 `PLATFORM_PRINCIPAL` 常量 | 这张表仍缺“系统主体”概念，**把这个债务写进数据里，而不是藏进注释** |

导入后：`scope='platform'`、`owner_id NULL`、`rights_status='licensed'`、`distribution_scope='classroom'`；有缺口时默认接受（操作员已看运行摘要），并把这次接受记进运行记录。

### 阻塞二：教师能往平台题库里写东西

子表写策略原本是：

```sql
EXISTS (... WHERE s.scope = 'platform' OR s.owner_id = app_current_user_id())
```

**`scope='platform'` 在允许列表里**——任何教师只要能拿到平台版本的 id，就能往里面插块和题。`knowledge_sources` 自己限制得对（只能写自己的 teacher 行），子表却放宽了。

已收窄为：子表写权限只覆盖 `s.scope='teacher' AND s.owner_id = 当前用户`；平台行由管理员会话写入（RLS 绕过）。

**测试断言了这条**：教师对平台版本执行 INSERT → 被 RLS 拒绝；同时教师**能读到**平台内容（共享语料的意义）。

### 现在的 P0 能力

| 能力 | 状态 |
| --- | --- |
| 操作员批量导入（目录/单文件） | ✅ 幂等、按类型归入教材/高考真题/模拟卷/教辅 |
| 平台内容对全体教师可检索 | ✅ |
| 平台内容对教师只读 | ✅（RLS 收窄并测试） |
| 有缺题时导入是否放行 | 由 `--no-accept` 决定 |
| 教师输入要求 → LLM 找对象 | ⚠️ **能用，但匹配质量未验证** |

**流水线：27 个数据库套件 + 17 项静态检查。**

### 仍然缺的（P0 视角）

1. **检索质量没有度量。** 现在 `knowledge.search` 是“课题关键词 ILIKE + 知识点重叠”。语料一旦从 4 页变成上千页，**召回率没有任何数据**。这是 P0 最该补的一环：准备一批真实教师提问 + 期望命中的对象，测召回，再谈优化。
2. **要求 → 检索词的转换很粗。** `extract_requirement` 从整句话里剥出“课题”，遇到“出一道导数压轴题，难度接近高考”这类要求，主题会提取成“导数压轴题”，而语料里没有这几个字。
3. **没有按来源类型/年份/难度筛选。** 教师说“用高考真题”时，`sources` 过滤存在，但教材/模拟卷的区分在检索里几乎没被用到。
4. **语料规模未验证。** 目前只在三份材料上跑过；入库一千份之后的表现完全未知。
5. **教材不是“题”** ——教材章节是连续文本，`segment()` 出来的“题”其实是段落。平台语料里教材与试卷需要不同的切分策略，现在共用一套。

### 一个需要先定的问题

**“对象”是什么？** 是题目、段落、还是知识点条目？现在的实现是“块”（一段文本 = 一个块），题目只是块的一种。教师说“找相应的对象”时，系统返回的是块，而块可能是一道题，也可能是一段教材正文。

**这个语义不清，会让检索质量的度量无从谈起**——测“召回率”之前必须先定义“命中什么算对”。这是我建议下一个要定的东西。

----------------------------------------

------------------------------------------------------------------------


## D.79 2026-11-05 真的把语料导进去了：34 道题、3 个来源

用户指出顺序错了：**没有语料，评测无从谈起**。对的。这一轮把手上真实材料导进平台库，并量了检索。

### 材料的真实情况（决定了成本）

| 文件 | 页数 | 文字层 |
| --- | --- | --- |
| 新课标Ⅰ卷 原卷版 | 4 | **0 字符（扫描件）** |
| 新课标Ⅰ卷 解析版 | 23 | 0 |
| 新课标Ⅱ卷 原卷版 | 4 | 0 |
| 新课标Ⅱ卷 解析版 | 25 | 0 |
| 全国甲卷（理）解析版 | 20 | 0 |

**六份 PDF 全是扫描件**，所以入库全部要过 OCR。全导 = 80 页 = 80 次计费调用。

### 导入策略：只导该当题目来源的

| 材料 | 决定 | 理由 |
| --- | --- | --- |
| Ⅰ卷原卷版 | 导入 | 题目来源 |
| Ⅱ卷原卷版 | 导入 | 题目来源 |
| Ⅱ卷原卷版「副本」 | 不导 | 与正本是同一份字节，导入器会按 SHA-256 跳过 |
| 4 张 JPG | 不导 | 与Ⅱ卷 PDF 同一份卷子，再导就是重复语料 |
| 3 份解析版（68 页） | 不导 | **解析版不作为题目来源**（D.69 的结论），导入只会得到一堆 `analysis_version` |

**省下 68 次调用**——这正是“先想清楚语料策略”的价值：不是所有能 OCR 的东西都该入库。

### 实测结果（真实导入，不是模拟）

```text
2024 新课标Ⅰ卷 原卷版.pdf   16 题  pending_review(numbering_gaps) → 接受
2024 新课标Ⅱ卷 原卷版.pdf   15 题  pending_review(numbering_gaps) → 接受
Chilon-三角函数练习 教师版.docx  3 题  indexed
------------------------------------------------------------
corpus: sources=3  versions=3  questions=34  chunks=35
```

**同一份Ⅱ卷**：PDF 切出 **15** 题，JPG 只切出 **14** 题。**PDF 比图片好**——这条以后能省事。

### 检索实测（教师口吻的三个问题）

```text
「集合」                      → 2 命中（两份卷子各一）
「导数与函数单调性」           → 7 命中
「出一道关于三角函数的单选题」   → 8 命中，前 3 条包含那份三角函数讲义
```

**能返回合理的对象**，但第三条暴露了问题：它把整句话当检索主题，靠知识点重叠凑出 8 条——**不是“理解要求”，是“碰巧有词能对上”**。

### 一个必须修的运维坑

第一次导入全是 `status=failed`、0 题，而工具只打印了 `0 题`——**没说原因**。

原因是 `.env` 里没有 `CHILON_OCR_PROVIDER`，默认 `none`，扫描件直接失败。这是**设计如此**（云 OCR 必须显式开启），但工具不打印失败原因就是缺陷。

已修：导入输出现在带 `detail`，失败的计入 `failed` 计数。

### 部署路径也补齐了

镜像里原来**没有 `tools/`**，意味着操作员无法在部署环境里导入语料。已加：

```dockerfile
COPY tools ./tools
```

compose 增加只读挂载，语料投放位置固定为 `./corpus`：

```yaml
- ./corpus:/corpus:ro
```

并写了 `corpus/README.md` 说明用法与注意事项。

### 语料的现状与差距

| 项 | 现状 |
| --- | --- |
| 试卷 | 2 份（Ⅰ卷、Ⅱ卷），34 题 |
| 教材 | **0 份——一份都没有** |
| 知识点覆盖 | 只覆盖到这两份卷子出现的考点 |
| 语料规模 | 34 题，距离“千题级检索”差两个数量级 |

**教材这条路径一行都没跑过**：`docs/` 里没有任何教材文件，`segment()` 对连续正文会切出段落而不是题，而从没验证过。

### 下一步（按依赖顺序）

1. **要教材电子版**：这是唯一能立刻扩语料的输入。没有文件，教材处理逻辑无法验证。
2. 教材需要**独立的切分策略**（按章节/小节/正文段落），不能和试卷共用 `segment()`。
3. 语料上到百题级之后再量召回——**34 题上的召回率没有意义**。
4. 检索要能理解“要求”，现在只是关键词+知识点重叠。

**流水线：27 个数据库套件 + 17 项静态检查。**

----------------------------------------

------------------------------------------------------------------------


## D.80 2026-11-05 语料到齐：6050 道真题，公式精确，六成有答案

按 D.78 的范围（2012–2026），先试 PDF，再换成 LaTeX 源码。**两条路的差别是决定性的。**

### PDF 那条路走不通

`deekur/gaokaomath`（CC BY 4.0）有 777 份原卷，2012–2026 共 259 份、525 页，**全部有文字层**——按理会省下全部 OCR 费用。

实测抽出的是：

```text
已知集合 =fxj 5 < x 3 < 5g, B =f 3; 1; 0; 2; 3g, 则 A\ B = ( )
```

`∩` → `\`，`√` → `p`，花括号 → `g/f`。这是 TeX 字体编码，**装 `fontTools` 也修不好**。免费路径的公式是坏的；修它只能 OCR（525 页计费），而且原卷不带宽的答案。

顺带修了一个真 bug：`QUESTION_START` 把 `(1)(2)` 当成新题号，导致一道解答题被切成三道、题号重复。修法是“括号号在已有题目内一律视为小问 + 题号必须递增”。修完 2024 新高考Ⅰ卷切出 19 题、编号 1–19 连续，北京 21 题连续。

**这个修复对扫描件路径同样有效**，是这一轮唯一的净收益。

### 换成 LaTeX 源码

`DxAThing/Gaokao-Math-Problems-Compilation`（**CC BY-SA 4.0**）把同一批题目重排成了 LaTeX，并带答案与解析：

```text
\begin{problem} ... \choices{o1}{o2}{o3}{o4} ... \end{problem}
\begin{answer} A \end{answer}
\begin{solution} ... \end{solution}
```

`app/services/tex_parse.py` 是确定性解析器，`app/services/tex_import.py` 负责入库。实测：

```text
274 份试卷   6050 道题   4124 道带答案（68%）
0 份解析失败  0 个空题干
入库：274 sources · 6050 questions · 10174 chunks
```

对比此前：**34 道题 → 6050 道题，178 倍**。

### 一个自己写出来的 bug，和它为什么值得记

把 `\i`（虚数单位）替换成 `\mathrm{i}` 时，用的是朴素字符串替换——于是 `\in` 也中招：

```text
\{x \in \R\}  →  \{x \mathrm{i}n \R\}
```

**十个题目的集合符号全部被写错**，而解析器的所有计数指标（题数、空题干数）都显示正常——**这类错误只有人去看一眼输出才会发现**。

修法是 `\i(?![a-zA-Z])`。测试里留了一条断言专门守它：“and it did not eat \in”。

### 授权写进数据，不是写进 README

CC BY-SA 4.0 要求署名与相同方式共享。只在文档里写一句是不够的——部署可以丢掉文档，数据不会。

因此给 `knowledge_sources` 加了 `rights_note` 列，导入时写入：

```text
Gaokao-Math-Problems-Compilation (CC BY-SA 4.0), <repo> ;
upstream questions: deekur/gaokaomath (CC BY 4.0)
```

`rights_status` 仍是 `licensed`——**CC BY-SA 是真实的许可证**，它不是“来源不明”，也不是“自有版权”。两者缺一不可：状态回答“能不能用”，note 回答“凭什么”。

### 检索实测（真实语料，教师口吻）

```text
「导数」     → 8 命中（2014 新课标Ⅱ、2014 天津、2026 全国Ⅰ…）
「圆锥曲线」 → 4 命中
「数列 求和」→ 8 命中
```

返回的题干是**干净的 LaTeX**（`函数 \(f(x)\) 在 \(x=x_0\) 处导数存在…`），可以直接展示与再生成。

### 明确没做的

* **解析（solution）不入库**：它是长段散文，会淹没检索；语料是用来“被找到”的。
* **图片不入库**：`\includegraphics` 被替换为 `[图]`，几何题的图缺失。
* **春季高考混在普通卷里**：语料目录同时包含两者，导入没有区分。
* 解析器不认 `\begin{problem}` 之外的题面结构（如个别年份的自定义环境），也不做题目去重。

**流水线：28 项检查（17 静态 + 27 数据库套件 + TeX 解析器）。**

----------------------------------------

------------------------------------------------------------------------


## D.81 2026-11-05 教材入库：974 页 OCR，1797 块，以及被挤掉的教材命中

按 D.79 的决定，人教 A 版高中数学 2019 版 5 册进库。

### 文字层是陷阱

5 册里有 2 册“有文字层”（必修二 278/282 页、选择性必修三 154/154 页）。抽出来是这样：

```text
犪＝（狓１，狔１）·（狓２，狔２）      ← 应为 a=(x1,y1)·(x2,y2)
```

**拉丁字母被编码成了生僻汉字**（a→犪、x→狓、r→狉），`√` 变 `槡`。看起来能读，公式全坏。

D.80 里真题 PDF 也是这个问题（`∩`→`\`、`√`→`p`）。**“有文字层”不等于“有可用文本”**，这是中文教材 PDF 的普遍情形，不是个例。

结论：5 册全部走 OCR，没有一册能省。

### 换了一个 OCR 接口

讲题接口 `RecognizeEduPaperCut` 对教材页**只返回例题与习题**。实测第 20 页只回了 3 块，而“由全集 U 中不属于 A 的所有元素组成的集合称为补集”这句定义**被丢掉了**——那正是教材存在的理由。

改用 `RecognizeEduPaperOcr`（整页识别），返回整页 `content`，正文、例题、解答都在。

### 切分：教材不是题目

用 `segment()` 会把“例5”“1.”切成假题目。新增 `split_page()`：按句号切、目标 600 字、**绝不从句子中间切**。

一条测试专门守它：把定义句放进去，断言它没被切开，且整页字符数不丢（558→558）。

### 实测

```text
必修第一册   270 页 → 549 块
必修第二册   282 页 → 468 块
选择性必修一 154 页 → 277 块
选择性必修二 114 页 → 213 块
选择性必修三 154 页 → 290 块
------------------------------------------------
974 页 → 1797 块，0 失败，974 次 OCR 调用
```

全库：

```text
sources=279  questions=6050  chunks=11971  answered=4124
  gaokao_paper  274 来源 / 10174 块
  textbook        5 来源 /  1797 块
```

### 授权：`restricted`，不是 `licensed`

教材著作权在人民教育出版社。GitHub 那个仓库标了 Apache-2.0，但**上传者无权替人教社授权**——按 Apache-2.0 收录这份内容本身就是错的。

因此：

* 把平台语料的约束从“必须 `licensed`”放宽为“`licensed` 或 `restricted`”；
* 教材标 `restricted`，`rights_note` 写明著作权人、来源，以及“该仓库的许可证不适用于教材内容本身”。

**这是一次约束的放宽，需要有理由**：不同语料的授权状态本来就不同，硬塞进一个值等于在数据里写假话。

### 一个被数据暴露的检索问题

教材进库后搜「补集」，返回的 8 条**全是高考题，没有一条教材讲解**。

原因不难猜：高考题里有大量 “A∩B”、“补集” 的字面出现，而教材讲解句更长、词频更低；检索是 `ILIKE` + 知识点重叠，没有长度归一化、没有排序。**教材块被题海挤掉了。**

这不是 bug，是**没有排序**的直接后果。它正好说明为什么下一步必须先有金标准：没有基线，“改好了”无法证明。

### 流水线

```text
28 项检查（17 静态 + 27 数据库套件 + TeX 解析器 + 教材切分）
```

----------------------------------------

------------------------------------------------------------------------


## D.82 2026-11-05 模拟卷：抓取链路、两个 bug，以及一次外部服务到期

### 抓取：它不给 PDF，给的是页图

笔袋的共享空间没有下载接口。文件列表给的是 `cloud.gaojiua.com/data/*.pdf`，但**直接请求一律 403**——那是运行时会签名的地址，静态 URL 无效。

真正的链路是：

```text
/api/cloud/share/list/?tags=高中      → 共享空间列表
/api/cloud/share/file/list/?parent_id= → 目录树（优质模拟 → 试卷 → 科目 → 试题/答案）
/api/cloud/doc/preview/?url=...        → 该 PDF 的逐页图 URL
cdn01.gaojiua.com/doc_pv/*.jpg         → 页面图，可直接下载
```

所以做法是：**逐页取图 → Pillow 拼回 PDF**。68 套 × 数学（试题 + 答案）→ **130 个 PDF、810 页、64 MB**。

（其中 3 套没有数学科目或没有页图，所以不是 136。）

### 两个 bug，都出在题号上

**① `（1）` 不是题号。**

天津南开区那份用 `（1）（2）（3）` 编号。`leading_number` 只认 `1.`，于是每个块都被当成“无编号碎片”并进上一题——**整份 9 页卷子并成了 1 道题**。

修法是承认“编号是一种风格”：先看这份卷子第一题是 `1.` 还是 `（1）`，再决定括号号是新题还是小问。

**② 修完立刻崩了。**

加完风格判断后，3 份卷子直接 `list index out of range`——`merged[-1]` 在判空之前就取了。

**这是本轮第二次“改动引入新崩溃”**（上一次是 `\i` 吃掉 `\in`）。两次的共同点：改完立刻跑的是**全量样本**，所以当场发现；如果只跑了通过的样本，就会带着崩溃上线。

### 质量：能用，但不完整

两轮修复后：

```text
5 套样本  26 页  →  63 题（最初 8 题）
```

逐份：10、11（天津，修复前 1）、13、14、15 题。**每份实际约 19 题，仍漏 4–9 题**，与扫描版高考卷的结论一致。

已把两条路由都实现了：

* `cut`：讲题接口，走既有的 `ingestion.ingest`（默认）
* `whole`：整页识别 + 按题号切块（**尚未在真实调用上验证**）

### 外部服务到期

准备跑 `whole` 对比实验时：

```text
HTTP 401  OcrServiceExpired  "The OCR service has expired."
```

阿里云的「教育场景识别」资源包到期。**教材那 974 页和样本那 26 页是赶在过期前跑完的**，之后的任何 OCR 都不可用。

剩余 131 个 PDF 的 OCR（约 400 次调用）因此停住。

**这是本轮第三次被外部边界挡住**：Docker 磁盘写满、CDN 防盗链、OCR 服务到期。三次都不是代码问题，但三次都让进度停下。**依赖第三方能力的环节，必须有“服务不可用时优雅停下”的设计**——现在 `whole` 路由连编译都过了、单元测试也过了，却一次真实调用都没跑过，这就是那个风险的具体形态。

### 已补的回归测试

`backend/tests/test_ocr_rules.py`（无数据库、无厂商调用）：

* `（1）` 能识别，但只在被要求时；
* 括号编号卷子切出 4 题而不是 1 题；
* `1.` 编号卷子里的 `（2）` 仍留在题内；
* 空列表不崩；
* 整页文本按题号切块，且“没有问题号的页面”原样保留。

**流水线：31 项检查（17 静态 + 27 数据库套件 + TeX + 教材 + OCR 规则）。**

----------------------------------------

------------------------------------------------------------------------

**文档结束**

本文件应作为 Chilon 当前设计的汇总基线。后续每次重要设计变更，都应同步更新对应章节、状态标记和 ADR，并保留变更历史。
