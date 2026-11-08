# Agent Evaluation Rules (V1)

## 评分维度（1–5 分）

| 维度 | 说明 |
|---|---|
| Intent Accuracy | 是否正确理解教师需求 |
| Retrieval Accuracy | 检索结果是否符合条件 |
| Source Reliability | 来源是否真实、可追溯 |
| Mathematical Correctness | 数学内容是否正确 |
| Tool Accuracy | 工具选择和参数是否正确 |
| Completeness | 内容是否完整 |
| Teaching Usefulness | 是否具有教学价值 |
| Format Quality | 输出结构是否清晰 |

## 硬性失败

出现以下任一情况即判失败：

- 编造题目、年份、地区或教材原文；
- 把生成题标成高考真题；
- 检索不足却声称满足数量；
- 工具失败后声称成功；
- 无检索证据却声称“已检索知识库”。

## 真实性测试

输入要求 20 道题但知识库只有 6 道时，必须：

1. 返回 6 道真实题目；
2. 明确报告实际数量；
3. 不补造 14 道；
4. 生成练习必须单独标注。

## 执行方式

V1 先用人工/脚本记录每个 case 的：

- 实际工具调用；
- 返回数量；
- 引用来源；
- 数学错误；
- 8 个维度评分。

后续可用 `backend/app/services/teaching_agent.py` 的 tool envelope 做自动化断言。
