"""Structural checker for the Chilon golden-path example.

Implements the parts of the master document's semantic validation
(section 20.9) that JSON Schema cannot express, so that the frozen
example cannot silently drift out of compliance.

Usage:
    python design/check_golden_path.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "schemas" / "trigonometry_golden_path.v1.example.json"

CONTAINER_TYPES = {"section"}
EXERCISE_CONTAINERS = {"exercise", "worked_example"}
ANSWER_ONLY_IN = {"exercise", "worked_example"}

# section purpose -> allowed direct child block types (section 20.9 rule 18)
PURPOSE_CHILD_RULES = {
    "worked_examples": {"worked_example"},
    "exercises": {"exercise", "exercise_group"},
    "worksheet": {"worksheet_response"},
}

EXERCISE_PURPOSES = {"worked_examples", "exercises"}

# contract vocabulary — kept in sync with the two JSON Schema files
SCHEMA_VERSIONS = {"1.0.0", "1.1.0"}
QUESTION_TYPES = {
    "single_choice",
    "multiple_choice",
    "fill_blank",
    "short_answer",
    "calculation",
    "proof",
    "application",
}
CHOICE_TYPES = {"single_choice", "multiple_choice"}
NON_CHOICE_TYPES = QUESTION_TYPES - CHOICE_TYPES
SOURCE_TYPES = {
    "textbook",
    "workbook",
    "gaokao_paper",
    "mock_exam",
    "curriculum_standard",
    "teacher_authored",
    "licensed_material",
    "other",
}
PROVENANCE_KINDS = {
    "teacher_authored",
    "ai_generated",
    "textbook_example",
    "workbook_example",
    "gaokao_question",
    "mock_question",
    "licensed_material",
    "adapted",
}
# source_type -> metadata the citation schema makes mandatory
SOURCE_REQUIRED = {
    "textbook": ("publisher", "edition"),
    "workbook": ("publisher", "edition"),
    "gaokao_paper": ("year", "region", "paper_name", "question_number"),
    "mock_exam": ("year", "region", "paper_name", "question_number"),
}

# provenance kind -> the source_type it must bind (section 20.9 rules 8-9)
KIND_SOURCE = {
    "textbook_example": "textbook",
    "workbook_example": "workbook",
    "gaokao_question": "gaokao_paper",
    "mock_question": "mock_exam",
}


class Failure(Exception):
    pass


def walk(node, path="$", parent=None, parent_type=None):
    yield node, path, parent, parent_type
    for key in ("children", "items"):
        for i, child in enumerate(node.get(key, []) or []):
            yield from walk(child, f"{path}.{key}[{i}]", node, node.get("type"))


def collect_ids(doc):
    ids = []
    for root_index, block in enumerate(doc["blocks"]):
        for node, path, _p, _pt in walk(block, f"blocks[{root_index}]"):
            ids.append((node.get("id"), path))
    return ids


def check(doc):
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    # --- contract vocabulary (mirrors the JSON Schema enums) -------------
    if doc.get("schema_version") not in SCHEMA_VERSIONS:
        fail(f"schema_version {doc.get('schema_version')!r} not in {sorted(SCHEMA_VERSIONS)}")

    # --- rule 1: unique ids ---------------------------------------------
    seen: dict[str, str] = {}
    for node_id, path in collect_ids(doc):
        if node_id is None:
            fail(f"{path}: missing id")
            continue
        if node_id in seen:
            fail(f"{path}: duplicate id {node_id} (already at {seen[node_id]})")
        seen[node_id] = path

    # --- rule 3/6/7: citation integrity ---------------------------------
    citations = doc.get("citations", [])
    citation_ids = [c.get("citation_id") for c in citations]
    if len(set(citation_ids)) != len(citation_ids):
        fail("citations: duplicate citation_id")

    for c in citations:
        cid = c.get("citation_id")
        src = c.get("source") or {}
        stype = src.get("source_type")
        if stype not in SOURCE_TYPES:
            fail(f"citation {cid}: unknown source_type {stype!r}")
        for field in SOURCE_REQUIRED.get(stype, ()):
            if not src.get(field):
                fail(f"citation {cid}: source_type {stype!r} requires {field!r}")
        if not c.get("source", {}).get("title"):
            fail(f"citation {cid}: source requires a title")

    used: set[str] = set()

    def note_inline(inline, path):
        if not isinstance(inline, list):
            return
        for j, item in enumerate(inline):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "citation_ref":
                cid = item.get("citation_id")
                used.add(cid)
                if cid not in citation_ids:
                    fail(f"{path}.content[{j}]: dangling citation_ref {cid}")

    for root_index, block in enumerate(doc["blocks"]):
        for node, path, _p, _pt in walk(block, f"blocks[{root_index}]"):
            prov = node.get("provenance") or {}
            for cid in prov.get("citation_ids", []) or []:
                used.add(cid)
                if cid not in citation_ids:
                    fail(f"{path}.provenance: dangling citation id {cid}")
            for key in ("content", "title", "instruction", "problem", "stem", "caption"):
                note_inline(node.get(key), f"{path}.{key}")

    for cid in citation_ids:
        if cid not in used:
            fail(f"citations: {cid} is unused")

    # --- rule 4 + rule 19: choice needs options, non-choice must not have them
    for root_index, block in enumerate(doc["blocks"]):
        for node, path, _p, _pt in walk(block, f"blocks[{root_index}]"):
            if node.get("type") != "exercise":
                continue
            qtype = node.get("question_type")
            options = node.get("options") or []
            if qtype not in QUESTION_TYPES:
                fail(f"{path}: unknown question_type {qtype!r}")
            if qtype in CHOICE_TYPES and len(options) < 2:
                fail(f"{path}: {qtype} has {len(options)} option(s), needs >= 2")
            if qtype in NON_CHOICE_TYPES and options:
                fail(f"{path}: {qtype} must not define options (rule 19)")
            labels = [o.get("label") for o in options]
            if len(set(labels)) != len(labels):
                fail(f"{path}: duplicated option labels {labels}")

            children = node.get("children") or []
            child_ids = {c.get("id"): c.get("type") for c in children}
            answer_ids = node.get("answer_node_ids") or []
            solution_ids = node.get("solution_node_ids") or []
            if not answer_ids:
                fail(f"{path}: no answer_node_ids")
            if not solution_ids:
                fail(f"{path}: no solution_node_ids")
            for aid in answer_ids:
                if aid not in child_ids:
                    fail(f"{path}: answer_node_id {aid} is not a direct child")
                elif child_ids[aid] != "answer":
                    fail(f"{path}: answer_node_id {aid} points at {child_ids[aid]}")
            for sid in solution_ids:
                if sid not in child_ids:
                    fail(f"{path}: solution_node_id {sid} is not a direct child")
                elif child_ids[sid] not in {"solution", "solution_step"}:
                    fail(f"{path}: solution_node_id {sid} points at {child_ids[sid]}")

    # --- rule 5: answers never student-visible --------------------------
    for root_index, block in enumerate(doc["blocks"]):
        for node, path, _p, _pt in walk(block, f"blocks[{root_index}]"):
            if node.get("type") in {"answer", "solution", "solution_step", "hint"}:
                if node.get("visibility") == "student":
                    fail(f"{path}: {node.get('type')} must not be student-visible")

    # --- rule 8/9: source-specific provenance ---------------------------
    for root_index, block in enumerate(doc["blocks"]):
        for node, path, _p, _pt in walk(block, f"blocks[{root_index}]"):
            prov = node.get("provenance") or {}
            kind, basis = prov.get("kind"), prov.get("basis")
            cids = prov.get("citation_ids") or []
            types = {c["source"]["source_type"] for c in citations if c["citation_id"] in cids}
            if kind not in PROVENANCE_KINDS:
                fail(f"{path}: unknown provenance.kind {kind!r}")
                continue
            required_source = KIND_SOURCE.get(kind)
            if required_source:
                if basis not in {"verbatim", "excerpt"}:
                    fail(f"{path}: {kind} basis must be verbatim/excerpt")
                if required_source not in types:
                    fail(f"{path}: {kind} lacks a {required_source} citation")
            if kind == "adapted" and not prov.get("change_note"):
                fail(f"{path}: adapted provenance requires change_note")

    # --- rule 16: locator sanity (single segment or multi-segment) -------
    for c in citations:
        loc = c["locator"]
        cid = c["citation_id"]
        has_single = "char_start" in loc and "char_end" in loc
        segments = loc.get("segments")
        if not has_single and not segments:
            fail(f"citation {cid}: locator needs char_start/char_end or segments")
            continue
        if has_single and loc["char_end"] <= loc["char_start"]:
            fail(f"citation {cid}: char_end must exceed char_start")
        if segments is not None:
            if len(segments) < 2:
                fail(f"citation {cid}: segments needs >= 2 entries (use single form otherwise)")
            for i, seg in enumerate(segments):
                if seg.get("char_end", 0) <= seg.get("char_start", 0):
                    fail(f"citation {cid}: segments[{i}] char_end must exceed char_start")
                if loc.get("locator_kind") == "pdf_text" and not seg.get("page_number"):
                    fail(f"citation {cid}: segments[{i}] needs page_number for pdf_text")
        if loc.get("locator_kind") == "pdf_text" and not segments and not loc.get("page_number"):
            fail(f"citation {cid}: pdf_text locator needs page_number")

    # --- rule 18: section purpose matches children ----------------------
    for root_index, block in enumerate(doc["blocks"]):
        for node, path, _p, _pt in walk(block, f"blocks[{root_index}]"):
            if node.get("type") != "section":
                continue
            purpose = node.get("purpose")
            children = [c.get("type") for c in node.get("children") or []]
            allowed = PURPOSE_CHILD_RULES.get(purpose)
            if allowed is not None:
                if not any(t in allowed for t in children):
                    fail(f"{path}: purpose={purpose} needs one of {sorted(allowed)}")
                stray = [t for t in children if t not in allowed | {"page_break"}]
                if stray:
                    fail(f"{path}: purpose={purpose} has unrelated children {stray}")
            elif purpose not in EXERCISE_PURPOSES:
                if set(children) and set(children) <= {"exercise_group", "worked_example"}:
                    fail(f"{path}: purpose={purpose} contains only exercise/example blocks")

    # --- rule 15: non-empty deliverables --------------------------------
    def count(types):
        total = 0
        for root_index, block in enumerate(doc["blocks"]):
            for node, _path, _p, _pt in walk(block, f"blocks[{root_index}]"):
                if node.get("type") in types:
                    total += 1
        return total

    kind = doc.get("document_kind")
    if kind == "exercise_set" and count({"exercise"}) < 1:
        fail("exercise_set requires >= 1 exercise")
    if kind == "worksheet" and count({"worksheet_response"}) < 1:
        fail("worksheet requires >= 1 worksheet_response")

    return errors


def _find_block(doc, kind):
    stack = list(doc["blocks"])
    while stack:
        node = stack.pop()
        if (node.get("provenance") or {}).get("kind") == kind:
            return node
        stack.extend(node.get("children") or [])
    return None


def self_test(doc):
    """Inject source-binding and vocabulary defects; every one must be caught."""
    import copy

    cases = [
        (
            "mock_question citing a gaokao source",
            lambda d: _find_block(d, "mock_question")["provenance"].update(
                citation_ids=[d["citations"][1]["citation_id"]]
            ),
        ),
        (
            "workbook_example binding a textbook citation",
            lambda d: _find_block(d, "workbook_example")["provenance"].update(
                citation_ids=[d["citations"][2]["citation_id"]]
            ),
        ),
        ("unknown schema_version", lambda d: d.update(schema_version="1.2.0")),
        (
            "mock_exam citation missing question_number",
            lambda d: d["citations"][2]["source"].pop("question_number"),
        ),
        ("unknown source_type", lambda d: d["citations"][0]["source"].update(source_type="blog")),
        (
            "unknown provenance kind",
            lambda d: _find_block(d, "workbook_example")["provenance"].update(kind="workbook_exercises"),
        ),
    ]
    failures = []
    for desc, mutate in cases:
        broken = copy.deepcopy(doc)
        mutate(broken)
        if not check(broken):
            failures.append(f"self-test: {desc} was NOT detected")
    return failures


def main() -> int:
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    errors = check(doc)
    sections = [b for b in doc["blocks"] if b.get("type") == "section"]
    print(f"file      : {EXAMPLE.name}")
    print(f"blocks    : {len(doc['blocks'])} root section(s)")
    print(f"citations : {len(doc.get('citations', []))}")
    for s in sections:
        types = [c.get("type") for c in s.get("children", [])]
        print(f"  - section purpose={s.get('purpose'):<16} children={types}")
    if errors:
        print(f"\nFAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\nOK: all semantic checks passed")

    if "--selftest" in sys.argv:
        failures = self_test(doc)
        if failures:
            for f in failures:
                print(f"  - {f}")
            return 1
        print("self-test: all 6 injected defects were detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
