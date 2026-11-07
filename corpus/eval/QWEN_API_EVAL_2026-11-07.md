# Qwen API 索引与重排 · 15 条真人问题评测（2026-11-07）

> 目的：把 embedding + rerank 切到阿里云百炼中国区（北京）后，在**未改动的 15 条真人问题**上对照本地 CPU 基线，确认 API 是否可用、指标是否退化。
> 结论先行：**API 链路可用**。原始 15 条 Recall 14/15（93.3%），加入稀有词 rescue 后 **15/15（100%）**；但 MRR 仍低于本地基线（无重排 0.780、API 重排 0.723 vs 本地 0.836/0.818）。**Q08 的 miss 不是 API 回归**，而是“近五年 + 递推”过滤冲突，已用稀有词 rescue 修复；重排是否默认启用仍要等 v2 strict 集。

## 1. 索引构建

| 项 | 值 |
| --- | --- |
| collection | `chilon_chunks_qwen3_7_text_embedding_v1` |
| points | **12,973 / 12,973** |
| embedding | `qwen3.7-text-embedding`，dim **1024**，cosine |
| 请求数 | **649**（20 条/请求） |
| input tokens | **2,332,424** |
| 成本（¥0.5/M） | **≈ ¥1.17** |
| 总耗时 | **978.4s ≈ 16.3 min**（embed 963.4s，upsert 10.5s） |
| 吞吐 | 13.47 chunks/s，2,421 tokens/s |
| payload 索引 | source_type / paper / question_type / year |

manifest：`var/retrieval/index_manifest_qwen3_7_api.json`

## 2. 评测结果（15 条冻结问题，同一 judge 口径）

| 组 | Recall@8 | MRR@8 | 空结果 |
| --- | ---: | ---: | ---: |
| 本地 Qwen3-Embedding-0.6B，无 rerank（历史） | 14/15 = 93.3% | **0.836** | 0% |
| 本地 + Qwen3-Reranker-0.6B（历史） | 14/15 = 93.3% | 0.818 | 0% |
| **API embedding，无 rerank** | 14/15 = 93.3% | **0.702** | 0% |
| **API embedding + `qwen3.7-text-rerank`（raw query）** | 14/15 = 93.3% | **0.714** | 0% |
| API embedding + API rerank（query 加 instruction 模板） | 14/15 = 93.3% | 0.677 | 0% |
| **API embedding + 稀有词 rescue，无 rerank** | **15/15 = 100%** | **0.780** | 0% |
| **API embedding + API rerank + 稀有词 rescue** | **15/15 = 100%** | **0.723** | 0% |

- API 重排平均 **0.58s/query**（CPU 本地同任务约 82.7s/query），15 条整轮含检索约 **12s**；
- 给 query 加 `Instruct: ...\nQuery:` 模板没有收益（0.708 / 0.677），**默认用 raw query**；
- Recall 不变、MRR 下降：不是“找不到”，而是**排序位置变差**。

### 2.1 逐条变化（API 相比本地基线）

无 rerank：Q03 1→2、Q05 1→4、Q16 1→4；其余 rank1 不变。
API rerank：Q03 8→1（改善）、Q20 7→1（改善）；Q05 1→5、Q06 1→5、Q07 1→7、Q09 1→6（退化）。

## 3. 失败原因

### 3.1 Q08 为什么 miss（旧基线也 miss）

Q08 原话：**“整理近五年高考数学数列大题，重点筛选递推数列和数列求和类型……”**，期望 `{any: [递推, 数列求和]}`。

抽取到的条件：

```json
{"year_range": [2022, 2026], "source_types": ["gaokao_paper"],
 "question_types": ["free_response"], "knowledge_points": ["数列"],
 "keywords": ["数列", "递推"]}
```

核查结果：

- 全库含“递推”的 chunk 有 **26 条**，但示例全部落在 **2012–2015 年**（如 2012 全国卷、2013 全国卷、2015 全国卷）；
- 加上“近五年（2022–2026）”过滤后，文本检索只剩 **27 条**，**不含“递推”**；
- 过滤后 27 条 ≥ `min_filtered_hits=8`，所以**不会回退到无过滤文本检索**；
- 无过滤文本检索里“递推”排 **rank 1**，但这条路径没有被执行；
- 向量路径 50 条里也没有“递推”（语义检索偏向一般“数列”，不认这个稀有词）；
- RRF 融合后 top-8 无“递推/数列求和” → lenient judge 判 miss。

**根因**：查询把“近五年”硬约束和“递推”稀有词放在一起，而语料里近五年没有递推题；过滤策略又没有触发回退。**这是检索策略与数据现实冲突，旧基线同样存在**，不是 API 引入的失败。修复方向（v2 设计）：

1. 查询含“稀有词 + 年份约束”时，过滤后若不含该稀有词，做**并集**（过滤结果 + 无过滤的稀有词命中）而不是只看过滤结果；
2. 或把这类查询标成“unanswerable/证据不足”专项，不按 miss 计；
3. 或数据侧补近五年递推题（当前语料确实没有）。

“数列求和”全库也只有 2 条 chunk，期望本身脆弱（v1 备注已写）。

### 3.1.1 修复与复测（2026-11-07）

