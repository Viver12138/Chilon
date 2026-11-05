#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一批人工标注合并进 02_Processed/Annotations/<document_id>.json。

批次文件格式（每行一条，| 分隔）：
    gk_2012_xxx_q01|kp_09_05_ellipse|kp_09_08_eccentricity kp_09_04_conic_def|0.85|判据

用法：
    python tools/kb_annotate_apply.py var/annotations/batch-001.txt
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

VAULT = pathlib.Path(r"C:\Users\Viver\Desktop\高中数学")
ANN = VAULT / "02_Processed" / "Annotations"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: kb_annotate_apply.py <batch-file>")
        return 2
    batch = pathlib.Path(sys.argv[1])
    lines = [ln for ln in batch.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]

    by_doc: dict[str, list[dict]] = {}
    bad = []
    for ln in lines:
        parts = ln.split("|")
        if len(parts) < 5:
            bad.append(ln)
            continue
        qid, prim, sec, conf, why = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip(), parts[4].strip()
        # 可选第 6 字段：小问级映射，格式 1:kp_a,kp_b;2:kp_c
        by_part = []
        if len(parts) >= 6 and re.match(r"^\d+:", parts[5].strip()):
            why = "|".join(parts[4:len(parts) - 1]).strip()
            for chunk in parts[-1].strip().split(";"):
                if not chunk.strip():
                    continue
                n, _, kps = chunk.partition(":")
                by_part.append({"part": f"({n.strip()})",
                                "kp": [k.strip() for k in kps.split(",") if k.strip()]})
        try:
            conf_val = float(conf) if conf else 0.0
        except ValueError:
            conf_val = 0.0
        m = re.match(r"^(gk_\d{4}_[a-z0-9_]+)_q(\d{2})$", qid)
        if not m:
            bad.append(ln)
            continue
        doc = m.group(1)
        by_doc.setdefault(doc, []).append({
            "question_id": qid,
            "annotation": {
                "kp_primary": None if prim in ("", "-", "null") else prim,
                "kp_secondary": [k for k in sec.split() if k and k not in ("-", "null")],
                "source": "model",
                "model": "deepseek-flash (batch, 2026-11-05)",
                "confidence": conf_val,
                "status": "needs_review",
                "rationale": why,
                "reviewed_by": None,
                **({"kp_by_part": by_part} if by_part else {}),
            },
        })

    merged = created = 0
    for doc, items in by_doc.items():
        path = ANN / f"{doc}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"document_id": doc, "version": 1, "note": "批量标注", "items": []}
            created += 1
        existing = {i["question_id"]: i for i in data["items"]}
        for it in items:
            existing[it["question_id"]] = it
            merged += 1
        data["items"] = sorted(existing.values(), key=lambda x: x["question_id"])
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"批次 {batch.name}：{len(lines)} 条｜写入 {merged}｜新文档 {created}｜格式错误 {len(bad)}")
    for b in bad[:5]:
        print("  格式问题:", b[:80])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
