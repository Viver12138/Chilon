# 平台语料投放目录

把教材、高考真题、模拟卷放进来，然后执行：

```bash
docker compose exec app python tools/import_platform.py --dir /corpus --source-type gaokao_paper
```

- 单份文件用 `--file`，目录用 `--dir`。
- 重复导入按 SHA-256 跳过，可以放心重跑。
- 扫描件需要 `CHILON_OCR_PROVIDER=aliyun`，否则会明确失败并在输出里给出原因。
- 解析版不建议作为题目来源：导入后会带上 `analysis_version` 原因。
