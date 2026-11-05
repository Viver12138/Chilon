"""Enter 共享空间 via the bottom tab and apply the 高中/数学/优质模拟 filter."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://gaojiua.com/h5/#/common-pages/webview/pc?redirect_params=%252F"
STATE = Path("D:/Chilon/var/gj_state.json")
SHOTS = Path("D:/Chilon/var/_gaojiua")
OUT = Path("D:/Chilon/var/gj_calls2.json")

CALLS: list[dict] = []


async def shot(page, name: str) -> None:
    await page.screenshot(path=str(SHOTS / f"{name}.png"))


async def click_text(frame, page, label: str) -> bool:
    matches = frame.locator(f"text={label}")
    for index in range(await matches.count()):
        item = matches.nth(index)
        try:
            if await item.is_visible():
                await item.click(timeout=5000)
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
            try:
                body = await response.text()
            except Exception:  # noqa: BLE001
                body = ""
            CALLS.append({"status": response.status, "url": response.url, "sample": body[:300]})

        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4500)

        # bottom tab bar: 首页 | 共享空间 | 填志愿 | 学习 | 我的
        await page.mouse.click(492, 1140)
        await page.wait_for_timeout(3500)
        await shot(page, "t1_entry")

        frame = None
        for candidate in page.frames:
            try:
                text = (await candidate.inner_text("body")).strip()
            except Exception:  # noqa: BLE001
                continue
            if "高中" in text and ("小学" in text or "初中" in text):
                frame = candidate
                break
        target = frame or page.frames[0]
        text = (await target.inner_text("body")).strip()
        print("entry text:", text[:300].replace("\n", " | "))

        for label in ("高中", "数学", "优质模拟", "确认"):
            ok = await click_text(target, page, label)
            print(f"click {label}: {ok}")
            await shot(page, f"t2_{label}")

        await page.wait_for_timeout(4000)
        text = (await target.inner_text("body")).strip()
        print(f"\nresult ({len(text)} chars):")
        print(text[:1200])

        cloud = [c for c in CALLS if any(k in c["url"] for k in ("cloud", "share", "file"))]
        print(f"\ncloud calls: {len(cloud)}")
        for call in cloud[:15]:
            print(f"  {call['status']} {call['url'][:110]}")
            print(f"      {call['sample'][:140]}")
        OUT.write_text(json.dumps(CALLS, ensure_ascii=False, indent=2), encoding="utf-8")
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
