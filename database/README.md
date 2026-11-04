# Database

Registry-first：`registry/` 是结构权威，`generated/` 是产物，两者不同步时 CI 失败。

| 目录 | 作用 |
| --- | --- |
| `registry/` | 手写：模块、表、字段、约束、索引、RLS |
| `generator/` | 校验与确定性 DDL 生成 |
| `generated/` | 生成的 SQL 与 manifest，**不要手改** |

## 命令

```bash
python database/generator/validate_registry.py --selftest
python database/generator/generate_ddl.py
python database/generator/generate_ddl.py --check   # CI 用
```

## 当前覆盖

只包含 K009（13 张表）。其余模块待字段级设计完成后加入。
