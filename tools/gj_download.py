"""Download the 优质模拟 math papers (试题 + 答案) from the user's session.

Volume and pacing are deliberate: sequential, with a delay between calls. This is the
user's own account; hammering the API risks it.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

STATE = Path("D:/Chilon/var/gj_state.json")
DEST = Path("D:/Chilon/corpus/mock-exams")
SHARE_ID = 14205
ROOT_FOLDER = 1293041461
DELAY = 1.2


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


def safe(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    return re.sub(r"\s+", " ", name).strip()[:120]


async def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = []
    async with async_playwright() as p:
        request = await p.request.new_context(
            base_url="https://api.gaojiua.com/release",
            extra_http_headers=headers(),
            storage_state=str(STATE),
        )

        async def listing(parent_id: int):
            response = await request.get(
                f"/api/cloud/share/file/list/?share_id={SHARE_ID}&parent_id={parent_id}"
                f"&page=1&page_size=100&order_option="
            )
            return (await response.json()).get("data") or []

        root = await listing(ROOT_FOLDER)
        folder = next(f for f in root if f.get("name") == "优质模拟")
        papers = await listing(folder["id"])
        print(f"papers: {len(papers)}")

        for index, paper in enumerate(papers, 1):
            title = safe(paper.get("name") or f"paper-{index}")
            subjects = await listing(paper["id"])
            math = next((s for s in subjects if s.get("name") == "数学"), None)
            if math is None:
                print(f"  [{index}] {title[:40]} — 无数学")
                continue
            for part in await listing(math["id"]):
                part_name = part.get("name") or ""
                for item in await listing(part["id"]):
                    url = item.get("file_url")
                    if not url or item.get("extension") != "pdf":
                        continue
                    kind = "答案" if "答案" in part_name else "试题"
                    target = DEST / f"{title}__数学{kind}.pdf"
                    if target.exists():
                        continue
                    try:
                        response = await request.get(url)
                        if response.status != 200:
                            print(f"  HTTP {response.status} for {target.name[:40]}")
                            continue
                        target.write_bytes(await response.body())
                        manifest.append(
                            {
                                "paper": paper.get("name"),
                                "part": kind,
                                "file": target.name,
                                "bytes": target.stat().st_size,
                                "source": "gaojiua 共享空间/官方资料总库/优质模拟",
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"  FAIL {target.name[:40]}: {exc}")
                    await asyncio.sleep(DELAY)
            if index % 10 == 0:
                print(f"  {index}/{len(papers)} papers, {len(manifest)} files")

        await request.dispose()

    manifest_path = Path("D:/Chilon/var/gj_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(entry["bytes"] for entry in manifest)
    print(f"\ndownloaded {len(manifest)} files, {total / 1024 / 1024:.1f} MB")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
