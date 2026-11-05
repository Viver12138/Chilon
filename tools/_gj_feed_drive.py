"""Do feed posts carry file links in extra_data.drive? A public path to files."""

from __future__ import annotations

import json
import sys
import urllib.request

HEADERS = {
    "AppFingerprint": "bidai",
    "PlatformName": "h5",
    "AppVersion": "7900",
    "WgtVersion": "7900",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}
BASE = "https://api.gaojiua.com/release/api/forum/topic/list/"


def page(number: int) -> list[dict]:
    url = f"{BASE}?item_type=5&page={number}&page_size=20&scene=0&scene_item=middle"
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8")).get("topics") or []


def main() -> int:
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    seen = 0
    with_drive = 0
    with_files = 0
    samples: list[str] = []
    math_mock = 0

    for number in range(1, pages + 1):
        topics = page(number)
        if not topics:
            break
        seen += len(topics)
        for topic in topics:
            extra = topic.get("extra_data") or {}
            drive = extra.get("drive") or []
            space = topic.get("share_space") or {}
            tags = " ".join(space.get("tags") or [])
            title = space.get("title") or ""
            if drive:
                with_drive += 1
                for entry in drive:
                    if isinstance(entry, dict) and entry.get("file_url"):
                        with_files += 1
                        if len(samples) < 5:
                            samples.append(entry.get("file_url"))
            if "数学" in (title + tags) and any(k in (title + tags) for k in ("模拟", "优质模拟", "联考")):
                math_mock += 1
                if len(samples) < 8:
                    samples.append(f"[space] {title} | {tags}")

    print(f"topics scanned     : {seen}")
    print(f"with drive entries : {with_drive}")
    print(f"drive file urls    : {with_files}")
    print(f"math+mock spaces    : {math_mock}")
    for line in samples:
        print("  -", line[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
