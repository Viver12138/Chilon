# Chilon Teaching Agent — Tool Contracts

所有工具统一返回：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "metadata": {}
}
```

失败：

```json
{
  "success": false,
  "data": null,
  "error": {"code": "RESOURCE_NOT_FOUND", "message": "..."},
  "metadata": {}
}
```

## 后端路由

| Tool | HTTP |
|---|---|
| `search_knowledge` | `POST /teaching-agent/tools/search_knowledge` |
| `get_question_detail` | `GET /teaching-agent/tools/questions/{question_id}` |
| `get_textbook_content` | `POST /teaching-agent/tools/get_textbook_content` |
| `get_source_detail` | `GET /teaching-agent/tools/sources/{source_id}` |
| `calculate_math` | `POST /teaching-agent/tools/calculate_math` |
| `chat` | `POST /teaching-agent/chat` |

所有工具都需要 `Authorization: Bearer <token>`。

## search_knowledge

```json
{
  "query": "数列求和",
  "source_types": ["gaokao", "mock_exam"],
  "year_range": {"start": 2020, "end": 2025},
  "question_types": ["free_response"],
  "knowledge_points": ["数列求和"],
  "limit": 10,
  "mode": "h",
  "scope_override": "question"
}
```

`source_types` 接受 `textbook`、`gaokao`、`mock_exam`；后端映射到
`textbook`、`gaokao_paper`、`mock_exam`。

返回的 `data.items` 每项保留：

- `question_id` / `chunk_id`
- `content`
- `answer`
- `question_type`
- `knowledge_points`
- `source.source_id/name/source_type/year/paper/locator`
- `rank` / `score`

`total` 与 `returned` 是本次调用的实际结果数量，不是全库统计。

## get_question_detail

通过稳定的 `question_id` 获取题目、答案、来源。ID 不存在时返回
`RESOURCE_NOT_FOUND`，不允许根据题干猜来源。

## get_textbook_content

```json
{"query": "等差数列求和公式", "grade": "高二", "volume": "选择性必修第二册", "limit": 8}
```

返回教材 chunk 与来源、位置；`volume` 为软过滤。

## get_source_detail

通过 `source_id` 返回来源类型、年份、地区、版本数和 chunk 数。

## calculate_math

只支持基础四则运算、幂、括号、`sqrt/sin/cos/tan/log/ln/exp/abs/floor/ceil`；
拒绝代码执行和省略号求和表达式。计算结果不等于数学证明。

## chat

```json
{
  "message": "总结数列求和的常见方法，并找 5 道高考真题",
  "history": [{"role": "user", "content": "..."}]
}
```

返回：

- `answer`
- `task_type`
- `citations`
- `generated`
- `evidence_count`
- `tool_calls`

无 LLM key 时仍返回证据模式结果，不会伪造生成答案。
