# 混合检索原型与真人问题基線复测 · 2026-11-06

> **结论（先看这里）**
>
> | 组 | Recall@8 | MRR@8 | 空结果率 | 有结果但不对 |
> | --- | ---: | ---: | ---: | ---: |
> | 旧引擎基线（26.7% 历史对照，本次未改） | 26.7%（4/15） | 0.180 | 13.3%（2/15） | 9/15 |
> | **混合检索（pg_trgm + Qdrant 向量 + RRF，无 rerank）** | **93.3%（14/15）** | **0.836** | **0.0%（0/15）** | **1/15** |
> | **混合 + Qwen3-Reranker-0.6B** | **93.3%（14/15）** | **0.818** | **0.0%（0/15）** | **1/15** |
>
> - 同一批**冻结的 15 条真人问题**、同一套判定代码（`tools/eval_retrieval.py` 的 judge/metrics，未改口径）、同一数据库快照（chunk 文本未变）。
> - Reranker 在 15 条上没有提升 Recall，MRR 反而从 0.836 降到 0.818（Q03 1→8、Q20 1→7 两条被降序）；**当前 CPU 上 rerank 成本 82.7s/查询，不建议默认启用**。
> - 旧 `55%`（40 条开发者自拟）与本次不可比；`26.7%` 是同一 15 条在旧引擎上的历史基线，仅作对照。
> - 数字来自 2026-11-06 16:26 的真实运行；未修改 `knowledge_search`、未按测试集调检索参数。

## 1. 环境与版本

| 项 | 值 |
| --- | --- |
| 硬件 | Intel Core Ultra 5 125H / 14C18T / 31.6GB RAM / 无独显 |
| Python | `.venv` Python 3.12.14 |
| torch | **2.15.0+cpu**（CPU wheel） |
| transformers | **5.22.1** |
| qdrant-client | **1.20.0** |
| Qdrant | Docker 容器 `chilon-qdrant`，`127.0.0.1:6333`（镜像 `qdrant/qdrant:latest`，卷 `chilon-qdrant-data`） |
| PostgreSQL | Docker 容器 `chilon-pg-corpus`，`127.0.0.1:55495/chilon`，`postgres` 角色（superuser，`system_session`） |
| 语料 | 346 sources / 12902 chunks / 6981 questions（与基线一致） |
| pg_trgm | 已 `CREATE EXTENSION pg_trgm` + `ix_knowledge_chunks_text_trgm` GIN 索引 |
| 运行 git commit | `381d904`（本轮代码未 commit） |

依赖安装记录：`torch` 来自 `https://download.pytorch.org/whl/cpu`，其余来自 PyPI；模型文件与缓存放在 `var/retrieval/models/`、`var/retrieval/hf_cache/`（`var/` 已被 gitignore）。

## 2. 模型（本地 CPU）

| 模型 | revision | 维度 / 长度 | 加载 | 备注 |
| --- | --- | --- | --- | --- |
| Qwen/Qwen3-Embedding-0.6B | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | dim=1024；`max_length=512` | ~8–18s，RSS ~2.7GB | fp32 CPU；query 用固定 instruction；文档侧不加 instruction |
| Qwen/Qwen3-Reranker-0.6B | `e61197ed45024b0ed8a2d74b80b4d909f1255473` | `max_length=1024` | ~2–9s，RSS ~2.9GB | batch=4（本机实测 0.51 pairs/s，batch=8 更慢 0.40） |

下载过程（如实记录）：HuggingFace 直连下载大文件在 15MB 处停滞；改用 **hf-mirror**（`HF_ENDPOINT=https://hf-mirror.com`）+ `HF_HUB_DISABLE_XET=1` 后以约 45MB/s 完成，两个模型各 1.19GB。模型 revision 从 HF 缓存 refs 读取。

## 3. 向量索引

