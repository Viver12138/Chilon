"""Save the app's lazy-loaded JS so the download URL logic can be read."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://gaojiua.com/h5/#/common-pages/webview/pc?redirect_params=%252F"
STATE = Path("D:/Chilon/var/gj_state.json")
OUT = Path("D:/Chilon/var/_gj_js")


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    saved = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(
            storage_state=str(STATE), viewport={"width": 1280, "height": 1200}
        )
        page = await context.new_page()

        async def save(response):
            nonlocal saved
            ctype = (response.headers.get("content-type") or "").lower()
            if "javascript" not in ctype:
                return
            try:
                body = await response.body()
            except Exception:  # noqa: BLE001
                return
            name = response.url.split("/")[-1].split("?")[0] or f"chunk{saved}.js"
            (OUT / name).write_bytes(body)
            saved += 1

        page.on("response", lambda r: asyncio.ensure_future(save(r)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)

        # enter 共享空间 through the bottom tab, then open the 优质模拟 folder
        await page.mouse.click(492, 1140)
        await page.wait_for_timeout(4000)
        for frame in page.frames:
            try:
                if await frame.locator("text=官方资料总库").count():
                    await frame.locator("text=官方资料总库").first.click(timeout=6000)
                    await page.wait_for_timeout(3000)
                    break
            except Exception:  # noqa: BLE001
                continue
        await page.wait_for_timeout(3000)
        await page.mouse.wheel(0, 800)
        await page.wait_for_timeout(2500)
        print(f"saved {saved} js files to {OUT}")
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
