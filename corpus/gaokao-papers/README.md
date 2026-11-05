# 高考数学真题

存放平台语料的原始试卷。导入命令（在项目根执行）：

```bash
docker compose exec app python tools/import_platform.py --dir /corpus/gaokao-papers --source-type gaokao_paper
```

## 入库约定

- **只放原卷**，不放解析版：解析版会被判为 `analysis_version`，不适合作为题目来源。
- **优先 PDF**：同一份卷子 PDF 切出 15 题，JPG 只切出 14 题。
- 同一份文件重复放入无副作用（按 SHA-256 跳过）。
- 命名建议：``年份-卷别-科目-原卷.pdf`，例如 `2024-新课标Ⅰ卷-数学-原卷.pdf`。
- 扫描件需要 `CHILON_OCR_PROVIDER=aliyun`，否则会明确失败并在输出里给出原因。