| 项 | 值 |
| --- | --- |
| collection | `chilon_chunks_qwen3_embedding_0_6b_v1` |
| points | **12902 / 12902** |
| 向量 | dim=1024，cosine，fp32 |
| payload | `chunk_id / question_id / source_id / source_type / title / year / paper / question_no / question_type / knowledge_points / locator` |
| payload indexes | `source_type` (keyword)、`paper` (keyword)、`question_type` (keyword)、`year` (integer) |
| embedding 输入 | V1.2 §9.3：「资料类型 / 年份 / 试卷 / 题号 / 题型 / 知识点 + 正文」，不拼接答案与大量无关元数据 |
| 知识点的数据口径 | **读 `knowledge_annotations`（active：`superseded_by IS NULL`，kp_primary + kp_secondary），不读 `knowledge_questions.current_knowledge_points`**；kp_id→中文名用 vault 词表（120 条）映射 |
| manifest | `var/retrieval/index_manifest.json` |

### 3.1 建索引吞吐与内存（V1.2 §17 要求的实测）

| 阶段 / 配置 | 观测 |
| --- | --- |
| 3 进程 × 6 threads（短 chunk 段） | 每进程 ~5.0 chunks/s，合计 **~12.8 chunks/s** |
| 单进程 × 16 threads（中等长度） | **~1.2 chunks/s** |
| 3 进程 × 6 threads（收尾长 chunk） | 每进程 ~0.2 chunks/s（~84 tokens/s/进程），合计 **~0.6 chunks/s / ~252 tokens/s** |
| 模型加载 | 9–18s |
| 常驻内存 | 加载后 ~2.7GB/进程；建库峰值 **3.0–3.3GB/进程**；3 进程合计 ~9.5GB |
| 全量 12902 chunks 的 token 量 | `sum(min(len,512)) = 2,060,271` tokens |
| 全量建库墙钟 | 13:37 首启 → 16:01 manifest，约 **2h24m**（含 2 次 OOM 中断与多个 resume 阶段）；有效约 1.5 chunks/s / ~238 tokens/s |

**为什么慢**：0.6B 模型在 CPU 上是 fp32 forward；chunk 长度差异大（p50=133、p90=364、max=1695 tokens），长 chunk 阶段每进程只有 ~84 tokens/s。按长度排序组 batch 比不排序快约 1.8×（实测 296 vs 164 tokens/s，单进程）。

### 3.2 OOM 事件（基础设施问题，不计入检索结论）

- 第一次：3 个 shard 同时运行至 6144 points 时，系统 commit 余量耗尽，PyTorch CPU allocator 报 `not enough memory`（申请 6MB 也失败）。
- 第二次：2 个 shard 至 10496 points 时再次 OOM。
- 根因：机器上**非本项目进程 `LeASPac.exe` 私有提交内存 53.8GB**（WorkingSet 仅 1.6GB，疑似泄漏），把 Windows commit limit（87.4GB）吃光；不是模型或索引代码的问题。
- 处置：每次 OOM 后都用 `--resume` 跳过已 upsert 的 chunk 无损继续；最终由用户批准结束 LeASPac 后，commit 余量恢复到 ~40GB，3 shard 并行把剩余 1894 chunks 建完。
- **影响**：索引最终完整（12902/12902）；吞吐数据包含长 chunk 的真实性能，不把 OOM 当作评测结论。

## 4. 混合检索原型（新代码，不改旧 `knowledge_search`）

代码：

| 文件 | 作用 |
| --- | --- |
| `backend/app/services/hybrid_retrieval.py` | 条件抽取 / embedding 输入 / 文本检索 / Qdrant 检索 / RRF / rerank / 指标配置（`CONFIG`） |
| `tools/build_hybrid_index.py` | 读 PG → embed → upsert Qdrant；支持 `--create-only / --resume / --shard-* / --threads`，每 256 点 upsert |
| `tools/eval_hybrid.py` | 15 条两组评测（复用旧 eval 的 `judge_query` / `compute_metrics`） |
| `tools/merge_index_manifests.py` | 合并分片 manifest、写 `index_manifest.json` |

流程：

```text
教师原话
  → 规则抽取：年份段/卷别/来源类型/题型 + jieba 关键词（+ taxonomy 知识点名仅记录，不用作过滤）
  → 文本路径：pg_trgm 关键词匹配（ILIKE ANY + word/similarity 排序）top-50
  → 向量路径：Qdrant cosine top-50（payload 结构化过滤）
  → 合并去重 + RRF（k=60）
  → [组 A] 直接 top-8
  → [组 B] top-40 交给 Qwen3-Reranker-0.6B，top-8
```

