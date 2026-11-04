"""FastAPI application.

Wiring only: create the engine, register routers and the single error translator.
Business rules stay in `app/services/*`, which is why this file has no `if` about
domain state in it.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import executions as executions_api
from app.api import plans as plans_api
from app.api import tasks as tasks_api
from app.api.deps import install_error_handlers
from app.db import session as db


@asynccontextmanager
async def lifespan(app: FastAPI):
    url = os.environ.get("CHILON_DATABASE_URL", "")
    if url:
        db.init(url)
    yield
    await db.dispose()


app = FastAPI(title="Chilon", version="0.1.0", lifespan=lifespan)

install_error_handlers(app)

app.include_router(tasks_api.router)
app.include_router(plans_api.router)
app.include_router(executions_api.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
