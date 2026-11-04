"""Generate a sample teacher/student DOCX pair from the real renderer.

No database needed: this exercises exactly the code path an export uses, so what
you open here is what a teacher would download.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services import export, materials  # noqa: E402

QUESTIONS = [
    {
        "no": "1",
        "stem": "已知 f(x)=sin(2x+π/3)，求 f(x) 的最小正周期与单调递增区间。",
        "answer": "最小正周期 T=π；递增区间为 [kπ-5π/12, kπ+π/12]，k∈Z。",
        "explanation": "由 T=2π/2=π。令 -π/2+2kπ ≤ 2x+π/3 ≤ π/2+2kπ，解得 -5π/12+kπ ≤ x ≤ π/12+kπ。",
        "citation_chunk_id": "c-1",
    },
    {
        "no": "2",
        "stem": "化简 sin²x + cos²x + tan x·cot x。",
        "answer": "结果为 2。",
        "explanation": "sin²x+cos²x=1，tan x·cot x=1，故原式为 2。",
        "citation_chunk_id": None,
    },
    {
        "no": "3",
        "stem": "在 △ABC 中，a=3，b=4，C=90°，求 c。",
        "answer": "c=5。",
        "explanation": "由勾股定理 c²=a²+b²=9+16=25，故 c=5。",
        "citation_chunk_id": "c-2",
    },
]

CITATIONS = [
    {"citation_id": "c-1", "source": {"source_type": "gaokao_paper", "title": "2023 全国甲卷 数学", "year": 2023}},
    {"citation_id": "c-2", "source": {"source_type": "textbook", "title": "人教版必修一"}},
]


def main() -> int:
    out_dir = ROOT / "docs" / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    document = materials.build_document(
        title="三角函数练习", topic="三角函数", questions=QUESTIONS, citations=CITATIONS
    )

    for profile, label in (("teacher", "教师版"), ("student", "学生版")):
        data = export.render_docx(document, profile)
        path = out_dir / f"Chilon-三角函数练习-{label}.docx"
        path.write_bytes(data)
        text = export.docx_text(data)
        answer_hits = sum(1 for q in QUESTIONS if q["answer"] in text)
        print(f"{label}: {len(data)} bytes, 答案命中 {answer_hits} 条 -> {path.name}")

    teacher = export.docx_text(export.render_docx(document, "teacher"))
    student = export.docx_text(export.render_docx(document, "student"))
    leaked = [q["no"] for q in QUESTIONS if q["answer"] in student]
    kept = [q["no"] for q in QUESTIONS if q["answer"] in teacher]
    print()
    print(f"教师版含答案的题: {kept}")
    print(f"学生版泄漏答案的题: {leaked or '无'}")
    return 1 if leaked else 0


if __name__ == "__main__":
    raise SystemExit(main())