### 4.1 冻结参数（评测前固定，未按测试集调整）

| 参数 | 值 |
| --- | --- |
| `final_k` | 8 |
| `text_top_n` / `vector_top_n` | 50 / 50 |
| `rrf_k` | 60 |
| `rerank_candidates` | 40 |
| `min_filtered_hits`（过滤后不足则回退无过滤） | 8 |
| embed `max_length` / build batch | 512 / 4（按长度排序） |
| rerank `max_length` / batch / doc 截断 | 1024 / 4 / 1200 chars |
| 文本关键词 | 12 个（jieba TF-IDF + 通用停用词 + 数学词表白名单） |
| 年份规则 | 近五年→2022–2026；近三年→2024–2026；显式 20xx |
| 卷别规则 | 新高考一卷/I卷 → `新高考I卷` 或 `全国I卷`；北京/上海/天津/甲/乙 直接映射 |
| 题型规则 | 选择题→single_choice+multiple_choice；填空题→fill_blank；大题/解答题/证明题/压轴题→free_response |
| 来源规则 | 模拟→mock_exam；真题/高考→gaokao_paper（两者都提到时都保留） |

### 4.2 条件抽取与过滤效果（逐条）

15 条里只有 11 条抽出了可用的结构化条件；文本路径有 4 条因过滤后不足 8 条而回退到无过滤（记录在 `per_query_detail`）：

| id | 年份/卷别过滤 | 类型/来源过滤 | 文本命中 | 文本回退 | 向量命中 |
| --- | --- | --- | ---: | --- | ---: |
| Q01 | — | free_response；mock+gaokao | 50 | 否 | 50 |
| Q02 | 2022–2026 | mock+gaokao | 50 | 否 | 50 |
| Q03 | — | free_response；mock+gaokao | 50 | 否 | 50 |
| Q04 | — | — | 50 | 否 | 50 |
| Q05 | — | mock+gaokao | 50 | 否 | 50 |
| Q06 | 2022–2026 | 新高考I/全国I；free_response；gaokao | 50 | **是** | 27 |
| Q07 | 2024–2026 | 选择题；gaokao | 50 | **是** | 18 |
| Q08 | 2022–2026 | free_response；gaokao | 27 | 否 | 50 |
| Q09 | — | gaokao | 0 | **是**（仍 0） | 50 |
| Q10 | 2022–2026 | gaokao | 50 | 否 | 50 |
| Q16/Q17/Q19 | — | — | 50 | 否 | 50 |
| Q20 | — | free_response | 50 | 否 | 50 |
| Q18 | — | gaokao | 0 | **是**（仍 0） | 50 |

说明：Q09、Q18 的查询里没有抽出可用数学关键词（taxonomy 也未覆盖“联立方程/韦达定理/弦长公式/二级结论”），文本路径为空，最终仅靠向量路径；这也是两条查询在旧引擎上为空、现在能命中的原因。

## 5. 评测口径

- 问题集：`corpus/eval/teacher_questions.json`，sha256 `ec0ae431b3caf0f9…`，15 条真人问题，`expect_verified=15/15`（已 SQL 核验），`strict` 0 条。
- 判定代码：直接 import `tools/eval_retrieval.py` 的 `judge_query` / `compute_metrics`，**没有改判定口径**；命中 = top-8 内任一 `expect.any` 片段出现在 `excerpt`（前 400 字符）+ 来源标题中。
- 数据快照：chunk 文本与 26.7% 基线时一致；之后只新增了 `knowledge_annotations`（6045 题有 kp）并发生过 `current_knowledge_points` 表示变化（已还原）。hybrid 不依赖该列，kp 从 annotations 读，所以召回不受影响。
- 26.7% 是 2026-11-06 标注导入前旧引擎的数字（历史对照）；旧 55% 为 40 条开发者自拟，不可比。

## 6. 结果

### 6.1 总体

