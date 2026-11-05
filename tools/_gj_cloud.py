"""Inspect the cloud file lists the 笔袋 site exposes without login."""

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
BASE = "https://api.gaojiua.com/release"


def get(path: str):
    request = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    for path in (
        "/api/cloud/file/hot-list/?time_range=1",
        "/api/cloud/file/hot-list/?time_range=2",
    ):
        try:
            payload = get(path)
        except Exception as exc:  # noqa: BLE001
            print(f"{path}: {exc}")
            continue
        print(f"\n=== {path}")
        print("keys:", list(payload.keys()))
        items = (
            payload.get("data")
            or payload.get("files")
            or payload.get("list")
            or payload.get("file_list")
            or []
        )
        if isinstance(items, dict):
            items = items.get("list") or []
        print(f"items: {len(items)}")
        for item in items[:8]:
            name = item.get("file_name") or item.get("name") or item.get("title")
            print(f"  - {name}")
            if item.get("file_id"):
                print(f"    file_id={item.get('file_id')} ext={item.get('ext')} size={item.get('file_size')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
