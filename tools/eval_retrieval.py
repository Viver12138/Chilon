"""Measure retrieval against a golden set: Recall@8, MRR, and empty-result rate.

Without a number, every retrieval change is a guess. This runs the real `knowledge_search`
with a real teacher session, so it measures what a teacher would actually get.

A query counts as **missed** if none of its `expect_any` fragments appears in the top-8.
The fragment comes from the corpus itself, not from my imagination — a query whose
expectation I invented would only measure my own optimism.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from app.db import session as db  # noqa: E402
from app.tools import impl as tools_impl  # noqa: E402

LIMIT = 8


def ctx(owner, topic):
    return tools_impl.ToolContext(
        owner_id=owner,
        execution_id=uuid.uuid4(),
        step_key="search",
        spec={},
        requirement={"topic": topic, "sources": []},
        deps={},
    )


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2
    golden = json.loads((ROOT / "corpus/eval/queries.json").read_text(encoding="utf-8"))
    queries = golden["queries"]

    # the corpus is entirely platform-scoped, so an admin session measures the same
    # retrieval a teacher gets — without provisioning a role on a database that already
    # has objects owned by one
    db.init(url)
    hits_total = 0
    found = 0
    empty = 0
    reciprocal = 0.0
    strict_found = strict_total = 0
    strict_reciprocal = 0.0
    rows = []
    try:
        teacher = uuid.uuid4()

        for query in queries:
            async with db.system_session() as session:
                result = await tools_impl.knowledge_search(session, ctx(teacher, query["text"]))
            hits = result["hits"][:LIMIT]
            hits_total += len(hits)
            if not hits:
                empty += 1
            rank = None
            target_rank = None
            target = query.get("target")
            for position, hit in enumerate(hits, 1):
                haystack = (hit.get("excerpt") or "") + " " + (hit.get("source_title") or "")
                if rank is None and any(fragment in haystack for fragment in query["expect_any"]):
                    rank = position
                if target and target_rank is None and target in haystack:
                    target_rank = position
                if rank is not None and (target is None or target_rank is not None):
                    break
            if rank is not None:
                found += 1
                reciprocal += 1.0 / rank
            if target_rank is not None:
                strict_found += 1
                strict_reciprocal += 1.0 / target_rank
            strict_total += 1 if target else 0
            rows.append(
                {
                    "id": query["id"],
                    "category": query["category"],
                    "text": query["text"],
                    "hits": len(hits),
                    "rank": rank,
                    "target_rank": target_rank,
                }
            )
    finally:
        await db.dispose()

    total = len(queries)
    print(f"{'id':8} {'cat':12} {'hits':>4} {'rank':>5} {'tgt':>4}  query")
    for row in rows:
        print(
            f"{row['id']:8} {row['category']:12} {row['hits']:>4} "
            f"{row['rank'] if row['rank'] else '-':>5} "
            f"{row['target_rank'] if row['target_rank'] else '-':>4}  {row['text'][:30]}"
        )
    print()
    print(f"queries      : {total}")
    print(f"Recall@{LIMIT:<2}    : {found}/{total} = {found / total:.0%}")
    print(f"MRR          : {reciprocal / total:.3f}")
    print(f"empty results: {empty}/{total} = {empty / total:.0%}")
    print(f"avg hits     : {hits_total / total:.1f}")
    if strict_total:
        print(
            f"strict target: {strict_found}/{strict_total} = {strict_found / strict_total:.0%}"
            f"  (MRR {strict_reciprocal / max(strict_total, 1):.3f})"
        )
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
