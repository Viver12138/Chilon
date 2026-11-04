#!/bin/sh
# Container entrypoint: wait for the database, migrate, seed, serve.
#
# Every step is idempotent and runs on **every** start, not only the first:
#   - `alembic upgrade head` is a no-op when the database is current;
#   - the platform seed uses ON CONFLICT DO NOTHING;
#   - the server starts last, so a failed migration never leaves a half-serving
#     process behind.
set -eu

: "${CHILON_DATABASE_URL:?CHILON_DATABASE_URL is required}"

# psycopg is already installed, so the wait and the seed both use it. `pg_isready`
# is not in this image: it ships with the postgres client, not with libpq.
python - <<'PY'
import os
import sys
import time

import psycopg

url = os.environ["CHILON_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
for attempt in range(1, 61):
    try:
        with psycopg.connect(url, connect_timeout=3):
            print("==> database is reachable")
            sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "not yet"
        print(f"    waiting ({attempt}/60): {exc}", file=sys.stderr)
        time.sleep(2)
print("database did not become reachable after 60 attempts", file=sys.stderr)
sys.exit(1)
PY

echo "==> applying migrations"
cd /app/backend
alembic upgrade head

echo "==> seeding platform tools (idempotent)"
python - <<'PY'
import os

import psycopg

url = os.environ["CHILON_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
with open("/app/database/seed/platform_tools.sql", encoding="utf-8") as handle:
    sql = handle.read()
with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
    cur.execute(sql)
print("    ok")
PY

echo "==> starting the server"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${CHILON_PORT:-8000}" \
  --proxy-headers
