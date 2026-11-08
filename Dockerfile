# Chilon backend image.
#
# The image contains the code and dependencies; it does **not** contain the schema.
# DDL and seed are applied at start by scripts/start.sh, so a fresh database and an
# existing one take exactly the same path — there is no "first run vs upgrade" fork
# in the image itself.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CHILON_EXPORT_DIR=/data/exports \
    CHILON_UPLOAD_DIR=/data/uploads

# No apt packages on purpose: psycopg[binary] bundles its own libpq, and the
# healthcheck uses the interpreter that is already here. Fewer moving parts, and the
# image builds without a Debian mirror (the first build attempt failed here: apt
# could not reach a repository at all).
WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --timeout 20 --retries 2 -r backend/requirements.txt

COPY backend ./backend
COPY agent ./agent
COPY schemas ./schemas
COPY database ./database
COPY scripts ./scripts
# the operator import tool must exist inside the image: the corpus is loaded by
# running it against the deployed database, not from a developer machine
COPY tools ./tools

# a non-root runtime user: the process that reads teacher uploads must not be root
RUN useradd --create-home --uid 10001 chilon \
 && mkdir -p /data/exports /data/uploads \
 && chown -R chilon:chilon /data /app \
 && chmod +x scripts/start.sh
USER chilon

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

ENTRYPOINT ["scripts/start.sh"]
