"""Open the app's preview page directly and record how it fetches the document."""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

STATE = Path("D:/Chilon/var/gj_state.json")
BASE = "https://gaojiua.com/h5/#/"
CALLS: list[dict] = []


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


async def fetch_target(request) -> dict | None:
    """First math paper's 试题 file with a CDN url."""
    async def listing(pid):
        response = await request.get(
            f"/api/cloud/share/file/list/?share_id=14205&parent_id={pid}&page=1&page_size=100&order_option="
        )
        return (await response.json()).get("data") or []

    root = await listing(1293041461)
    folder = next(f for f in root if f.get("name") == "优质模拟")
    papers = await listing(folder["id"])
    subs = await listing(papers[0]["id"])
    math = next(s for s in subs if s.get("name") == "数学")
    parts = await listing(math["id"])
    part = next(p for p in parts if p.get("name") == "试题")
    files = await listing(part["id"])
    return files[0] if files else None


async def main() -> int:
    async with async_playwright() as p:
        request = await p.request.new_context(
            base_url="https://api.gaojiua.com/release",
            extra_http_headers=headers(),
            storage_state=str(STATE),
        )
        target = await fetch_target(request)
        await request.dispose()
        if target is None:
            print("no target file")
            return 1
        print("target:", target.get("name"), target.get("file_url")[:80])
        info = {
            "id": target.get("id"),
            "name": target.get("name"),
            "file_url": target.get("file_url"),
            "extension": target.get("extension"),
            "size": target.get("size"),
            "file_type": target.get("file_type"),
        }
        url = BASE + "cloud/previewByImage?fileInfo=" + urllib.parse.quote(json.dumps(info))

        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(
            storage_state=str(STATE), viewport={"width": 1000, "height": 1400}
        )
        page = await context.new_page()

        async def on_response(response):
            host = response.url.split("/")[2] if "//" in response.url else ""
            if "gaojiua" not in host:
                return
            CALLS.append(
                {
                    "status": response.status,
                    "url": response.url,
                    "type": response.headers.get("content-type", ""),
                }
            )

        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(6000)
        await page.screenshot(path="var/_gaojiua/preview.png")

        print(f"\nrequests: {len(CALLS)}")
        for call in CALLS:
            print(f"  {call['status']} {call['type'][:22]:24} {call['url'][:120]}")
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
