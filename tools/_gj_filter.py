"""Apply the 共享空间 filter (高中 / 数学 / 优质模拟) and see what comes back."""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import async_playwright

URL = "https://gaojiua.com/h5/#/common-pages/webview/pc?redirect_params=%252F"
CALLS: list[str] = []


async def visible_click(frame, page, label: str, timeout: int = 6000) -> bool:
    matches = frame.locator(f"text={label}")
    count = await matches.count()
    for index in range(count):
        item = matches.nth(index)
        try:
            if await item.is_visible():
                await item.click(timeout=timeout)
                await page.wait_for_timeout(1200)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 1200})
        page.on(
            "request",
            lambda r: CALLS.append(f"{r.method} {r.url}")
            if "api.gaojiua.com" in r.url
            else None,
        )
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
            print("no app frame")
            return 1

        print("1. open 共享空间:", await visible_click(frame, page, "共享空间"))
        await page.wait_for_timeout(2500)
        for label in ("高中", "数学", "高三", "优质模拟"):
            ok = await visible_click(frame, page, label)
            print(f"   click {label}: {ok}")
            await page.wait_for_timeout(800)
        print("2. confirm:", await visible_click(frame, page, "确认"))
        await page.wait_for_timeout(4500)

        text = (await frame.inner_text("body")).strip()
        print(f"\nresult text ({len(text)} chars):")
        print(text[:1500])
        await page.screenshot(path="var/_gaojiua/filter_result.png", full_page=False)

        print(f"\napi calls ({len(dict.fromkeys(CALLS))}):")
        for call in list(dict.fromkeys(CALLS))[:25]:
            print("  ", call[:140])
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
