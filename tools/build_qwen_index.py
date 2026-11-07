"""Build a Qdrant index for the Chilon corpus with the Qwen API embedding.

Reads chunks from PostgreSQL (SSOT), composes the same embedding input as the
local CPU build (V1.2 §9.3), calls DashScope ``qwen3.7-text-embedding``, and
upserts vectors + filter metadata into a **new** collection.  The local
Qwen3-Embedding collection is left untouched, so the two indexes can be A/B'd.

Usage (from repo root, .venv interpreter):

    .\\.venv\\Scripts\\python.exe tools\\build_qwen_index.py --recreate
    .\\.venv\\Scripts\\python.exe tools\\build_qwen_index.py --limit 256 --collection chilon_qwen_api_smoke --recreate
    .\\.venv\\Scripts\\python.exe tools\\build_qwen_index.py --resume

The API key comes from ``.env`` via ``backend/app/settings.py``.  The index is a
derived artefact and can be rebuilt from PostgreSQL at any time.
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
import build_hybrid_index as local_build  # noqa: E402
import qwen_api  # noqa: E402

DEFAULT_COLLECTION = "chilon_chunks_qwen3_7_text_embedding_v1"
DEFAULT_MANIFEST = ROOT / "var" / "retrieval" / "index_manifest_qwen3_7_api.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Qdrant index via Qwen embedding API")
    parser.add_argument("--database-url", default=os.environ.get("CHILON_TEST_DATABASE_URL"))
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dim", type=int, default=qwen_api.embedding_dimension())
    parser.add_argument("--batch-size", type=int, default=qwen_api.DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="0 = all chunks (smoke otherwise)")
    parser.add_argument("--kp-vocab", default=hr.DEFAULT_KP_VOCAB)
    parser.add_argument("--recreate", action="store_true", help="drop and recreate the collection")
    parser.add_argument("--resume", action="store_true", help="skip chunk ids already indexed")
    args = parser.parse_args()

    if not args.database_url:
        print("CHILON_TEST_DATABASE_URL is not set (or pass --database-url)", file=sys.stderr)
        return 2

    from qdrant_client import QdrantClient  # type: ignore
    from qdrant_client import models as qm  # type: ignore

    started_total = time.perf_counter()

    # 1) chunks + annotations from PostgreSQL (same source as the local build)
    print("connecting to PostgreSQL ...")
    conn = local_build.connect(args.database_url)
    try:
        counts = local_build.corpus_counts(conn)
        fetch_started = time.perf_counter()
        chunks = hr.fetch_all_chunks(conn)
        kp_name_map = hr.load_kp_name_map(args.kp_vocab) if args.kp_vocab else {}
        annotations = hr.fetch_annotation_points(conn, kp_name_map)
        hr.attach_annotation_points(chunks, annotations)
        fetch_seconds = time.perf_counter() - fetch_started
    finally:
        conn.close()
    if args.limit:
        chunks = chunks[: args.limit]
    texts = [hr.embedding_text(hit) for hit in chunks]
    print(f"chunks: {len(chunks)} (DB: {counts})  fetch={fetch_seconds:.1f}s")

    # 2) collection
    client = QdrantClient(url=args.qdrant_url, timeout=120)
    exists = local_build.collection_exists(client, args.collection)
    existing_ids: set[str] = set()
    if exists and args.resume:
        existing_ids = local_build.scroll_ids(client, args.collection)
        pairs = [(hit, text) for hit, text in zip(chunks, texts) if hit["chunk_id"] not in existing_ids]
        chunks = [pair[0] for pair in pairs]
        texts = [pair[1] for pair in pairs]
        print(f"resume: {len(existing_ids)} points exist, remaining {len(chunks)}", flush=True)
    if not exists:
        local_build.create_collection(client, args.collection, args.dim)
        print(f"collection {args.collection!r} created (dim={args.dim})", flush=True)
    elif not args.resume:
        if not args.recreate:
            print(
                f"collection {args.collection!r} already exists; pass --recreate or --resume",
                file=sys.stderr,
            )
            return 3
        client.delete_collection(args.collection)
        local_build.create_collection(client, args.collection, args.dim)
        print(f"collection {args.collection!r} recreated (dim={args.dim})", flush=True)

    # 3) embed + upsert
    embedded = 0
    upserted = 0
    requests = 0
    tokens_total = 0
    embed_seconds = 0.0
    upsert_seconds = 0.0
    progress_started = time.perf_counter()
    pending: list = []
    point_batch = 256

    def flush(points: list) -> int:
        nonlocal upsert_seconds
        if not points:
            return 0
        started = time.perf_counter()
        client.upsert(collection_name=args.collection, points=points, wait=False)
        upsert_seconds += time.perf_counter() - started
        return len(points)

    for start in range(0, len(chunks), args.batch_size):
        batch_chunks = chunks[start : start + args.batch_size]
        batch_texts = texts[start : start + args.batch_size]
        vectors, stats = qwen_api.embed_texts(
            batch_texts, dimension=args.dim, batch_size=args.batch_size
        )
        requests += int(stats["requests"])
        tokens_total += int(stats["input_tokens"])
        embed_seconds += float(stats["seconds"])
        for hit, vector in zip(batch_chunks, vectors):
            pending.append(
                qm.PointStruct(
                    id=hit["chunk_id"],
                    vector=vector,
                    payload={
                        "chunk_id": hit["chunk_id"],
                        "question_id": hit["question_id"],
                        "source_id": hit["source_id"],
                        "source_type": hit["source_type"],
                        "title": hit["source_title"],
                        "year": hit["year"],
                        "paper": hit["source_paper"],
                        "question_no": hit["question_no"],
                        "question_type": hit["question_type"],
                        "knowledge_points": hit["knowledge_points"],
                        "locator": hit["locator"],
                    },
                )
            )
            if len(pending) >= point_batch:
                upserted += flush(pending)
                pending = []
        embedded += len(batch_chunks)
        if embedded % 256 < args.batch_size or embedded >= len(chunks):
            elapsed = time.perf_counter() - progress_started
            rate = embedded / elapsed if elapsed else 0
            eta = (len(chunks) - embedded) / rate if rate else 0
            print(
                f"[{hr.now_iso()}] embedded {embedded}/{len(chunks)} "
                f"({rate:.1f} chunks/s, ETA {eta / 60:.1f} min, tokens={tokens_total})",
                flush=True,
            )
    upserted += flush(pending)
    total_seconds = time.perf_counter() - started_total

    count = client.count(collection_name=args.collection, exact=True).count
    print(f"collection points: {count}")

    manifest = {
        "schema": "chilon-qwen-api-index/v1",
        "created_at": hr.now_iso(),
        "git_commit": hr._git_commit(),
        "database": {
            "host": "127.0.0.1:55495",
            "name": "chilon",
            **counts,
            "chunks_embedded": len(chunks),
            "limit": args.limit or None,
        },
        "collection": {
            "name": args.collection,
            "points": count,
            "dim": args.dim,
            "distance": "cosine",
            "qdrant_url": args.qdrant_url,
            "payload_indexes": list(local_build.INDEX_FIELDS),
            "mode": "resume" if args.resume else "fresh",
            "pre_existing_points_skipped": len(existing_ids),
        },
        "knowledge_points": {
            "source": "knowledge_annotations (active rows: superseded_by IS NULL)",
            "questions_with_kp": len(annotations),
            "name_map_used": bool(kp_name_map),
            "name_map_size": len(kp_name_map),
        },
        "embedding": {
            "provider": "dashscope",
            "model": qwen_api.embedding_model(),
            "region": os.environ.get("CHILON_QWEN_REGION", "cn-beijing"),
            "base_url": os.environ.get("CHILON_QWEN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"),
            "dim": args.dim,
            "batch_size": args.batch_size,
            "input_template": "资料类型/年份/试卷/题号/题型/知识点 + 正文（V1.2 §9.3）",
        },
        "usage": {
            "requests": requests,
            "input_tokens": tokens_total,
            "estimated_cost_cny_at_0_5_per_m": round(tokens_total / 1_000_000 * 0.5, 4),
        },
        "timing": {
            "fetch_seconds": round(fetch_seconds, 1),
            "embed_seconds": round(embed_seconds, 1),
            "upsert_seconds": round(upsert_seconds, 1),
            "total_seconds": round(total_seconds, 1),
            "chunks_per_second": round(len(chunks) / embed_seconds, 2) if embed_seconds else None,
            "tokens_per_second": round(tokens_total / embed_seconds, 1) if embed_seconds else None,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {hr._rel(args.manifest)}")
    print(json.dumps(manifest["usage"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
