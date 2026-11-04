"""Try LibreOffice conversion in different output directories to find a writable one."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services import export, materials, pdf  # noqa: E402

document = materials.build_document(
    title="测试",
    topic="三角函数",
    questions=[
        {"no": "1", "stem": "求最小正周期", "answer": "答案：π", "explanation": "x", "citation_chunk_id": None}
    ],
)
docx = export.render_docx(document, "student")
binary = pdf.find_soffice()
print("soffice:", binary)
print("TEMP:", os.environ.get("TEMP"))

for label, base in (("system-temp", os.environ.get("TEMP")), ("workspace", None)):
    work = Path(tempfile.mkdtemp(prefix="lo-", dir=base))
    src = work / "d.docx"
    src.write_bytes(docx)
    profile = work / "profile"
    profile.mkdir()
    out = work / "out"
    out.mkdir()
    command = [
        str(binary),
        f"-env:UserInstallation={profile.as_uri()}",
        "--headless",
        "--norestore",
        "--nologo",
        "--nofirststartwizard",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out),
        str(src),
    ]
    result = subprocess.run(command, capture_output=True, timeout=120)
    produced = list(out.glob("*.pdf"))
    stderr = (result.stderr or b"").decode("utf-8", "replace")[:200]
    print(f"{label:12} exit={result.returncode} produced={len(produced)} stderr={stderr!r}")
    print(f"             workdir={work}")
