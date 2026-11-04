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

## 当前覆盖

只包含 K009。其余模块待字段级设计完成后加入。