| 组 | Recall@8 | MRR@8 | 空结果率 | 有结果但不对 | 平均命中数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 混合无 rerank | **14/15 = 93.3%** | **0.836** | **0/15 = 0%** | 1/15 | 8.0 |
| 混合 + rerank | **14/15 = 93.3%** | **0.818** | **0/15 = 0%** | 1/15 | 8.0 |
| 旧引擎（26.7% 历史对照） | 4/15 = 26.7% | 0.180 | 2/15 = 13.3% | 9/15 | 6.93 |

### 6.2 按类别

| 类别 | 条数 | 无 rerank Recall | 无 rerank MRR | +rerank Recall | +rerank MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| 题型+知识点 | 1 | 100% | 1.000 | 100% | 1.000 |
| 年份+卷别 | 5 | 80% | 0.507 | 80% | **0.800** |
| 自然语言要求 | 9 | 100% | 1.000 | 100% | 0.808 |
| 主题词 / 教材概念 | 0 | — | — | — | — |

### 6.3 15 条逐条

| id | 类别 | 26.7% 基线 | 混合无 rerank | 混合+rerank | 备注 |
| --- | --- | --- | --- | --- | --- |
| Q01 | 自然语言要求 | miss | **hit@1** | hit@1 | 导数极值/零点题 |
| Q02 | 年份+卷别 | miss | **hit@1** | hit@1 | 立体几何二面角题 |
| Q03 | 自然语言要求 | miss | **hit@1** | hit@8 | rerank 把含“定值”的块降序 |
| Q04 | 自然语言要求 | hit@1 | hit@1 | hit@1 | 数列题 |
| Q05 | 自然语言要求 | miss | **hit@1** | hit@1 | 概率统计题 |
| Q06 | 年份+卷别 | hit@2 | hit@3 | **hit@1** | rerank 改善 |
| Q07 | 年份+卷别 | miss | hit@5 | **hit@1** | rerank 改善 |
| Q08 | 年份+卷别 | miss | **miss** | **miss** | top-8 是数列递推题，但字面不含“递推/数列求和” |
| Q09 | 题型+知识点 | empty | **hit@1** | hit@1 | 仅向量路径命中 |
| Q10 | 年份+卷别 | miss | **hit@1** | hit@1 | 零点题 |
| Q16 | 自然语言要求 | miss | **hit@1** | hit@1 | 教材数列求和内容 |
| Q17 | 自然语言要求 | miss | **hit@1** | hit@1 | 教材单调性与导数 |
| Q18 | 自然语言要求 | empty | **hit@1** | hit@1 | 圆锥曲线题 |
| Q19 | 自然语言要求 | hit@5 | **hit@1** | hit@1 | 三角函数教材 |
| Q20 | 自然语言要求 | hit@1 | **hit@1** | hit@7 | rerank 把含“不等式”的块降序 |

## 7. 失败与假阳性分析

1. **Q08 是唯一 miss（两组）**：top-1 是 2025 全国I卷数列递推题（`a_{n+1}/n = a_n/(n+1)+…`），语义上正是“递推数列大题”，但 excerpt 不含字面“递推”或“数列求和”，因此按冻结的片段式判定记为 miss。这说明**lenient 片段判定对“语义相关但字面不含期望词”的条目偏保守**；不是检索没找到相关题。**不要按这个结果回头修改期望来抬分**，应另做独立的人工/strict 核验。
2. **Reranker 的两次降序**：Q03（1→8）和 Q20（1→7）。Q03 rerank top-1 是 2014 陕西卷圆锥曲线综合题（语义相关），但被降序的块才含“定值”片段；Q20 rerank top-1 是 2017 全国III卷导数+不等式证明题（语义相关），但含“不等式”字面的块被排到第 7。说明 reranker 与“片段命中”判定不完全一致，且 15 条中 **12 条融合后已是 rank1**（天花板效应），rerank 的收益（Q06/Q07）被两次降序抵消，MRR 净降 0.018。
3. **空结果率 0**：向量路径保证每查询都有 50 个候选、融合后 top-8 始终有结果；旧引擎的两个空结果（Q09/Q18）靠向量路径解决。
4. **过滤生效但被 fallback 削弱**：Q06/Q07 文本路径过滤后不足 8 条触发无过滤回退；向量路径仍按过滤（Q06 27 条、Q07 18 条）。因此“结构化过滤”还没有被单独度量；V1.2 §13.2 的“过滤准确率”未实现。
5. **excerpt 400 字符判定**：本轮 93.3% 已远高于基线，但判定仍只看 excerpt；长块尾部的期望词可能判不中（例如 Q08 的相关块文本更长）。

