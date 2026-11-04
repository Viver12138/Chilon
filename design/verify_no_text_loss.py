"""Compare two document snapshots ignoring whitespace, to prove no text was lost."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def squeeze(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return re.sub(r"\s+", "", text)


def main() -> int:
    a = Path(sys.argv[1])
    b = Path(sys.argv[2])
    sa, sb = squeeze(a), squeeze(b)
    print(f"{a.name}: {len(sa)} chars (whitespace removed)")
    print(f"{b.name}: {len(sb)} chars (whitespace removed)")
    if sa == sb:
        print("IDENTICAL: no text content lost or reordered")
        return 0
    # report the first divergence
    limit = min(len(sa), len(sb))
    for i in range(limit):
        if sa[i] != sb[i]:
            lo = max(0, i - 40)
            print(f"first difference at char {i}")
            print(f"  A: ...{sa[lo:i + 40]}...")
            print(f"  B: ...{sb[lo:i + 40]}...")
            break
    else:
        print(f"prefix identical; length differs by {len(sb) - len(sa)}")
        print(f"  tail A: {sa[limit - 60:limit]}")
        print(f"  tail B: {sb[limit - 60:len(sb)]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
