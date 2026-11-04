# Chilon

面向高中数学教师（高考）的 AI 教学工作台。本仓库目前处于**设计与契约冻结、工程骨架就绪**阶段，尚未包含业务流程代码。

![contracts](https://github.com/Viver12138/Chilon/actions/workflows/check.yml/badge.svg)

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
```

## 设计与契约的状态

设计已完成并冻结：分册 D1（产品闭环与门禁）、D2（信息架构）、D3（页面规格）、D4（动作与错误码）、D5（接口与 SSE）、D6（验收与测试矩阵）、K09（知识库字段设计）。

契约以 JSON 形式版本化，均有对应校验器且带自测（注入缺陷必须被检出）。

## 已知欠账

- **场景 B/C/D 未做教师走查**，只有场景 A 有一次真实教师验证。D3 冻结时保留了 `unverified` 清单，而不是宣称已验证。
- **`created_by` 一类字段暂无外键**：它们常由系统 Worker 写入，而 Worker 不是用户。需要先设计"系统主体"概念。
- **`0001_baseline` 仍是可重建基线**：一旦有环境部署过就必须冻结，之后只能新增 revision。