## 8. 与 V1.2 阶段 4–5 验收

| 阶段 4 交付物 | 状态 |
| --- | --- |
| PostgreSQL 结构化库 | 已存在（346/12902/6981） |
| Qdrant 部署 + 向量索引 | **完成**：12902 points，dim 1024，payload 过滤字段与索引齐全 |
| Embedding / Reranker 部署 | **完成**：均 CPU 本地跑通，记录 revision/吞吐/内存 |
| 多粒度切分、父子 ID | 未实现（沿用现有 stem/answer chunk 粒度） |
| 增量索引 | **部分**：支持 `--resume` 跳过已入库 id；未做到内容哈希级增量 |

| 阶段 5 交付物 | 状态 |
| --- | --- |
| PostgreSQL 全文/trgm 检索 | 完成（pg_trgm + GIN） |
| 结构化过滤 | 完成条件抽取与 SQL/Qdrant 过滤（含 fallback；未单独度量过滤准确率） |
| Qdrant 向量检索 | 完成 |
| 候选合并 + 去重 | 完成（RRF，chunk_id 去重） |
| Reranker 精排 | 完成（Qwen3-Reranker-0.6B） |
| 检索评估 | 完成（同一 15 条，两组；Recall/MRR/空结果/分类；nDCG 等未实现） |

V1.2 未给阶段 4–5 硬性数值门槛；按交付物判断：**原型达到“可评估、可追溯”的阶段 5 要求**，混合检索把同一 15 条真人问题的 Recall@8 从 26.7% 提到 93.3%、MRR 从 0.180 提到 0.836。**但 reranker 在 15 条上没有净收益且 CPU 成本高，不能据此认为 reranker 已通过验收。**

## 9. 吞吐与延迟（评测实测）

| 环节 | 耗时 |
| --- | --- |
| 15 条 query embedding（批 32） | 3.5s（275.7 tokens/s，4.26 queries/s） |
| 文本检索（pg_trgm，每查询） | mean 0.111s / p95 0.178s |
| 向量检索（Qdrant，每查询） | mean 0.032s / p95 0.042s |
| 文档取回 + 融合 | <0.01s |
| **Reranker（40 候选/查询）** | **mean 82.7s / p95 109.6s**（600 pairs / 1239s = 0.48 pairs/s） |
| 单查询总延迟 | mean 83.0s / p95 109.8s；其中 rerank 占 99.7% |

Reranker 是绝对瓶颈；15 条评测因此耗时约 21 分钟。若生产默认开 rerank，按当前 CPU 不可接受。

## 10. 与旧数字的关系

- **26.7% → 93.3%**：同一 15 条、同一判定、同一 chunk 快照；差异来自新检索路径（向量+trgm+RRF），不是调参美化。混合路径未改旧 `knowledge_search`。
- **55%**：旧 40 条开发者自拟问题集的数字，问题集/语料/口径均不同，**不可比，不得并列引用**。
- `strict` 仍然 0 条：本版仍不能回答“是不是找到了教师指定的那一道/那一条”；93.3% 是 lenient 口径。

## 11. 复现

