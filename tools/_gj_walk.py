"""Walk 官方资料总库 → 优质模拟 and report what mock papers are actually there."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

STATE = Path("D:/Chilon/var/gj_state.json")
SHARE_ID = 14205


def headers() -> dict[str, str]:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    token = None
    for origin in state.get("origins") or []:
        for item in origin.get("localStorage") or []:
            if item.get("name") == "vuex":
                token = json.loads(item["value"]).get("token")
    return {
        "AppFingerprint": "bidai",
        "PlatformName": "h5",
        "AppVersion": "7900",
        "WgtVersion": "7900",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }


async def main() -> int:
    async with async_playwright() as p:
        request = await p.request.new_context(
            base_url="https://api.gaojiua.com/release",
            extra_http_headers=headers(),
            storage_state=str(STATE),
        )

        async def listing(parent_id: int, page: int = 1, size: int = 100):
            response = await request.get(
                f"/api/cloud/share/file/list/?share_id={SHARE_ID}&parent_id={parent_id}"
                f"&page={page}&page_size={size}&order_option="
            )
            payload = await response.json()
            return payload.get("data") or [], payload.get("nomore")

        root = 1293041461
        folders, _ = await listing(root)
        target = next((f for f in folders if f.get("name") == "优质模拟"), None)
        print(f"root folders: {[f.get('name') for f in folders]}")
        if target is None:
            print("no 优质模拟 folder")
            return 1
        print(f"优质模拟 folder id={target['id']}")

        level1, _ = await listing(target["id"])
        print(f"\n优质模拟 has {len(level1)} entries:")
        for entry in level1[:20]:
            kind = "dir" if entry.get("file_type") == 1 else entry.get("extension")
            print(f"   [{entry['id']}] {entry.get('name')[:40]:42} {kind}")

        # descend one level into each subfolder and count files
        total_files = 0
        math_files = []
        for entry in level1:
            if entry.get("file_type") != 1:
                continue
            children, _ = await listing(entry["id"])
            pdfs = [c for c in children if c.get("extension") == "pdf"]
            total_files += len(pdfs)
            print(f"   {entry.get('name')[:24]:26} -> {len(children)} entries ({len(pdfs)} pdf)")
            if "数学" in (entry.get("name") or ""):
                math_files.extend(pdfs)
            await asyncio.sleep(0.4)

        print(f"\ntotal pdf under 优质模拟 (one level): {total_files}")
        if math_files:
            print(f"math pdfs: {len(math_files)}")
            for item in math_files[:15]:
                print(f"   {item.get('name')[:60]:62} {item.get('size', 0) / 1024 / 1024:5.1f} MB")
        await request.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
