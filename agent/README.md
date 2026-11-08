# Chilon Teaching Agent

面向高中数学教师的 DeepSeek Harness Agent 参考实现。V1 采用：

```text
System Prompt + 6 Skills + 5 Tools + Chilon Backend
```

## 目录

```text
agent/
├── prompts/
│   ├── system.md
│   ├── teaching-principles.md
│   └── output-format.md
├── skills/
│   ├── knowledge-summary/SKILL.md
│   ├── question-retrieval/SKILL.md
│   ├── question-analysis/SKILL.md
│   ├── lesson-planning/SKILL.md
│   ├── exam-analysis/SKILL.md
│   └── teaching-material-generation/SKILL.md
├── tools/tool-contracts.md
└── evaluation/
    ├── evaluation_rules.md
    └── datasets/
```

后端实现：

- `backend/app/services/teaching_agent.py`
- `backend/app/api/teaching_agent.py`

## 启动

```bash
# 后端依赖运行中
python tools/check_all.py
```

在应用进程内调用：

```text
POST /teaching-agent/chat
Authorization: Bearer <teacher token>
```

工具接口见 `agent/tools/tool-contracts.md`。

## 设计约束

- Agent 不直接访问 PostgreSQL/Qdrant，只调用后端工具；
- 检索不足时报告实际数量，不补造真题；
- 生成题必须标注 `[Agent 生成]`；
- 无工具结果时不得声称“已检索知识库”；
- 无 LLM key 时退化为证据模式，不阻塞调试。

## 评测

```text
agent/evaluation/datasets/*.jsonl
agent/evaluation/evaluation_rules.md
```

首批样例覆盖：知识总结、真题检索、条件约束、试题分析、教学设计、资料生成。
