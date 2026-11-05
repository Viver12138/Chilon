"""Are a share space's files reachable without login?

The filtered 优质模拟 library sits behind a phone login; this checks whether the
underlying share/file endpoints are public anyway.
"""

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
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__, getattr(exc, "code", None)


def main() -> int:
    # a share id taken from the public feed
    status, feed = get("/api/forum/topic/list/?item_type=5&page=1&page_size=20&scene=0&scene_item=middle")
    share_ids = []
    for topic in (feed or {}).get("topics") or []:
        space = topic.get("share_space") or {}
        if space.get("id"):
            share_ids.append(space["id"])
    print(f"feed status={status} share ids={share_ids[:5]}")

    if not share_ids:
        return 1
    share_id = share_ids[0]

    probes = [
        f"/api/cloud/share/detail/?share_id={share_id}",
        f"/api/cloud/file/list/?share_id={share_id}",
        f"/api/cloud/file/list/?share_id={share_id}&page=1&page_size=30",
        f"/api/cloud/share/file/list/?share_id={share_id}",
        f"/api/cloud/xkw/file-list/?share_id={share_id}",
    ]
    for path in probes:
        status, payload = get(path)
        if payload is None:
            print(f"{status:14} {path[:70]}")
            continue
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            n = len(data)
        elif isinstance(data, dict):
            n = len(data.get("list") or data.get("files") or [])
        else:
            n = "?"
        print(f"{status} items={n} {path[:70]}")
        if n and n != "?":
            sample = data[0] if isinstance(data, list) else (data.get("list") or [])[0]
            print("    sample keys:", list(sample.keys())[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
