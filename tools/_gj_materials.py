"""Walk the 笔袋 site's material sections looking for mock papers."""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright

URL = "https://gaojiua.com/h5/#/common-pages/webview/pc?redirect_params=%252F"
CALLS: list[str] = []


async def frame_with_text(page):
    for frame in page.frames:
        try:
            if (await frame.inner_text("body")).strip():
                return frame
        except Exception:  # noqa: BLE001
            continue
    return None


async def click_label(frame, page, label: str) -> bool:
    matches = frame.locator(f"text={label}")
    for index in range(await matches.count()):
        item = matches.nth(index)
        try:
            if await item.is_visible():
                await item.click(timeout=6000)
                await page.wait_for_timeout(3500)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        page.on(
            "request",
            lambda r: CALLS.append(f"{r.method} {r.url}")
            if "api.gaojiua.com" in r.url and "topic/list" not in r.url
            else None,
        )
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)

        frame = await frame_with_text(page)
        if frame is None:
            print("no app frame")
            return 1

        for label in ("资料分享", "热门资料", "中学"):
            ok = await click_label(frame, page, label)
            print(f"\n=== {label}: clicked={ok}, url={frame.url[:80]}")
            if not ok:
                continue
            text = (await frame.inner_text("body")).strip()
            print(f"text {len(text)} chars")
            print(text[:600].replace("\n", " | "))
            await page.screenshot(
                path=f"var/_gaojiua/gj_{label}.png", full_page=False
            )
            # look for mock-paper wording
            for keyword in ("模拟", "模考", "联考", "押题", "真题", "试卷"):
                if keyword in text:
                    print(f"    contains: {keyword}")

        print(f"\napi calls: {len(set(CALLS))}")
        for call in list(dict.fromkeys(CALLS))[:15]:
            print("  ", call[:130])
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
