# Database

Registry-first：`registry/` 是结构权威，`generated/` 是产物，两者不同步时 CI 失败。

| 目录 | 作用 |
| --- | --- |
| `registry/` | 手写：模块、表、字段、约束、索引、RLS |
| `generator/` | 校验与确定性 DDL 生成 |
| `generated/` | 生成的 SQL 与 manifest，**不要手改** |
| `tests/` | 容器冒烟测试与结构断言 |

## 命令

```bash
python database/generator/validate_registry.py --selftest
python database/generator/generate_ddl.py            # core 变体（默认）
python database/generator/generate_ddl.py --with-optional   # 含 pgvector 表
python database/generator/generate_ddl.py --check    # CI 用：检测漂移
```

## 容器冒烟测试

把生成的 DDL 应用到真实的 PostgreSQL 17 容器，并断言表数量、RLS、策略、索引、外键，以及
两层知识库约束是否真的会拒绝坏数据。

```powershell
# Windows（需要 Docker Desktop 正在运行）
.\database\tests\run_container_test.ps1
.\database\tests\run_container_test.ps1 -KeepContainer   # 保留容器供排查
```

```bash
# Linux / CI
pwsh -NoProfile -File database/tests/run_container_test.ps1
```

## 两个变体

| 变体 | 表数 | 何时用 |
| --- | --- | --- |
| `core`（默认） | 12 | MVP；向量检索不在主路径（D.13） |
| `with-optional` | 13 | 启用 pgvector 时；需要 `CREATE EXTENSION vector` |

`core` 变体跳过 `knowledge_question_embeddings`，并在文件头列出被跳过的表。

## 迁移（Alembic）

迁移是**不可变快照**：生成时把当前 DDL 嵌进 revision 文件，之后 Registry 再变也不会改写历史。

```bash
# 1. 改 Registry
# 2. 重新生成 DDL
python database/generator/generate_ddl.py
# 3. 校验 DDL 与 Registry 一致
python database/generator/generate_ddl.py --check
# 4. 生成新 revision（--down 指向当前最新 revision）
python database/generator/gen_migration.py --id 0002_xxx --slug "add something" --down 0001_baseline
# 5. 应用到数据库
cd backend && alembic upgrade head
```

**漂移保护**：`database/tests/check_migration_sync.py` 比较最新 revision 记录的 `SCHEMA_HASH`
与当前 manifest。若两者不一致，说明"改了 Registry、重新生成了 DDL，但忘了生成迁移"，CI 会失败。

**切分正确性**：`database/tests/check_migration_splitter.py` 验证迁移里的 SQL 切分器不会在
`$$ ... $$` 函数体内部切断语句。这是唯一可能静默损坏 DDL 的环节。

迁移用**同步驱动**（psycopg）执行：asyncpg 不支持多语句执行，而 DDL 不在请求路径上。
应用本身仍然 async。

依赖（需自行安装）：

```bash
python -m venv .venv
.venv/Scripts/pip install alembic "psycopg[binary]"
```

### 迁移端到端测试

```powershell
.\database\tests\run_migration_test.ps1
```

起容器 → `alembic upgrade head` → 结构验证 → 检查 `alembic_version` → `alembic downgrade base`
→ 断言表与函数都被清干净。这条比直接应用 DDL 更接近真实发布路径。

## 当前覆盖

| 模块 | 表数 | 状态 |
| --- | --- | --- |
| K009 Knowledge Base | 13 | 已入库（含 1 张可选表） |
| K011 Task & Agent Orchestration | 17 | 已入库 |
| K012 Project & Material | 10 | 已入库 |
| K013 Conversation & Activity | 7 | 已入库（消息修订表判定为非 MVP） |
| K014 Quality & Evaluation | 24 | 已入库 |
| K021 Administrative Security | 4 | 已入库（无 K002 外键） |

core 变体生成了 74 张表（K009 的可选向量表默认跳过）。其余模块待字段级设计完成后加入。
