"""Evaluate the hybrid retrieval prototype on the frozen 15-query teacher set.

Two groups are reported, with the same question set and the same judging code as
``tools/eval_retrieval.py`` (the old eval口径 is not changed):

* hybrid without rerank: pg_trgm lexical + Qdrant vector, RRF fusion, top-8;
* hybrid + Qwen3-Reranker-0.6B: rerank top-N fused candidates, top-8.

All parameters are read from ``backend/app/services/hybrid_retrieval.CONFIG`` and
recorded in the report; they are fixed before this run.

Usage:
    .\\.venv\\Scripts\\python.exe tools\\eval_hybrid.py
    .\\.venv\\Scripts\\python.exe tools\\eval_hybrid.py --limit-queries 1   # smoke
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.services import hybrid_retrieval as hr  # noqa: E402
import eval_retrieval as legacy_eval  # noqa: E402

DEFAULT_QUESTIONS = ROOT / "corpus" / "eval" / "teacher_questions.json"
DEFAULT_OUT_PREFIX = ROOT / "var" / "retrieval" / "hybrid_eval_2026-11-06"
DEFAULT_EMBEDDING_DIR = ROOT / "var" / "retrieval" / "models" / "Qwen3-Embedding-0.6B"
DEFAULT_RERANKER_DIR = ROOT / "var" / "retrieval" / "models" / "Qwen3-Reranker-0.6B"
DEFAULT_HF_CACHE = ROOT / "var" / "retrieval" / "hf_cache"
BASELINE_JSON = ROOT / "var" / "retrieval" / "baseline_2026-11-06.json"

RERANK_REPO = "Qwen/Qwen3-Reranker-0.6B"
COLLECTION = "chilon_chunks_qwen3_embedding_0_6b_v1"


def ensure_model(repo: str, model_dir: Path, cache_dir: Path) -> tuple[Path, str | None]:
    from huggingface_hub import HfApi, snapshot_download

    revision: str | None = None
    try:
        revision = getattr(HfApi().model_info(repo, revision="main"), "sha", None)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: could not read upstream revision of {repo}: {exc}")
    if (model_dir / "config.json").exists():
        print(f"model already present: {hr._rel(model_dir)}")
        return model_dir, revision
    model_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"downloading {repo} -> {hr._rel(model_dir)} (HF direct) ...")
    started = time.perf_counter()
    snapshot_download(repo_id=repo, local_dir=str(model_dir), cache_dir=str(cache_dir))
    print(f"   downloaded in {time.perf_counter() - started:.1f}s")
    return model_dir, revision


def connect(dsn: str):
    import psycopg  # type: ignore

    return psycopg.connect(dsn.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=10)


def _category_metrics(rows: list[dict], k: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for category in legacy_eval.CATEGORIES:
        subset = [row for row in rows if row["category"] == category]
        if subset:
            out[category] = legacy_eval.compute_metrics(subset, k)
    return out


def _score_baseline(rows: list[dict], baseline: dict | None) -> dict | None:
    if not baseline:
        return None
    old = {row["id"]: row for row in baseline.get("queries", [])}
    comparison = []
    for row in rows:
        old_row = old.get(row["id"], {})
        comparison.append(
            {
                "id": row["id"],
                "baseline_status": old_row.get("status"),
                "baseline_rank": old_row.get("lenient_rank"),
                "new_status": row["status"],
                "new_rank": row["lenient_rank"],
            }
        )
    return {"baseline_runs_at": baseline.get("generated_at"), "per_query": comparison}


def _hit_dump(row: dict, limit: int = 8) -> list[dict]:
    out = []
    for hit in row.get("top_hits", [])[:limit]:
        out.append(
            {
                "rank": hit.get("rank"),
                "chunk_id": hit.get("chunk_id"),
                "question_id": hit.get("question_id"),
                "source_type": hit.get("source_type"),
                "year": hit.get("year"),
                "paper": hit.get("source_paper"),
                "title": hit.get("source_title"),
                "knowledge_points": hit.get("knowledge_points"),
                "excerpt": (hit.get("excerpt") or "")[:140],
                "rrf_score": hit.get("rrf_score"),
                "rerank_score": hit.get("rerank_score"),
                "from": hit.get("rrf_sources"),
            }
        )
    return out


def render_summary_md(doc: dict) -> str:
    lines = ["# 混合检索评测（自动生成）", ""]
    lines.append(f"- 生成时间：{doc['generated_at']}")
    lines.append(f"- 问题集：`{doc['question_set']['path']}`（{doc['question_set']['scored']} 条）")
    lines.append(f"- 配置：{json.dumps(doc['config'], ensure_ascii=False)}")
    lines.append(f"- 索引：`{doc['index']['collection']}`，{doc['index']['points']} points")
    lines.append("")
    for group_key, default_label in (
        ("no_rerank", "混合无 rerank（pg_trgm + Qdrant + RRF）"),
        ("rerank", "混合 + Qwen3-Reranker-0.6B"),
    ):
        # --skip-rerank only produces the no_rerank group; render what exists.
        group = doc["groups"].get(group_key)
        if not group:
            continue
        metrics = group["metrics"]
        lines.append(f"## {group.get('label') or default_label}")
        lines.append("")
        lines.append(f"- Recall@8：{metrics['found']}/{metrics['queries']} = {metrics['recall_at_k']:.1%}")
        lines.append(f"- MRR@8：{metrics['mrr']:.3f}")
        lines.append(f"- 空结果：{metrics['empty']}/{metrics['queries']} = {metrics['empty_rate']:.1%}")
        lines.append(f"- 有结果但不对：{metrics['hits_but_miss']}/{metrics['queries']}")
        lines.append("")
        lines.append("| 类别 | 条数 | Recall@8 | MRR@8 | 空结果 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for category, cat in group["by_category"].items():
            lines.append(
                f"| {category} | {cat['queries']} | {cat['recall_at_k']:.1%} | {cat['mrr']:.3f} | {cat['empty_rate']:.1%} |"
            )
        lines.append("")
        lines.append("| id | 状态 | 排名 | 命中数 | 前 3 命中 |")
        lines.append("| --- | --- | ---: | ---: | --- |")
        for row in group["queries"]:
            tops = " / ".join(
                f"{hit['source_type']}:{hit['year']}:{(hit['title'] or '')[:18]}"
                for hit in row["top_hits"][:3]
            )
            lines.append(
                f"| {row['id']} | {row['status']} | {row['lenient_rank'] or '—'} | {row['hits']} | {tops} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate hybrid retrieval on the 15 frozen questions")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--database-url", default=os.environ.get("CHILON_TEST_DATABASE_URL"))
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--collection", default=COLLECTION)
    parser.add_argument("--embedding-model-dir", type=Path, default=DEFAULT_EMBEDDING_DIR)
    parser.add_argument("--reranker-model-dir", type=Path, default=DEFAULT_RERANKER_DIR)
    parser.add_argument("--hf-cache", type=Path, default=DEFAULT_HF_CACHE)
    parser.add_argument("--out-prefix", type=Path, default=DEFAULT_OUT_PREFIX)
    parser.add_argument("--kp-vocab", default=hr.DEFAULT_KP_VOCAB, help="vault 知识点词表.md（只读）")
    parser.add_argument("--limit-queries", type=int, default=0, help="0 = all 15")
    parser.add_argument("--skip-rerank", action="store_true", help="only run the no-rerank group")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument(
        "--api",
        action="store_true",
        help="use Qwen API for query embedding + rerank (qwen3.7-text-embedding / qwen3.7-text-rerank)",
    )
    parser.add_argument("--api-dim", type=int, default=1024)
    parser.add_argument("--api-embedding-model", default=None)
    parser.add_argument("--api-rerank-model", default=None)
    parser.add_argument(
        "--api-query-instruction",
        action="store_true",
        help="prepend the local instruction template to API queries (default: raw query; measured worse on 15 queries)",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("CHILON_TEST_DATABASE_URL is not set (or pass --database-url)", file=sys.stderr)
        return 2

    # question set + judging口径 come from the existing eval module, unchanged
    dataset = legacy_eval.load_dataset(args.questions)
    scored, excluded = legacy_eval.select_queries(dataset, include_untrusted=False)
    if not scored:
        print("no judgeable questions", file=sys.stderr)
        return 3
    if args.limit_queries:
        scored = scored[: args.limit_queries]
    print(f"questions: {len(scored)} (excluded {len(excluded)})")

    # models
    embed_dir = rerank_dir = None
    embed_rev = rerank_rev = None
    if not args.api:
        embed_dir, embed_rev = (
            (args.embedding_model_dir, None)
            if args.skip_download
            else ensure_model("Qwen/Qwen3-Embedding-0.6B", args.embedding_model_dir, args.hf_cache)
        )
        if not args.skip_rerank:
            rerank_dir, rerank_rev = (
                (args.reranker_model_dir, None)
                if args.skip_download
                else ensure_model(RERANK_REPO, args.reranker_model_dir, args.hf_cache)
            )

    from qdrant_client import QdrantClient  # type: ignore

    client = QdrantClient(url=args.qdrant_url, timeout=120)
    collection_info = client.get_collection(args.collection)
    points = collection_info.points_count
    print(f"collection {args.collection}: {points} points")

    queries = [query["text"] for query in scored]
    if args.api:
        from qwen_api import embed_texts as api_embed_texts

        api_queries = (
            [hr.embedding_query_text(query) for query in queries]
            if args.api_query_instruction
            else queries
        )
        print("embedding queries via Qwen API ...")
        t0 = time.perf_counter()
        query_vectors, embed_stats = api_embed_texts(api_queries)
        embedding_load_s = 0.0
        dim = len(query_vectors[0]) if query_vectors else args.api_dim
        print(
            f"   dim={dim} query_template="
            f"{'instruction' if args.api_query_instruction else 'raw'} api={embed_stats}"
        )
    else:
        print("loading embedding model ...")
        t0 = time.perf_counter()
        embedding_model, embedding_tokenizer, dim = hr.load_embedding_model(embed_dir)  # type: ignore[arg-type]
        embedding_load_s = time.perf_counter() - t0
        print(f"   dim={dim} load={embedding_load_s:.1f}s rss={hr._rss_mb()}MB")
        query_vectors, embed_stats = hr.embed_queries(embedding_model, embedding_tokenizer, queries)
        print(f"query embedding: {embed_stats}")
        # free the embedding model before loading the reranker (CPU RAM is shared with
        # other processes on this machine; two 0.6B fp32 models at once is unnecessary)
        import gc

        del embedding_model, embedding_tokenizer
        gc.collect()

    reranker_model = reranker_tokenizer = None
    reranker_load_s = None
    if not args.skip_rerank:
        if args.api:
            reranker_model = "api"
            reranker_load_s = 0.0
        else:
            print("loading reranker model ...")
            t0 = time.perf_counter()
            reranker_model, reranker_tokenizer = hr.load_reranker(rerank_dir)  # type: ignore[arg-type]
            reranker_load_s = time.perf_counter() - t0
            print(f"   load={reranker_load_s:.1f}s rss={hr._rss_mb()}MB")

    conn = connect(args.database_url)
    # Knowledge points: read from knowledge_annotations (SSOT), not from
    # knowledge_questions.current_knowledge_points (changed during the annotation import).
    kp_name_map = hr.load_kp_name_map(getattr(args, "kp_vocab", hr.DEFAULT_KP_VOCAB))
    annotations = hr.fetch_annotation_points(conn, kp_name_map)
    print(f"knowledge points from knowledge_annotations: {len(annotations)} questions")
    rows_no_rerank: list[dict] = []
    rows_rerank: list[dict] = []
    details: list[dict] = []
    timings: list[dict] = []
    rerank_stats_all: list[dict] = []
    try:
        for index, query in enumerate(scored):
            started = time.perf_counter()
            conditions = hr.extract_conditions(query["text"])
            t_extract = time.perf_counter() - started

            t0 = time.perf_counter()
            text_hits = hr.text_search(conn, query["text"], conditions, use_filters=True)
            text_fallback = False
            if len(text_hits) < hr.CONFIG["min_filtered_hits"]:
                text_hits = hr.text_search(conn, query["text"], conditions, use_filters=False)
                text_fallback = True
            text_s = time.perf_counter() - t0

            t0 = time.perf_counter()
            vector_hits = hr.vector_search(
                client,
                args.collection,
                query_vectors[index],
                conditions=conditions,
                use_filters=True,
            )
            vector_fallback = False
            if len(vector_hits) < hr.CONFIG["min_filtered_hits"]:
                vector_hits = hr.vector_search(
                    client, args.collection, query_vectors[index], conditions=conditions, use_filters=False
                )
                vector_fallback = True
            vector_s = time.perf_counter() - t0

            t0 = time.perf_counter()
            ids = [hit["chunk_id"] for hit in vector_hits if hit.get("chunk_id")]
            hydrated = hr.fetch_chunks(conn, ids)
            vector_full = []
            for hit in vector_hits:
                full = hydrated.get(hit["chunk_id"])
                if full is None:
                    continue
                merged = dict(full)
                merged["vector_score"] = hit.get("vector_score")
                merged["from_vector_rank"] = vector_hits.index(hit) + 1
                vector_full.append(merged)
            hydrate_s = time.perf_counter() - t0

            t0 = time.perf_counter()
            fused = hr.rrf_fuse([text_hits, vector_full])
            hr.attach_annotation_points(fused, annotations)
            fuse_s = time.perf_counter() - t0

            no_rerank_hits = fused[: hr.CONFIG["final_k"]]
            row_no = legacy_eval.judge_query(no_rerank_hits, query, hr.CONFIG["final_k"])
            row_no["hits"] = len(no_rerank_hits)
            rows_no_rerank.append(row_no)

            rerank_s = None
            row_rr = None
            if reranker_model is not None:
                t0 = time.perf_counter()
                candidates = fused[: hr.CONFIG["rerank_candidates"]]
                docs = [
                    hr.embedding_text(hit)[: hr.CONFIG["rerank_doc_chars"]] for hit in candidates
                ]
                if args.api:
                    import qwen_api

                    scores, rerank_stats = qwen_api.rerank(
                        query["text"], docs, model=args.api_rerank_model
                    )
                else:
                    scores, rerank_stats = hr.rerank_scores(
                        reranker_model, reranker_tokenizer, query["text"], docs
                    )
                rerank_stats_all.append(rerank_stats)
                ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
                rerank_hits = []
                for rank, (hit, score) in enumerate(ranked[: hr.CONFIG["final_k"]], 1):
                    enriched = dict(hit)
                    enriched["rerank_score"] = round(float(score), 6)
                    rerank_hits.append(enriched)
                row_rr = legacy_eval.judge_query(rerank_hits, query, hr.CONFIG["final_k"])
                row_rr["hits"] = len(rerank_hits)
                rows_rerank.append(row_rr)
                rerank_s = time.perf_counter() - t0

            total_s = time.perf_counter() - started
            timings.append(
                {
                    "extract": t_extract,
                    "text": text_s,
                    "vector": vector_s,
                    "hydrate": hydrate_s,
                    "fuse": fuse_s,
                    "rerank": rerank_s,
                    "total": total_s,
                }
            )
            details.append(
                {
                    "id": query["id"],
                    "category": query["category"],
                    "text": query["text"],
                    "conditions": conditions,
                    "text_hits": len(text_hits),
                    "text_fallback_unfiltered": text_fallback,
                    "vector_hits": len(vector_hits),
                    "vector_fallback_unfiltered": vector_fallback,
                    "fused_candidates": len(fused),
                    "no_rerank": {
                        "status": row_no["status"],
                        "lenient_rank": row_no["lenient_rank"],
                        "top_hits": _hit_dump(row_no),
                    },
                    "rerank": (
                        {
                            "status": row_rr["status"],
                            "lenient_rank": row_rr["lenient_rank"],
                            "top_hits": _hit_dump(row_rr),
                        }
                        if row_rr is not None
                        else None
                    ),
                    "timing": {key: round(value, 4) if value is not None else None for key, value in timings[-1].items()},
                }
            )
            rank_note = (
                f"rank={row_no['lenient_rank']}" if row_no["lenient_rank"] else row_no["status"]
            )
            rr_note = (
                (
                    f"rank={row_rr['lenient_rank']}"
                    if row_rr["lenient_rank"]
                    else row_rr["status"]
                )
                if row_rr is not None
                else "skipped"
            )
            print(
                f"[{index + 1}/{len(scored)}] {query['id']} no_rerank={rank_note} rerank={rr_note} "
                f"(text={len(text_hits)}, vec={len(vector_hits)}, fused={len(fused)})"
            )
    finally:
        conn.close()

    k = hr.CONFIG["final_k"]
    groups: dict[str, dict] = {
        "no_rerank": {
            "label": "混合无 rerank（pg_trgm + Qdrant + RRF）",
            "metrics": legacy_eval.compute_metrics(rows_no_rerank, k),
            "by_category": _category_metrics(rows_no_rerank, k),
            "queries": [
                {
                    "id": row["id"],
                    "category": row["category"],
                    "status": row["status"],
                    "lenient_rank": row["lenient_rank"],
                    "hits": row["hits"],
                    "top_hits": _hit_dump(row),
                }
                for row in rows_no_rerank
            ],
        }
    }
    if not args.skip_rerank:
        groups["rerank"] = {
            "label": (
                "混合 + qwen3.7-text-rerank（API）"
                if args.api
                else "混合 + Qwen3-Reranker-0.6B"
            ),
            "metrics": legacy_eval.compute_metrics(rows_rerank, k),
            "by_category": _category_metrics(rows_rerank, k),
            "queries": [
                {
                    "id": row["id"],
                    "category": row["category"],
                    "status": row["status"],
                    "lenient_rank": row["lenient_rank"],
                    "hits": row["hits"],
                    "top_hits": _hit_dump(row),
                }
                for row in rows_rerank
            ],
        }

    baseline = None
    if BASELINE_JSON.exists():
        baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    no_rerank_rows = groups["no_rerank"]["queries"]
    comparison = {
        "baseline_report": hr._rel(BASELINE_JSON) if BASELINE_JSON.exists() else None,
        "baseline_metrics": baseline["metrics"] if baseline else None,
        "no_rerank_vs_baseline": _score_baseline(no_rerank_rows, baseline),
    }
    if "rerank" in groups:
        comparison["rerank_vs_baseline"] = _score_baseline(groups["rerank"]["queries"], baseline)
        comparison["rerank_vs_no_rerank"] = [
            {
                "id": rr["id"],
                "no_rerank_status": nr["status"],
                "no_rerank_rank": nr["lenient_rank"],
                "rerank_status": rr["status"],
                "rerank_rank": rr["lenient_rank"],
            }
            for nr, rr in zip(groups["no_rerank"]["queries"], groups["rerank"]["queries"])
        ]

    def _timing_summary(key: str) -> dict:
        values = [item[key] for item in timings if item.get(key) is not None]
        return {
            "mean_s": round(sum(values) / len(values), 3) if values else None,
            "p50_s": round(hr.percentile(values, 50), 3) if values else None,
            "p95_s": round(hr.percentile(values, 95), 3) if values else None,
        }

    doc = {
        "schema": "chilon-hybrid-eval/v1",
        "generated_at": hr.now_iso(),
        "git_commit": hr._git_commit(),
        "question_set": {
            "path": hr._rel(args.questions),
            "sha256": dataset["sha256"],
            "scored": len(scored),
            "excluded": excluded,
        },
        "data_policy": {
            "knowledge_points": "knowledge_annotations (active rows)",
            "current_knowledge_points_column_used": False,
            "note": "2026-11-06 annotation import changed current_knowledge_points to kp_id arrays; hybrid prototype reads annotations instead. Baseline 26.7% was measured before that import and is kept only as a historical comparison.",
            "baseline_snapshot_relation": "chunk text unchanged; annotation layer added after the 26.7% baseline run",
        },
        "config": hr.CONFIG,
        "index": {
            "collection": args.collection,
            "points": points,
            "dim": dim,
            "qdrant_url": args.qdrant_url,
        },
        "models": {
            "embedding": (
                {
                    "provider": "dashscope",
                    "model": args.api_embedding_model or "qwen3.7-text-embedding",
                    "dim": dim,
                    "load_seconds": None,
                }
                if args.api
                else {
                    "repo": "Qwen/Qwen3-Embedding-0.6B",
                    "revision": embed_rev,
                    "dim": dim,
                    "load_seconds": round(embedding_load_s, 2),
                }
            ),
            "reranker": (
                {
                    "provider": "dashscope",
                    "model": args.api_rerank_model or "qwen3.7-text-rerank",
                    "load_seconds": None,
                }
                if args.api and reranker_model is not None
                else (
                    {
                        "repo": RERANK_REPO,
                        "revision": rerank_rev,
                        "load_seconds": round(reranker_load_s, 2) if reranker_load_s else None,
                    }
                    if reranker_model is not None
                    else None
                )
            ),
        },
        "throughput": {
            "query_embedding": embed_stats,
            "rerank": {
                "batches": len(rerank_stats_all),
                "pairs": sum(item["pairs"] for item in rerank_stats_all),
                "seconds": round(sum(item["seconds"] for item in rerank_stats_all), 3),
                "pairs_per_second": (
                    round(
                        sum(item["pairs"] for item in rerank_stats_all)
                        / sum(item["seconds"] for item in rerank_stats_all),
                        2,
                    )
                    if rerank_stats_all
                    else None
                ),
            },
            "per_query": {
                key: _timing_summary(key)
                for key in ("extract", "text", "vector", "hydrate", "fuse", "rerank", "total")
            },
        },
        "groups": groups,
        "comparison": comparison,
        "per_query_detail": details,
    }

    json_path = Path(str(args.out_prefix) + ".json")
    md_path = Path(str(args.out_prefix) + ".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_summary_md(doc) + "\n", encoding="utf-8")

    print()
    for key in ("no_rerank", "rerank"):
        if key not in groups:
            continue
        metrics = groups[key]["metrics"]
        print(
            f"{groups[key]['label']}: Recall@8={metrics['found']}/{metrics['queries']}="
            f"{metrics['recall_at_k']:.1%} MRR={metrics['mrr']:.3f} "
            f"empty={metrics['empty']}/{metrics['queries']}={metrics['empty_rate']:.1%} "
            f"hits_but_miss={metrics['hits_but_miss']}"
        )
    print(f"timing per query: {doc['throughput']['per_query']['total']}")
    print(f"rerank: {doc['throughput']['rerank']}")
    print(f"JSON: {hr._rel(json_path)}")
    print(f"MD  : {hr._rel(md_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
