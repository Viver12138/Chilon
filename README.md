# Chilon

面向高中数学教师（高考）的 AI 教学工作台。本仓库目前处于**设计与契约冻结、工程骨架就绪**阶段，尚未包含业务流程代码。

![contracts](https://github.com/Viver12138/Chilon/actions/workflows/check.yml/badge.svg)

## 文档

- [Chilon 使用说明（教师版）](docs/Chilon-用户功能说明.md) —— 面向老师的用法说明，不含技术细节
- 设计基线：`Chilon_Project_Design_Master_Document.md`（技术向）

## 这个仓库里有什么

```text
Chilon_Project_Design_Master_Document.md   设计与契约基线（65 个章节、AD 记录 D.1–D.30）
design/                                     设计分册 D1–D6、K09 字段设计、走查包、校验器
schemas/                                    机器可读契约（状态机、动作、接口、导航、测试矩阵）
database/registry/                          表结构权威：6 个模块、82 张表
database/generator/                         校验器与确定性 DDL 生成器
database/generated/                         生成产物（勿手改）
database/tests/                             容器冒烟、迁移闭环、覆盖校验
backend/                                    Alembic 基线 + 应用骨架
tools/check_all.py                          14 项检查的唯一入口
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

# PDF 导出与教师上传（上传在 RLS 下运行，非超级用户）
pwsh -NoProfile -File database/tests/run_pdf_upload_test.ps1
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

## 设计与契约的状态

设计已完成并冻结：分册 D1（产品闭环与门禁）、D2（信息架构）、D3（页面规格）、D4（动作与错误码）、D5（接口与 SSE）、D6（验收与测试矩阵）、K09（知识库字段设计）。

契约以 JSON 形式版本化，均有对应校验器且带自测（注入缺陷必须被检出）。

## 已知欠账

- **场景 B/C/D 未做教师走查**，只有场景 A 有一次真实教师验证。D3 冻结时保留了 `unverified` 清单，而不是宣称已验证。
- **`created_by` 一类字段暂无外键**：它们常由系统 Worker 写入，而 Worker 不是用户。需要先设计"系统主体"概念。
- **`0001_baseline` 仍是可重建基线**：一旦有环境部署过就必须冻结，之后只能新增 revision。
## 用 docker compose 跑起来

`ash
cp .env.example .env          # 填入 CHILON_DB_PASSWORD（本地开发可用默认值）
docker compose up -d --build
`

打开 http://127.0.0.1:8000/ 注册一个账号，然后写一句话、批准方案、下载教师版和学生版。

容器启动时会依次做三件事，**每次启动都做，不只是第一次**：

1. 等数据库可连接（用 psycopg 探测，不用 pg_isready——它不在这个镜像里）；
2. lembic upgrade head（已是当前版本时是无操作）；
3. 应用 database/seed/platform_tools.sql（ON CONFLICT DO NOTHING，幂等）。

任何一步失败，服务器都不会启动——不会留下一个半死不活的进程。

/healthz 只回报进程存活，**不查数据库**：依赖故障不应该让进程看起来也死了，否则编排器会去重启一个本身正常的服务。

导出与上传文件存放在 chilon-data 卷的 /data 下（CHILON_EXPORT_DIR / CHILON_UPLOAD_DIR），**重新部署不会删掉教师已经下载过的文件**。