```powershell
# 1) Qdrant
docker run -d --name chilon-qdrant -p 6333:6333 -p 6334:6334 -v chilon-qdrant-data:/qdrant/storage qdrant/qdrant

# 2) PG 连接（密码从容器 env 取，不落盘）
$c = docker inspect chilon-pg-corpus | ConvertFrom-Json
$map = @{}; foreach ($e in $c.Config.Env) { $i = $e.IndexOf('='); if ($i -gt 0) { $map[$e.Substring(0,$i)] = $e.Substring($i+1) } }
$env:CHILON_TEST_DATABASE_URL = "postgresql+psycopg://postgres:$($map['POSTGRES_PASSWORD'])@127.0.0.1:55495/chilon"

# 3) 重建索引（模型已下载时 --skip-download；可 --resume 断点续建）
.\.venv\Scripts\python.exe tools\build_hybrid_index.py --create-only --recreate --collection chilon_chunks_qwen3_embedding_0_6b_v1
.\.venv\Scripts\python.exe tools\build_hybrid_index.py --no-create --resume --shard-count 3 --shard-index 0 --threads 6 --collection chilon_chunks_qwen3_embedding_0_6b_v1 --skip-download --manifest var\retrieval\index_manifest_final0.json
#   （shard-index 1、2 同理；完成后 merge）
.\.venv\Scripts\python.exe tools\merge_index_manifests.py --collection chilon_chunks_qwen3_embedding_0_6b_v1 --manifests var\retrieval\index_manifest_final0.json ... --out var\retrieval\index_manifest.json --embedding-revision <sha>

# 4) 评测（15 条，两组）
.\.venv\Scripts\python.exe tools\eval_hybrid.py --out-prefix var\retrieval\hybrid_eval_2026-11-06

# 4b) 只跑无 rerank 组（约 1–2 分钟；--skip-rerank 不加载 reranker 模型）
.\.venv\Scripts\python.exe tools\eval_hybrid.py --skip-rerank --skip-download --collection chilon_chunks_qwen3_embedding_0_6b_v1 --out-prefix var\retrieval\hybrid_eval_no_rerank_2026-11-06
#   → 输出 hybrid_eval_no_rerank_2026-11-06.json/.md；结构只含 no_rerank group，
#     Recall@8=14/15、MRR=0.836、空结果=0/15，与完整运行的无 rerank 组一致。
```

## 12. 产物

| 文件 | 内容 |
| --- | --- |
| `var/retrieval/index_manifest.json` | 索引 manifest（collection/dim/points/模型 revision/吞吐/内存/分片） |
| `var/retrieval/index_build_*.log` | 各阶段建库日志（含 OOM 与 resume） |
| `var/retrieval/hybrid_eval_2026-11-06.json` | 两组完整结果（逐条 top-8、条件、耗时、对比基线） |
| `var/retrieval/hybrid_eval_2026-11-06.md` | 自动生成的人读摘要 |
| `var/retrieval/hybrid_eval.log` | 评测运行日志 |
| `backend/app/services/hybrid_retrieval.py` | 混合检索原型模块（新） |
| `tools/build_hybrid_index.py` / `tools/eval_hybrid.py` / `tools/merge_index_manifests.py` | 建库 / 评测 / manifest 合并脚本（新） |

## 13. 限制与下一步建议

1. **reranker 暂不应默认开**：15 条上 Recall 无增益、MRR 略降、成本 83s/query。下一步应在更大/更难的候选集上测 nDCG，并考虑 GPU/ONNX/int8 或只对 top-20 重排。
2. **判定口径**：Q08 暴露“片段式 lenient 判定”对语义相关但字面不含期望词的条目偏保守。建议补 strict target 或题号级判定，并用独立人工核验，**不要按本次数字回改期望**。
3. **过滤准确率**：条件抽取已实现但被文本 fallback 部分绕过；建议单独测“年份/卷别/题型过滤是否正确生效”（V1.2 §13.2）。
4. **索引效率**：CPU fp32 下全量 12902 chunks 约 2h；建议 ONNX/int8/多进程稳定化、增量索引（内容哈希）、父子块/多粒度。
5. **数据口径**：hybrid 的 kp 来自 `knowledge_annotations`（不依赖 `current_knowledge_points`）；旧 26.7% 仅作历史对照；后续标注更新后需重建索引并重测。
6. 本版未覆盖：nDCG@K、过滤准确率、来源完整率、误召回率（V1.2 §13.2 的其余指标）。

## 14. 版本记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-11-06 | 首版：Qdrant 全量索引（12902 chunks）+ 混合检索原型 + 15 条两组评测；Recall@8 26.7%→93.3%（无 rerank 与 +rerank 相同），MRR 0.180→0.836/0.818；记录 CPU 吞吐、内存、OOM 恢复、reranker 无净收益；未改旧检索实现、未 commit。 |
