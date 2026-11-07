"""Append-only shadow observation log for the H/HR router.

Set `CHILON_RETRIEVAL_SHADOW_LOG` to override the JSONL path. Logging must never
break search: any write failure is swallowed. The log stores the query and a
hashed user key, not the raw user id.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import settings

_LOCK = threading.Lock()


def log_path() -> Path:
    raw = settings.get('CHILON_RETRIEVAL_SHADOW_LOG', 'var/retrieval/shadow_events.jsonl')
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def user_hash(user_key: str) -> str:
    return hashlib.sha256((user_key or '').encode('utf-8')).hexdigest()[:12]


def _rotate(path: Path, backups: int) -> None:
    if backups <= 0:
        path.unlink(missing_ok=True)
        return
    for index in range(backups, 0, -1):
        source = path if index == 1 else path.with_name(f'{path.name}.{index - 1}')
        target = path.with_name(f'{path.name}.{index}')
        if source.exists():
            target.unlink(missing_ok=True)
            source.replace(target)


def append(event: dict) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        max_mb = max(0.0, float(settings.get('CHILON_RETRIEVAL_SHADOW_MAX_MB', '50') or 50))
        backups = max(0, int(settings.get('CHILON_RETRIEVAL_SHADOW_BACKUPS', '3') or 3))
        payload = {'ts': datetime.now(timezone.utc).isoformat(), **event}
        line = json.dumps(payload, ensure_ascii=False)
        with _LOCK:
            if max_mb and path.exists() and path.stat().st_size > max_mb * 1024 * 1024:
                _rotate(path, backups)
            with path.open('a', encoding='utf-8') as fh:
                fh.write(line + '\n')
    except Exception:  # noqa: BLE001 - observation must not break search
        pass
