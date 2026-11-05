"""Open 共享空间 → 内容结构 → 高中/数学/优质模拟, with a screenshot at each step."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://gaojiua.com/h5/#/common-pages/webview/pc?redirect_params=%252F"
STATE = Path("D:/Chilon/var/gj_state.json")
OUT = Path("D:/Chilon/var/gj_filter_calls.json")
SHOTS = Path("D:/Chilon/var/_gaojiua")

CALLS: list[dict] = []


async def click(frame, page, label: str) -> bool:
    matches = frame.locator(f"text={label}")
    for index in range(await matches.count()):
        item = matches.nth(index)
        try:
            if await item.is_visible():
                await item.click(timeout=6000)
                await page.wait_for_timeout(1800)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def shot(page, frame, name: str) -> None:
    text = ""
    try:
        text = (await frame.inner_text("body")).strip()
    except Exception:  # noqa: BLE001
        pass
    await page.screenshot(path=str(SHOTS / f"{name}.png"))
    print(f"   [{name}] url={frame.url[:70]} text={len(text)} :: {text[:120].replace(chr(10), ' | ')}")


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
            try:
                body = await response.text()
            except Exception:  # noqa: BLE001
                body = ""
            CALLS.append(
                {
                    "status": response.status,
                    "url": response.url,
                    "sample": body[:300],
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

        print("step 1: 共享空间")
        print("   clicked:", await click(frame, page, "共享空间"))
        await page.wait_for_timeout(3000)
        await shot(page, frame, "s1_share")

        print("step 2: 内容结构")
        print("   clicked:", await click(frame, page, "内容结构"))
        await page.wait_for_timeout(3000)
        await shot(page, frame, "s2_filter")

        for label in ("高中", "数学", "优质模拟", "确认"):
            print(f"step: {label}")
            print("   clicked:", await click(frame, page, label))
            await page.wait_for_timeout(1200)
            await shot(page, frame, f"s3_{label}")

        await page.wait_for_timeout(4000)
        text = (await frame.inner_text("body")).strip()
        print(f"\nfinal text ({len(text)} chars):")
        print(text[:1500])

        cloud = [c for c in CALLS if any(k in c["url"] for k in ("cloud", "share", "tag", "filter"))]
        print(f"\ncloud/share calls: {len(cloud)}")
        for call in cloud[:15]:
            print(f"  {call['status']} {call['url'][:110]}")
            print(f"      {call['sample'][:160]}")
        OUT.write_text(json.dumps(CALLS, ensure_ascii=False, indent=2), encoding="utf-8")
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
