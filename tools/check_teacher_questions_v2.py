"""Validate teacher-questions/v2 templates and datasets.

Structural validation uses corpus/eval/teacher_questions.v2.schema.json; this
script adds the checks that JSON Schema alone cannot express (quota counts,
verified flags, chunk_id existence against PostgreSQL).

Usage (system python has jsonschema):

    python tools/check_teacher_questions_v2.py
    python tools/check_teacher_questions_v2.py --input corpus/eval/teacher_questions.v2.json
    python tools/check_teacher_questions_v2.py --input ... --database-url "postgresql+psycopg://..."

Exit codes:
    0  ok
    2  schema / template structural error
    3  dataset completeness error (unfilled text, unverified expect, bad quota)
    4  database check failed (missing chunks / cannot connect)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = ROOT / "corpus" / "eval" / "teacher_questions.v2.schema.json"
DEFAULT_INPUT = ROOT / "corpus" / "eval" / "teacher_questions.v2.template.json"
QUOTA = {"definition": 8, "theorem": 6, "formula": 6, "question": 10}
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def fail(message: str, code: int) -> int:
    print(f"FAIL: {message}")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate teacher-questions/v2")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--database-url", default=os.environ.get("CHILON_TEST_DATABASE_URL"))
    parser.add_argument("--min-strict", type=int, default=30)
    parser.add_argument("--require-quota", action="store_true", help="strict 类型必须严格等于 8/6/6/10")
    args = parser.parse_args()

    try:
        import jsonschema
    except ImportError:
        print("需要 jsonschema：请用系统 python（python tools/...），不要用 .venv。")
        return 2

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    data = json.loads(args.input.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        print(f"FAIL: schema 校验失败（{len(errors)} 条）：")
        for error in errors[:20]:
            print(f"  - {list(error.path)}: {error.message}")
        return 2
    print(f"OK schema: {args.input.relative_to(ROOT) if args.input.is_relative_to(ROOT) else args.input}")

    queries = data["queries"]
    ids = [q["id"] for q in queries]
    if len(ids) != len(set(ids)):
        dup = [qid for qid, count in Counter(ids).items() if count > 1]
        return fail(f"id 重复：{dup}", 2)

    is_template = bool(data.get("template"))
    categories = Counter(q["category"] for q in queries)
    print(f"queries={len(queries)} categories={dict(categories)}")

    if is_template:
        if data.get("provenance", {}).get("status") != "template":
            return fail("模板的 provenance.status 必须是 template", 2)
        if len(queries) != 60:
            return fail(f"v2.0 模板应为 60 槽位，当前 {len(queries)}", 2)
        for category, expected in {"主题词": 12, "题型+知识点": 12, "教材概念": 12, "年份+卷别": 12, "自然语言要求": 12}.items():
            if categories.get(category) != expected:
                return fail(f"模板类别 {category} 应为 {expected}，当前 {categories.get(category)}", 2)
        planned = Counter(q.get("strict_plan") for q in queries if q.get("strict_plan"))
        for object_type, expected in QUOTA.items():
            if planned.get(object_type) != expected:
                return fail(f"模板 strict 计划 {object_type} 应为 {expected}，当前 {planned.get(object_type)}", 2)
        strict_planned = sum(planned.values())
        if strict_planned != 30:
            return fail(f"模板 strict 计划应为 30，当前 {strict_planned}", 2)
        print(f"OK template quotas: strict_plan={dict(planned)} total={strict_planned}")
        print("PASS: 模板结构、类别配额、strict 计划均正确。")
        return 0

    # ---- real dataset checks ----
    empty_text = [q["id"] for q in queries if not q.get("text", "").strip()]
    if empty_text:
        return fail(f"未填 text：{empty_text[:10]}", 3)
    empty_any = [q["id"] for q in queries if not q["expect"].get("any")]
    if empty_any:
        return fail(f"expect.any 为空：{empty_any[:10]}", 3)
    unverified = [q["id"] for q in queries if not q.get("expect_verified")]
    if unverified:
        return fail(f"expect_verified=false：{unverified[:10]}", 3)
    if data.get("provenance", {}).get("status") != "real_teacher":
        return fail("数据集 provenance.status 必须是 real_teacher（模拟候选不能当基线）", 3)

    strict_queries = [q for q in queries if q["expect"].get("strict")]
    strict_types = Counter(q["expect"]["strict"]["object_type"] for q in strict_queries)
    print(f"strict queries={len(strict_queries)} types={dict(strict_types)}")
    if len(strict_queries) < args.min_strict:
        return fail(f"strict 查询 {len(strict_queries)} < 要求 {args.min_strict}", 3)
    if args.require_quota:
        for object_type, expected in QUOTA.items():
            if strict_types.get(object_type) != expected:
                return fail(f"strict 类型 {object_type} 应为 {expected}，当前 {strict_types.get(object_type)}", 3)
    bad_chunk_ids = []
    for q in strict_queries:
        strict = q["expect"]["strict"]
        if not q.get("strict_verified"):
            return fail(f"{q['id']} 有 strict 但 strict_verified != true", 3)
        if not strict.get("rationale"):
            return fail(f"{q['id']} strict 缺 rationale", 3)
        if not strict.get("verified_by"):
            return fail(f"{q['id']} strict 缺 verified_by", 3)
        for chunk_id in strict["chunk_ids"]:
            if not UUID_RE.match(chunk_id):
                bad_chunk_ids.append((q["id"], chunk_id))
    if bad_chunk_ids:
        return fail(f"chunk_id 不是 UUID：{bad_chunk_ids[:5]}", 3)

    if args.database_url:
        try:
            import psycopg  # type: ignore
        except ImportError:
            print("提示：--database-url 需要 .venv（psycopg）；本次跳过 DB 存在性检查。")
        else:
            dsn = args.database_url.replace("postgresql+psycopg://", "postgresql://")
            conn = psycopg.connect(dsn, connect_timeout=10)
            try:
                with conn.cursor() as cur:
                    for q in strict_queries:
                        for chunk_id in q["expect"]["strict"]["chunk_ids"]:
                            cur.execute("SELECT 1 FROM knowledge_chunks WHERE id = %s::uuid", (chunk_id,))
                            if cur.fetchone() is None:
                                return fail(f"{q['id']} strict chunk 不存在：{chunk_id}", 4)
            finally:
                conn.close()
            print("OK database: 所有 strict chunk_id 均存在")
    else:
        print("提示：未传 --database-url，跳过 strict chunk_id 存在性检查。")

    print("PASS: 数据集完整（text/expect/verification/strict 金标结构均通过）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
