"""Build a minimal, valid PDF with a text layer, for tests.

Written by hand instead of pulling in a PDF library: the test needs to prove that
*ingestion* can read a real PDF, and generating the fixture with the same kind of
library would hide the parts of the format that actually break extraction (offsets,
text operators).

ASCII only: Helvetica has no built-in CJK glyphs, and embedding a Chinese font is a
different problem from the one under test.
"""

from __future__ import annotations


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def minimal_pdf(lines: list[str], *, font_size: int = 12) -> bytes:
    """One page, one line per entry, Helvetica, no compression."""
    leading = font_size + 6
    ops = ["BT", f"/F1 {font_size} Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            ops.append(f"0 -{leading} Td")
        ops.append(f"({_escape(line)}) Tj")
    ops.append("ET")
    content = "\n".join(ops).encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(out)
