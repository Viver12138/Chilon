# Chilon Backend

工程骨架，未包含业务代码。

## 目录

```
backend/
  app/
    __init__.py
    main.py          # FastAPI 应用入口（占位）
    settings.py      # 配置加载（占位）
  tests/
    __init__.py
  pyproject.toml
```

## 与设计文档的对应

| 设计输入 | 位置 |
| --- | --- |
| 状态机 | `schemas/state_machines.v1.json` |
| 动作与错误码 | `schemas/actions.v1.json` |
| 接口契约 | `schemas/api_surface.v1.json` |
| 表结构 | `database/registry/` |
| 页面规格 | `design/Chilon_Design_Volume_D3_Page_Specifications.md` |

## 启动（待实现）

```bash
pip install -e .
uvicorn app.main:app --reload
```

## 约束

- 契约变更后必须跑 `python tools/check_all.py`，CI 会拦截不一致。
- 数据库变更走 Registry → 生成器 → Alembic，不手工改 DDL。
