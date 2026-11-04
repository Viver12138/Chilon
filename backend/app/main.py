"""Application entry point.

Only a health endpoint exists so the skeleton can boot; business routes are added
after Phase 2 (database foundation) and Phase 3 (domain services).
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Chilon", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
