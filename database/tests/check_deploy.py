"""Deployment files must agree with the application.

A deployment can rot silently: a Dockerfile that copies a path which moved, an
entrypoint that seeds a file which no longer exists, a healthcheck pointed at a route
nobody registered. None of these fail until someone runs `docker compose up`, and then
they fail in a container with no useful output.

This check reads the artifacts as text and compares them with the code. It does not
build an image — a build needs a network and a daemon, which is exactly why the rot
goes unnoticed for so long.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

problems: list[str] = []
notes: list[str] = []


def require(path: str) -> Path | None:
    target = ROOT / path
    if not target.exists():
        problems.append(f"missing file: {path}")
        return None
    return target


def main() -> int:
    dockerfile = require("Dockerfile")
    compose = require("docker-compose.yml")
    start = require("scripts/start.sh")
    seed = require("database/seed/platform_tools.sql")
    requirements = require("backend/requirements.txt")

    if dockerfile:
        text = dockerfile.read_text(encoding="utf-8")
        for copy in re.findall(r"^COPY\s+(\S+)", text, re.M):
            if copy.startswith("--"):
                continue
            if not (ROOT / copy).exists():
                problems.append(f"Dockerfile copies a path that does not exist: {copy}")
        if "HEALTHCHECK" not in text:
            problems.append("Dockerfile has no HEALTHCHECK")
        if "USER " not in text:
            problems.append("Dockerfile runs as root (no USER instruction)")
        if "urllib" not in text:
            problems.append("Dockerfile healthcheck should use the bundled interpreter, not an external tool")

    if compose:
        text = compose.read_text(encoding="utf-8")
        for service in ("db:", "app:"):
            if service not in text:
                problems.append(f"docker-compose.yml has no {service} service")
        if "service_healthy" not in text:
            problems.append("app does not wait for the database to be healthy")
        if "chilon-data:/data" not in text:
            notes.append("the app volume is not mounted at /data")
        for volume in ("chilon-pgdata", "chilon-data"):
            if f"  {volume}:" not in text:
                problems.append(f"volume {volume} is used but not declared")

    if start:
        text = start.read_text(encoding="utf-8")
        if "alembic upgrade head" not in text:
            problems.append("entrypoint does not run migrations")
        if "platform_tools.sql" not in text:
            problems.append("entrypoint does not apply the platform seed")
        if "uvicorn" not in text:
            problems.append("entrypoint does not start uvicorn")
        if "set -eu" not in text:
            problems.append("entrypoint does not fail fast (missing set -eu)")
        if seed and "seed/platform_tools.sql" not in text:
            problems.append("entrypoint seeds a file the repository does not have")

    if seed:
        text = seed.read_text(encoding="utf-8")
        if "ON CONFLICT" not in text:
            problems.append("the platform seed is not idempotent (no ON CONFLICT)")

    if requirements:
        text = requirements.read_text(encoding="utf-8")
        for needed in ("fastapi", "uvicorn", "SQLAlchemy", "psycopg", "alembic", "python-multipart"):
            if needed.lower() not in text.lower():
                problems.append(f"requirements.txt is missing {needed}")

    # the healthcheck path in the Dockerfile must exist in the application
    if dockerfile:
        match = re.search(r"http://127\.0\.0\.1:\d+(/[A-Za-z0-9_/-]*)", dockerfile.read_text(encoding="utf-8"))
        if match:
            path = match.group(1)
            main_py = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
            if f'"{path}"' not in main_py and f"'{path}'" not in main_py:
                problems.append(f"healthcheck probes {path}, which main.py does not define")
        else:
            problems.append("Dockerfile healthcheck does not probe a path")

    for note in notes:
        print(f"note: {note}")
    if problems:
        print("FAIL: deployment files disagree with the application")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("OK: Dockerfile, compose, entrypoint, seed and requirements agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
