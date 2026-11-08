# 平台语料投放目录

把教材、高考真题、模拟卷放进来，然后执行：

```bash
docker compose exec app python tools/import_platform.py --dir /corpus --source-type gaokao_paper
```

- 单份文件用 `--file`，目录用 `--dir`。
- 重复导入按 SHA-256 跳过，可以放心重跑。
- 扫描件需要 `CHILON_OCR_PROVIDER=aliyun`，否则会明确失败并在输出里给出原因。
- 解析版不建议作为题目来源：导入后会带上 `analysis_version` 原因。

## 高考真题（TeX 源，推荐）

2012–2026 的 6050 道高考数学真题，来自
[Gaokao-Math-Problems-Compilation](https://github.com/DxAThing/Gaokao-Math-Problems-Compilation)
（**CC BY-SA 4.0**，上游题目来自 [deekur/gaokaomath](https://github.com/deekur/gaokaomath)，CC BY 4.0）。

```bash
# 取得源码（只取 content/ 与 index/）
git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/DxAThing/Gaokao-Math-Problems-Compilation.git tex
cd tex && git sparse-checkout set content index

# 导入 2012 年起的全部真题
docker compose exec app python tools/import_tex.py --content /corpus/tex/content --since 2012
```

- 需要管理员数据库角色（平台语料写入绕过 RLS）。
- 按文件 SHA-256 幂等，可重复执行。
- 导入时会写入 `rights_note`，记录许可证与上游仓库 —— CC BY-SA 要求署名，**这条要求在数据里，不在文档里**。
- 解析结果：6050 题，其中 4124 题带答案；解析（solution）不入库。
