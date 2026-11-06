"""Build the Qdrant vector index for the Chilon corpus (V1.2 stage 4).

Reads the authoritative chunk text from PostgreSQL (SSOT), composes the
embedding input described in V1.2 §9.3 (body + a little necessary metadata),
embeds it with Qwen3-Embedding-0.6B on CPU, and writes vectors + filter
metadata to Qdrant.  The index is a derived artefact and can be rebuilt from
PostgreSQL at any time.

Usage (from D:\\Chilon):

    $env:CHILON_TEST_DATABASE_URL = "postgresql+psycopg://postgres:<pw>@127.0.0.1:55495/chilon"
    .\\.venv\\Scripts\\python.exe tools\\build_hybrid_index.py --recreate

    # quick throughput benchmark on 256 chunks (does not create the final collection)
    .\\.venv\\Scripts\\python.exe tools\\build_hybrid_index.py --limit 256 --collection chilon_bench_256 --recreate

Manifest: var/retrieval/index_manifest.json
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

from app.services import hybrid_retrieval as hr  # noqa: E402

DEFAULT_COLLECTION = "chilon_chunks_qwen3_embedding_0_6b_v1"
EMBED_REPO = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_MODEL_DIR = ROOT / "var" / "retrieval" / "models" / "Qwen3-Embedding-0.6B"
DEFAULT_HF_CACHE = ROOT / "var" / "retrieval" / "hf_cache"
DEFAULT_MANIFEST = ROOT / "var" / "retrieval" / "index_manifest.json"


def ensure_model(repo: str, model_dir: Path, cache_dir: Path) -> tuple[Path, str | None]:
    """Download the model snapshot if needed; return (dir, upstream revision)."""
    from huggingface_hub import HfApi, snapshot_download

    revision: str | None = None
    try:
        info = HfApi().model_info(repo, revision="main")
        revision = getattr(info, "sha", None)
    except Exception as exc:  # noqa: BLE001 - revision is metadata, not fatal
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

    url = dsn.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(url, connect_timeout=10)


def corpus_counts(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM knowledge_sources),"
            " (SELECT count(*) FROM knowledge_chunks),"
            " (SELECT count(*) FROM knowledge_questions)"
        )
        sources, chunks, questions = cur.fetchone()
    return {"sources": sources, "chunks": chunks, "questions": questions}


INDEX_FIELDS = {
    "source_type": "keyword",
    "paper": "keyword",
    "question_type": "keyword",
    "year": "integer",
}


def collection_exists(client, name: str) -> bool:
    try:
        return bool(client.collection_exists(name))
    except AttributeError:  # older qdrant-client
        return any(collection.name == name for collection in client.get_collections().collections)


def create_collection(client, name: str, dim: int) -> None:
    from qdrant_client import models as qm  # type: ignore

    client.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )
    for field, schema in INDEX_FIELDS.items():
        schema_type = (
            qm.PayloadSchemaType.INTEGER if schema == "integer" else qm.PayloadSchemaType.KEYWORD
        )
        try:
            client.create_payload_index(
                collection_name=name, field_name=field, field_schema=schema_type, wait=True
            )
        except Exception as exc:  # noqa: BLE001 - payload index is an optimization
            print(f"WARN: payload index {field} failed: {exc}")


def scroll_ids(client, name: str) -> set[str]:
    ids: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=name,
            limit=1024,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        ids.update(str(point.id) for point in points)
        if offset is None:
            break
    return ids


def read_model_dim(model_dir: Path) -> int:
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    return int(config["hidden_size"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Qdrant index for Chilon chunks")
    parser.add_argument("--database-url", default=os.environ.get("CHILON_TEST_DATABASE_URL"))
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--hf-cache", type=Path, default=DEFAULT_HF_CACHE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--max-length", type=int, default=hr.CONFIG["embed_max_length"])
    parser.add_argument(
        "--batch-size", type=int, default=4, help="embedding batch (length-sorted); default 4 (measured fastest on CPU)"
    )
    parser.add_argument("--limit", type=int, default=0, help="0 = all chunks (benchmark otherwise)")
    parser.add_argument(
        "--kp-vocab",
        default=hr.DEFAULT_KP_VOCAB,
        help="vault 知识点词表.md（只读，提供 kp_id -> 中文名）；空字符串表示不用名称映射",
    )
    parser.add_argument("--recreate", action="store_true", help="drop and recreate the collection")
    parser.add_argument("--resume", action="store_true", help="keep existing collection, skip chunk ids already indexed")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--threads", type=int, default=hr.CONFIG["torch_threads"], help="torch CPU threads")
    parser.add_argument("--shard-index", type=int, default=0, help="0-based shard index for parallel builds")
    parser.add_argument("--shard-count", type=int, default=1, help="number of parallel build shards")
    parser.add_argument("--no-create", action="store_true", help="collection must already exist (parallel shards)")
    parser.add_argument("--create-only", action="store_true", help="create collection + payload indexes, then exit")
    args = parser.parse_args()

    if not args.database_url:
        print("CHILON_TEST_DATABASE_URL is not set (or pass --database-url)", file=sys.stderr)
        return 2
    if args.shard_count < 1 or not (0 <= args.shard_index < args.shard_count):
        print("invalid shard index/count", file=sys.stderr)
        return 2
    hr.CONFIG["torch_threads"] = args.threads

    from qdrant_client import QdrantClient  # type: ignore
    from qdrant_client import models as qm  # type: ignore

    if args.create_only:
        client = QdrantClient(url=args.qdrant_url, timeout=120)
        exists = collection_exists(client, args.collection)
        if exists and not args.recreate:
            print(f"collection {args.collection!r} already exists; pass --recreate to drop it")
            return 3
        if exists:
            client.delete_collection(args.collection)
        dim = read_model_dim(args.model_dir)
        create_collection(client, args.collection, dim)
        print(f"collection {args.collection!r} created (dim={dim}, cosine) + payload indexes")
        return 0

    started_total = time.perf_counter()
    process_peak = hr._rss_mb()

    # 1) model
    if args.skip_download:
        model_dir, revision = args.model_dir, None
    else:
        model_dir, revision = ensure_model(EMBED_REPO, args.model_dir, args.hf_cache)

    # 2) chunks from PostgreSQL
    print("connecting to PostgreSQL ...")
    conn = connect(args.database_url)
    try:
        counts = corpus_counts(conn)
        fetch_started = time.perf_counter()
        chunks = hr.fetch_all_chunks(conn)
        # Knowledge points come from knowledge_annotations (SSOT), NOT from
        # knowledge_questions.current_knowledge_points (its representation changed
        # during the 2026-11-06 annotation import; the hybrid prototype must not
        # depend on it).
        kp_name_map = hr.load_kp_name_map(args.kp_vocab) if args.kp_vocab else {}
        annotations = hr.fetch_annotation_points(conn, kp_name_map)
        hr.attach_annotation_points(chunks, annotations)
        fetch_seconds = time.perf_counter() - fetch_started
    finally:
        conn.close()
    if args.limit:
        chunks = chunks[: args.limit]
    print(f"chunks: {len(chunks)} (DB: {counts})  fetch={fetch_seconds:.1f}s")

    # 3) embedding model
    print("loading Qwen3-Embedding-0.6B on CPU ...")
    rss_before_model = hr._rss_mb()
    load_started = time.perf_counter()
    model, tokenizer, dim = hr.load_embedding_model(model_dir)
    model_load_seconds = time.perf_counter() - load_started
    rss_after_model = hr._rss_mb()
    print(f"   dim={dim} load={model_load_seconds:.1f}s rss={rss_after_model}MB")

    # compose embedding inputs once, then length-sort for CPU-friendly batching
    print("composing embedding inputs ...", flush=True)
    texts = [hr.embedding_text(hit) for hit in chunks]
    print("tokenizing for length buckets ...", flush=True)
    lengths = [len(tokenizer.encode(text, add_special_tokens=True)) for text in texts]
    order = sorted(range(len(chunks)), key=lambda index: lengths[index])
    chunks = [chunks[index] for index in order]
    texts = [texts[index] for index in order]
    estimated_tokens = sum(min(length, args.max_length) for length in lengths)
    print(
        f"length buckets: mean_tokens={sum(lengths) / max(len(lengths), 1):.1f} "
        f"max={max(lengths) if lengths else 0} est_tokens@max_length={estimated_tokens}",
        flush=True,
    )

    # 4) shard selection + Qdrant collection
    if args.shard_count > 1:
        pairs = list(zip(chunks, texts))
        pairs = pairs[args.shard_index :: args.shard_count]
        chunks = [pair[0] for pair in pairs]
        texts = [pair[1] for pair in pairs]
        print(f"shard {args.shard_index + 1}/{args.shard_count}: {len(chunks)} chunks", flush=True)

    client = QdrantClient(url=args.qdrant_url, timeout=120)
    exists = collection_exists(client, args.collection)
    existing_ids: set[str] = set()
    if exists and args.resume:
        existing_ids = scroll_ids(client, args.collection)
        if existing_ids:
            before = len(chunks)
            pairs = [
                (hit, text) for hit, text in zip(chunks, texts) if hit["chunk_id"] not in existing_ids
            ]
            chunks = [pair[0] for pair in pairs]
            texts = [pair[1] for pair in pairs]
            print(
                f"resume: {len(existing_ids)} points exist, skipped {before - len(chunks)}, "
                f"remaining {len(chunks)}",
                flush=True,
            )
    if not exists:
        if args.no_create:
            print(
                f"collection {args.collection!r} does not exist; create it first (--create-only)",
                file=sys.stderr,
            )
            return 4
        create_collection(client, args.collection, dim)
        print(f"collection {args.collection!r} created (dim={dim}, cosine) + payload indexes", flush=True)
    elif not args.resume:
        if not args.recreate:
            print(
                f"collection {args.collection!r} already exists; pass --recreate to rebuild or --resume to continue",
                file=sys.stderr,
            )
            return 3
        client.delete_collection(args.collection)
        create_collection(client, args.collection, dim)
        print(f"collection {args.collection!r} recreated (dim={dim}, cosine) + payload indexes", flush=True)

    # 5) embed + upsert
    import torch  # type: ignore

    group_size = max(args.batch_size * 8, 256)
    point_batch = 256
    embedded = 0
    upserted = 0
    tokens_total = 0
    embed_seconds = 0.0
    upsert_seconds = 0.0
    progress_started = time.perf_counter()
    pending: list = []
    peak_rss = hr._rss_mb() or 0.0

    def flush(points: list) -> int:
        nonlocal upsert_seconds
        if not points:
            return 0
        started = time.perf_counter()
        client.upsert(collection_name=args.collection, points=points, wait=False)
        upsert_seconds += time.perf_counter() - started
        return len(points)

    for start in range(0, len(chunks), group_size):
        group_chunks = chunks[start : start + group_size]
        group_texts = texts[start : start + group_size]
        vectors, stats = hr.embed_texts(
            model,
            tokenizer,
            group_texts,
            batch_size=args.batch_size,
            max_length=args.max_length,
        )
        tokens_total += stats["tokens"]
        embed_seconds += stats["seconds"]
        for hit, vector in zip(group_chunks, vectors):
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
        embedded += len(group_chunks)
        rss = hr._rss_mb()
        if rss:
            peak_rss = max(peak_rss, rss)
        elapsed = time.perf_counter() - progress_started
        rate = embedded / elapsed if elapsed else 0
        eta = (len(chunks) - embedded) / rate if rate else 0
        if embedded % 256 < group_size or embedded >= len(chunks):
            print(
                f"[{hr.now_iso()}] embedded {embedded}/{len(chunks)} "
                f"({rate:.1f} chunks/s, ETA {eta / 60:.1f} min, rss {rss}MB)",
                flush=True,
            )
    upserted += flush(pending)
    total_seconds = time.perf_counter() - started_total
    peak_rss = max(peak_rss, hr._rss_mb() or 0.0)

    # 6) collection stats (payload indexes were created with the collection)
    count = client.count(collection_name=args.collection, exact=True).count
    print(f"collection points: {count}")

    manifest = {
        "schema": "chilon-hybrid-index/v1",
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
            "dim": dim,
            "distance": "cosine",
            "qdrant_url": args.qdrant_url,
            "payload_indexes": list(INDEX_FIELDS),
            "mode": "resume" if args.resume else "fresh",
            "pre_existing_points_skipped": len(existing_ids),
            "shard": {"index": args.shard_index, "count": args.shard_count},
        },
        "knowledge_points": {
            "source": "knowledge_annotations (active rows: superseded_by IS NULL)",
            "questions_with_kp": len(annotations),
            "name_map_used": bool(kp_name_map),
            "name_map_size": len(kp_name_map),
            "current_knowledge_points_column_used": False,
            "note": "2026-11-06 annotation import changed current_knowledge_points to kp_id arrays; the hybrid prototype reads knowledge_annotations instead, per Lead data policy.",
        },
        "embedding": {
            "model": EMBED_REPO,
            "revision": revision,
            "local_dir": hr._rel(args.model_dir),
            "dtype": "float32",
            "device": "cpu",
            "dim": dim,
            "max_length": args.max_length,
            "batch_size": args.batch_size,
            "batching": "batches formed after sorting chunks by token length (CPU throughput)",
            "torch_threads": hr.CONFIG["torch_threads"],
            "instruction": hr.CONFIG["embed_instruction"],
            "input_template": "资料类型/年份/试卷/题号/题型/知识点 + 正文（V1.2 §9.3）",
        },
        "versions": {
            "torch": getattr(torch, "__version__", None),
        },
        "timing": {
            "fetch_seconds": round(fetch_seconds, 1),
            "model_load_seconds": round(model_load_seconds, 1),
            "embed_seconds": round(embed_seconds, 1),
            "upsert_seconds": round(upsert_seconds, 1),
            "total_seconds": round(total_seconds, 1),
            "chunks_per_second": round(len(chunks) / embed_seconds, 2) if embed_seconds else None,
            "tokens_per_second": round(tokens_total / embed_seconds, 1) if embed_seconds else None,
            "tokens_embedded": tokens_total,
        },
        "memory": {
            "rss_before_model_mb": rss_before_model,
            "rss_after_model_mb": rss_after_model,
            "peak_rss_mb": round(peak_rss, 1),
        },
    }
    try:
        import transformers  # type: ignore
        import qdrant_client  # type: ignore

        manifest["versions"]["transformers"] = transformers.__version__
        manifest["versions"]["qdrant_client"] = qdrant_client.__version__
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil  # type: ignore

        manifest["memory"]["peak_process_rss_mb"] = round(
            psutil.Process().memory_info().rss / (1024 * 1024), 1
        )
    except Exception:  # noqa: BLE001
        pass

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {hr._rel(args.manifest)}")
    print(json.dumps(manifest["timing"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
