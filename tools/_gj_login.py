"""Open a real browser window for the user to log in, then save the session.

The login step is the user's: a phone number and an SMS code cannot be handled here, and
typing them for someone would be acting on credentials I have no business holding. Once
the session exists in this window, later steps reuse it.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://gaojiua.com/h5/#/common-pages/webview/pc?redirect_params=%252F"
STATE = Path("D:/Chilon/var/gj_state.json")
LOG = Path("D:/Chilon/var/gj_login.log")


def say(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


async def app_frame(page):
    for frame in page.frames:
        try:
            if (await frame.inner_text("body")).strip():
                return frame
        except Exception:  # noqa: BLE001
            continue
    return None


async def logged_in(page) -> bool:
    """The app keeps its session in localStorage `vuex`; until `user_id` is set there is
    no login. Checking page text gave a false positive while the shell was still loading.
    """
    for frame in page.frames:
        if "gaojiua.com" not in (frame.url or ""):
            continue
        try:
            raw = await frame.evaluate("localStorage.getItem('vuex')")
        except Exception:  # noqa: BLE001
            continue
        if not raw:
            continue
        try:
            state = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if state.get("user_id") or state.get("token"):
            return True
    return False


async def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False)
        context = await browser.new_context(viewport={"width": 1280, "height": 950})
        page = await context.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        say("浏览器已打开。请在窗口里用手机号登录（我不会接触验证码）。")
        say("登录成功后我会自动保存会话并继续。")

        deadline = time.time() + 900  # 15 minutes to log in
        while time.time() < deadline:
            await asyncio.sleep(5)
            if await logged_in(page):
                break
        else:
            say("等待超时：未检测到登录状态，退出。")
            await browser.close()
            return 1

        say("检测到已登录，保存会话…")
        await context.storage_state(path=str(STATE))
        say(f"会话已保存到 {STATE}")
        await page.wait_for_timeout(2000)
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