已实现 **稀有词 rescue**（`backend/app/services/hybrid_retrieval.py`）：

1. 统计 query 关键词在语料中的 chunk 频次，≤50 视为稀有词（如“递推”=26）；
2. 过滤后的文本结果若**完全不含**稀有词，则跑一次无过滤文本检索，取出含该稀有词的结果作为**第三路**；
3. RRF 融合时给 rescue 路权重 **3.0**（`[文本 1.0, 向量 1.0, 稀有词 3.0]`），避免稀有词被普通“数列”结果淹没；
4. 记录 `rare_keywords_missing` / `rare_rescue_used`，产品层可提示“近五年无，以下为更早年份”。

复测（同一 15 条、同一 API 索引）：

| 指标 | raw API | + 稀有词 rescue |
| --- | ---: | ---: |
| Recall@8（无重排） | 14/15 | **15/15** |
| Recall@8（API 重排） | 14/15 | **15/15** |
| MRR@8（无重排） | 0.702 | **0.780** |
| MRR@8（API 重排） | 0.714 | **0.723** |

- Q08：无重排 **rank 1**、API 重排 **rank 6**，从 miss 变为命中；
- Q06 也触发 rescue（“余弦定理/恒等/变换”被过滤丢失）：无重排 3→2；
- 代价：Q05 的 API 重排 5→6（轻微）；rescue 会**绕过年份硬过滤**，产品需显式提示年份不符。

复测产物：`var/retrieval/hybrid_eval_qwen_api_rare2_2026-11-07.json` / `.md`。

**复跑校验（2026-11-07）**：同配置再跑一遍（`var/retrieval/hybrid_eval_qwen_api_rare_rerun_2026-11-07`），逐条 `status/lenient_rank` 与首次 **0 差异**，指标一致（15/15、MRR 0.780/0.723），说明该修复结果可复现。

### 3.2 MRR 为什么下降

- **API embedding 排序差异**：Q05（1→4）、Q16（1→4）、Q03（1→2）——qwen3.7 的语义排序与本地 Qwen3-Embedding-0.6B 不同，把“含期望片段”的 chunk 排后了；
- **API rerank 与 lenient judge 的错位**：`qwen3.7-text-rerank` 按语义相关性排序，会压后“语义相关、但正好含期望字面片段”的 chunk（Q05/Q06/Q07/Q09）；同时把 Q03/Q20 提到 rank1。**本地 reranker 也有同样现象**（Q03/Q20 被降序），只是 API 模型更强、影响更大；
- **judge 口径**：现在的指标是 lenient 片段匹配（top-8 excerpt 里出现 `expect.any` 即算），不是 strict chunk 命中；语义重排天然会与片段匹配冲突。**不能用 15 条上的 MRR 降来判定 API 重排“坏了”**，应等 v2 strict 数据集（chunk_id 金标）+ nDCG 再决定重排默认开关。

## 4. 结论与下一步

1. **API 链路可用**：索引 16.3 分钟/¥1.17，15 条评测 12 秒；Recall 与本地持平，稀有词 rescue 后 **15/15**；
2. **不能用这 15 条判定重排收益**：样本小、无 strict；API 重排 MRR 0.723 仍低于本地 0.818，Q08 经 rescue 命中但 rank 6。等 v2.0（60 条/30 strict）再决定默认开关；
3. **稀有词 + 年份过滤已修**：`text_search_with_rare_rescue` + 加权 RRF（1/1/3），Q08 从 miss → rank1（无重排）；产品需提示“年份不符”；
4. **API 模型已按质量优先选 `qwen3.7-text-embedding` + `qwen3.7-text-rerank`**；本地模型保留为离线回退，两套索引并存：
   - 本地：`chilon_chunks_qwen3_embedding_0_6b_v1`（12,973）
   - API：`chilon_chunks_qwen3_7_text_embedding_v1`（12,973）
5. **不要在这 15 条上调参**；v2 评测集到位后按五组对照（L/T/V/H/HR）重跑。

## 5. 产物

- 索引：`var/retrieval/index_manifest_qwen3_7_api.json`
- 评测（raw）：`var/retrieval/hybrid_eval_qwen_api_2026-11-07.json` / `.md`
- 评测（稀有词 rescue）：`var/retrieval/hybrid_eval_qwen_api_rare2_2026-11-07.json` / `.md`
- 指令模板对照：`var/retrieval/hybrid_eval_qwen_api_instr_2026-11-07.json`
- 代码：`tools/qwen_api.py`、`tools/build_qwen_index.py`、`tools/eval_hybrid.py --api`、`backend/app/services/hybrid_retrieval.py`（rare rescue + weighted RRF）

## 6. 边界

- 15 条真人问题、lenient 片段判定、无 strict target；Q08 的期望词在年份约束下不可得，rescue 是**有意绕过**年份硬过滤，产品必须提示年份不符；
- rescue 阈值（≤50 chunks）与权重（3.0）是在这 15 条上定的，**有过拟合风险**；v2 strict 集上需重新确认；
- API 与本地 embedding 不是同一模型，排序差异不能简单归因于“API 更差”；
- 成本按北京区原价 ¥0.5/M 估算，实际账单价以百炼控制台为准。
