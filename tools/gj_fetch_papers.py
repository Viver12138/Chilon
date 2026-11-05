"""Reconstruct the mock papers from the app's page images.

The app never serves the PDF: `/api/cloud/doc/preview/` renders it to page images on
`cdn01.gaojiua.com`. Those images are the document, so they are downloaded in page order
and stitched back into a PDF with Pillow — same content, one file per paper.

Pacing: sequential, one request at a time. It is the user's account.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import sys
import urllib.parse
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

STATE = Path("D:/Chilon/var/gj_state.json")
DEST = Path("D:/Chilon/corpus/mock-exams")
SHARE_ID = 14205
ROOT = 1293041461
DELAY = 1.0


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
    return re.sub(r"\s+", " ", name).strip()[:110]


async def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    DEST.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

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

        async def pages_of(pdf_url: str) -> list[str]:
            encoded = urllib.parse.quote(pdf_url, safe="")
            response = await request.get(
                f"/api/cloud/doc/preview/?page=1&page_size=100&url={encoded}"
            )
            payload = await response.json()
            return (payload.get("data") or {}).get("urls") or []

        root = await listing(ROOT)
        folder = next(f for f in root if f.get("name") == "优质模拟")
        papers = await listing(folder["id"])
        if limit:
            papers = papers[:limit]
        print(f"papers to process: {len(papers)}")

        for index, paper in enumerate(papers, 1):
            title = safe(paper.get("name") or f"paper-{index}")
            subjects = await listing(paper["id"])
            math = next((s for s in subjects if s.get("name") == "数学"), None)
            if math is None:
                continue
            for part in await listing(math["id"]):
                kind = "答案" if "答案" in (part.get("name") or "") else "试题"
                target = DEST / f"{title}__数学{kind}.pdf"
                if target.exists():
                    continue
                for item in await listing(part["id"]):
                    url = item.get("file_url")
                    if not url:
                        continue
                    try:
                        urls = await pages_of(url)
                        if not urls:
                            print(f"  no pages: {target.name[:50]}")
                            continue
                        images = []
                        for page_url in urls:
                            response = await request.get(page_url)
                            if response.status != 200:
                                raise RuntimeError(f"image {response.status}")
                            images.append(Image.open(io.BytesIO(await response.body())).convert("RGB"))
                            await asyncio.sleep(0.15)
                        images[0].save(
                            target,
                            save_all=True,
                            append_images=images[1:],
                            resolution=150,
                        )
                        manifest.append(
                            {
                                "paper": paper.get("name"),
                                "part": kind,
                                "file": target.name,
                                "pages": len(images),
                                "bytes": target.stat().st_size,
                                "source": "gaojiua 共享空间/官方资料总库/优质模拟",
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"  FAIL {target.name[:44]}: {exc}")
                    await asyncio.sleep(DELAY)
            if index % 10 == 0:
                print(f"  {index}/{len(papers)} papers, {len(manifest)} pdfs")

        await request.dispose()

    Path("D:/Chilon/var/gj_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(entry["bytes"] for entry in manifest)
    pages = sum(entry["pages"] for entry in manifest)
    print(f"\nbuilt {len(manifest)} pdfs, {pages} pages, {total / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
