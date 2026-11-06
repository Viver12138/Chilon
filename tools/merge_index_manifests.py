"""Merge per-shard Qdrant index manifests into one final manifest.

The full corpus build is run as N parallel shards (one process per shard, all
upserting into the same Qdrant collection).  Each shard writes its own
``index_manifest_shardN.json``; this script aggregates timing / memory /
throughput into ``var/retrieval/index_manifest.json`` and reads the real point
count from Qdrant.

Usage:
    .\\.venv\\Scripts\\python.exe tools\\merge_index_manifests.py `
        --collection chilon_chunks_qwen3_embedding_0_6b_v1 `
        --manifests var\\retrieval\\index_manifest_shard0.json var\\retrieval\\index_manifest_shard1.json var\\retrieval\\index_manifest_shard2.json `
        --out var\\retrieval\\index_manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services import hybrid_retrieval as hr  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge shard index manifests")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--manifests", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "var" / "retrieval" / "index_manifest.json")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--embedding-revision", default=None, help="upstream model revision (sha)")
    args = parser.parse_args()

    from qdrant_client import QdrantClient  # type: ignore

    client = QdrantClient(url=args.qdrant_url, timeout=120)
    info = client.get_collection(args.collection)
    total_points = info.points_count

    shards = [json.loads(path.read_text(encoding="utf-8")) for path in args.manifests]
    embed_seconds = sum(shard["timing"]["embed_seconds"] for shard in shards)
    tokens = sum(shard["timing"]["tokens_embedded"] for shard in shards)
    chunks = sum(shard["database"]["chunks_embedded"] for shard in shards)
    upsert_seconds = sum(shard["timing"]["upsert_seconds"] for shard in shards)
    total_seconds = sum(shard["timing"]["total_seconds"] for shard in shards)
    wall_seconds = max(shard["timing"]["total_seconds"] for shard in shards)
    peak_rss = max((shard["memory"].get("peak_rss_mb") or 0) for shard in shards)
    first = shards[0]

    merged = {
        "schema": "chilon-hybrid-index/v1",
        "created_at": hr.now_iso(),
        "git_commit": hr._git_commit(),
        "build_mode": f"{len(shards)} parallel shards",
        "note": (
            "The full index has 12902 points; this manifest's timing/throughput covers the "
            "final resume run (last shard batch). Earlier build phases and OOM/recovery are "
            "in var/retrieval/index_build_*.log."
        ),
        "database": {**first["database"], "chunks_embedded": chunks},
        "collection": {
            **first["collection"],
            "name": args.collection,
            "points": total_points,
            "shard": {"count": len(shards), "index": None},
        },
        "knowledge_points": first["knowledge_points"],
        "embedding": {
            **first["embedding"],
            "revision": args.embedding_revision or first["embedding"].get("revision"),
        },
        "versions": first["versions"],
        "timing": {
            "embed_seconds": round(embed_seconds, 1),
            "upsert_seconds": round(upsert_seconds, 1),
            "sum_of_shard_total_seconds": round(total_seconds, 1),
            "wall_seconds": round(wall_seconds, 1),
            "chunks_per_second": round(chunks / embed_seconds, 2) if embed_seconds else None,
            "tokens_per_second": round(tokens / embed_seconds, 1) if embed_seconds else None,
            "aggregate_chunks_per_second": round(chunks / wall_seconds, 3) if wall_seconds else None,
            "aggregate_tokens_per_second": round(tokens / wall_seconds, 1) if wall_seconds else None,
            "tokens_embedded": tokens,
            "chunks_embedded": chunks,
        },
        "memory": {
            "peak_rss_per_shard_mb": round(peak_rss, 1),
            "shards": [shard["memory"].get("peak_rss_mb") for shard in shards],
        },
        "shards": [
            {
                "manifest": hr._rel(path),
                "chunks": shard["database"]["chunks_embedded"],
                "embed_seconds": shard["timing"]["embed_seconds"],
                "tokens": shard["timing"]["tokens_embedded"],
                "torch_threads": shard["embedding"].get("torch_threads"),
                "peak_rss_mb": shard["memory"].get("peak_rss_mb"),
            }
            for path, shard in zip(args.manifests, shards)
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"merged {len(shards)} shards -> {hr._rel(args.out)}")
    print(f"points={total_points} chunks={chunks} tokens={tokens} "
          f"embed_s={merged['timing']['embed_seconds']} "
          f"chunks/s={merged['timing']['chunks_per_second']} "
          f"tokens/s={merged['timing']['tokens_per_second']} "
          f"peak_rss/shard={merged['memory']['peak_rss_per_shard_mb']}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
