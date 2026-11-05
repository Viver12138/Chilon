"""With the saved session, find the math mock-exam share space and inspect its files."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

STATE = Path("D:/Chilon/var/gj_state.json")


async def main() -> int:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    token = None
    for origin in state.get("origins") or []:
        for item in origin.get("localStorage") or []:
            if item.get("name") == "vuex":
                token = json.loads(item["value"]).get("token")
    print("token:", "set" if token else "MISSING")

    headers = {
        "AppFingerprint": "bidai",
        "PlatformName": "h5",
        "AppVersion": "7900",
        "WgtVersion": "7900",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}" if token else "",
    }
    base = "https://api.gaojiua.com/release"

    async with async_playwright() as p:
        request = await p.request.new_context(
            base_url=base, extra_http_headers=headers, storage_state=str(STATE)
        )

        for tags in ("高中", "高中,数学", "高中,数学,优质模拟"):
            response = await request.get(f"/api/cloud/share/list/?page=1&page_size=20&tags={tags}")
            payload = await response.json()
            items = payload.get("data") or []
            print(f"\n=== tags={tags}: {len(items)} space(s)")
            for item in items[:6]:
                print(f"   [{item.get('id')}] {item.get('title')} | {' '.join(item.get('tags') or [])[:50]}")

        # inspect one space's file list
        share_id = 14205
        info = await (await request.get(f"/api/cloud/share/info/?share_id={share_id}")).json()
        data = info.get("data") or {}
        print(f"\nshare {share_id}: {data.get('title')} parent_file_id={data.get('share_file_id')}")

        listing = await (
            await request.get(
                f"/api/cloud/share/file/list/?share_id={share_id}"
                f"&parent_id={data.get('share_file_id')}&page=1&page_size=20&order_option="
            )
        ).json()
        files = listing.get("data") or []
        print(f"files in root: {len(files)}")
        if files:
            print("item keys:", list(files[0].keys()))
            print(json.dumps(files[0], ensure_ascii=False)[:600])
            for item in files[:8]:
                print(f"   {item.get('name')[:50]:52} type={item.get('file_type')} page={item.get('page_num')}")
        await request.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
