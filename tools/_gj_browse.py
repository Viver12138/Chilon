"""With the user's session, apply the 优质模拟 filter and record what the API returns."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://gaojiua.com/h5/#/common-pages/webview/pc?redirect_params=%252F"
STATE = Path("D:/Chilon/var/gj_state.json")
OUT = Path("D:/Chilon/var/gj_probe.json")

CALLS: list[dict] = []


async def visible_click(frame, page, label: str, timeout: int = 6000) -> bool:
    matches = frame.locator(f"text={label}")
    for index in range(await matches.count()):
        item = matches.nth(index)
        try:
            if await item.is_visible():
                await item.click(timeout=timeout)
                await page.wait_for_timeout(1500)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(
            storage_state=str(STATE), viewport={"width": 1280, "height": 1200}
        )
        page = await context.new_page()

        async def on_response(response):
            if "api.gaojiua.com" not in response.url:
                return
            if response.request.method == "OPTIONS":
                return
            try:
                body = await response.text()
            except Exception:  # noqa: BLE001
                body = ""
            CALLS.append(
                {
                    "method": response.request.method,
                    "url": response.url,
                    "status": response.status,
                    "sample": body[:400],
                }
            )

        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4500)

        frame = None
        for candidate in page.frames:
            try:
                if (await candidate.inner_text("body")).strip():
                    frame = candidate
                    break
            except Exception:  # noqa: BLE001
                continue
        if frame is None:
            print("no frame")
            return 1

        steps = [
            ("共享空间", True),
            ("高中", True),
            ("数学", True),
            ("优质模拟", False),
            ("优质试卷", False),
            ("确认", True),
        ]
        for label, required in steps:
            ok = await visible_click(frame, page, label)
            print(f"click {label}: {ok}")
            await page.wait_for_timeout(1500)

        await page.wait_for_timeout(5000)
        text = (await frame.inner_text("body")).strip()
        print(f"\npage text ({len(text)} chars):")
        print(text[:1200])
        await page.screenshot(path="var/_gaojiua/gj_filtered.png")

        interesting = [c for c in CALLS if any(k in c["url"] for k in ("cloud", "file", "share", "tag", "tag"))]
        print(f"\ncloud/file calls: {len(interesting)}")
        for call in interesting[:12]:
            print(f"  {call['status']} {call['url'][:110]}")

        OUT.write_text(json.dumps(CALLS, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nall calls saved to {OUT}")
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
