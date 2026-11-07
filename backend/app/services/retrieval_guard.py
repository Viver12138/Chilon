"""Guardrails for retrieval API/tool traffic.

Backends:
  * `memory` (default): per-process counters, single instance;
  * `redis` (optional): shared per-user minute/daily counters across instances;
  * `auto`: Redis when CHILON_REDIS_URL is set and the redis package imports,
    otherwise memory.

The global concurrency cap remains per-process in `routed_retrieval`; a true
cluster-wide concurrency limiter belongs in the gateway.

Note: Redis counters are increment-first. A rejected request still increments its
window; this is deliberately conservative.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import date

from app import settings


class RateLimited(Exception):
    pass


class QuotaExceeded(Exception):
    pass


_LOCK = threading.Lock()
_MINUTE: dict[str, deque[float]] = defaultdict(deque)
_DAILY: dict[tuple[date, str], int] = defaultdict(int)
_DAILY_HR: dict[tuple[date, str], int] = defaultdict(int)
_REDIS = None
_REDIS_LOADED = False


def _int(name: str, default: int) -> int:
    try:
        return max(0, int(settings.get(name, str(default)) or default))
    except ValueError:
        return default


def _redis_client():
    global _REDIS, _REDIS_LOADED
    if _REDIS_LOADED:
        return _REDIS
    _REDIS_LOADED = True
    backend = (settings.get('CHILON_RETRIEVAL_GUARD_BACKEND', 'auto') or 'auto').lower()
    url = settings.get('CHILON_REDIS_URL')
    if backend not in ('auto', 'redis') or not url:
        return None
    try:
        import redis  # type: ignore
        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
        client.ping()
        _REDIS = client
    except Exception:  # noqa: BLE001 - optional dependency / server
        _REDIS = None
    return _REDIS


def _redis_check(client, user_key: str, mode: str) -> None:
    now = time.time()
    minute = int(now // 60)
    day = date.today().isoformat()
    minute_key = f'chilon:retrieval:rate:{user_key}:{minute}'
    daily_key = f'chilon:retrieval:daily:{user_key}:{day}'
    hr_key = f'chilon:retrieval:hr:{user_key}:{day}'
    per_minute = _int('CHILON_RETRIEVAL_RATE_PER_MIN', 30)
    daily = _int('CHILON_RETRIEVAL_DAILY_QUERIES', 500)
    daily_hr = _int('CHILON_RETRIEVAL_DAILY_HR', 100)
    is_hr = mode.lower() == 'hr'
    pipe = client.pipeline()
    pipe.incr(minute_key)
    pipe.expire(minute_key, 70)
    pipe.incr(daily_key)
    pipe.expire(daily_key, 172800)
    if is_hr:
        pipe.incr(hr_key)
        pipe.expire(hr_key, 172800)
    values = pipe.execute()
    minute_count = int(values[0])
    day_count = int(values[2])
    hr_count = int(values[4]) if is_hr else 0
    if per_minute and minute_count > per_minute:
        raise RateLimited(f'rate limit {per_minute}/min')
    if daily and day_count > daily:
        raise QuotaExceeded(f'daily query quota {daily}')
    if is_hr and daily_hr and hr_count > daily_hr:
        raise QuotaExceeded(f'daily HR quota {daily_hr}')


def _memory_check(user_key: str, mode: str) -> None:
    now = time.time()
    today = date.today()
    per_minute = _int('CHILON_RETRIEVAL_RATE_PER_MIN', 30)
    daily = _int('CHILON_RETRIEVAL_DAILY_QUERIES', 500)
    daily_hr = _int('CHILON_RETRIEVAL_DAILY_HR', 100)
    with _LOCK:
        window = _MINUTE[user_key]
        while window and window[0] < now - 60:
            window.popleft()
        if per_minute and len(window) >= per_minute:
            raise RateLimited(f'rate limit {per_minute}/min')
        if daily and _DAILY[(today, user_key)] >= daily:
            raise QuotaExceeded(f'daily query quota {daily}')
        if mode.lower() == 'hr' and daily_hr and _DAILY_HR[(today, user_key)] >= daily_hr:
            raise QuotaExceeded(f'daily HR quota {daily_hr}')
        window.append(now)
        _DAILY[(today, user_key)] += 1
        if mode.lower() == 'hr':
            _DAILY_HR[(today, user_key)] += 1


def check_and_record(user_key: str, mode: str = 'auto') -> None:
    """Raise RateLimited/QuotaExceeded before doing any expensive work."""
    client = _redis_client()
    if client is not None:
        try:
            _redis_check(client, user_key, mode)
            return
        except (RateLimited, QuotaExceeded):
            raise
        except Exception:  # noqa: BLE001 - degrade to memory on Redis outage
            pass
    _memory_check(user_key, mode)


def note_mode(user_key: str, mode: str) -> None:
    """Record an auto-selected HR result (quota is checked on the next request)."""
    if mode != 'HR':
        return
    client = _redis_client()
    if client is not None:
        try:
            key = f'chilon:retrieval:hr:{user_key}:{date.today().isoformat()}'
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, 172800)
            pipe.execute()
            return
        except Exception:  # noqa: BLE001
            pass
    with _LOCK:
        _DAILY_HR[(date.today(), user_key)] += 1


def snapshot(user_key: str) -> dict:
    today = date.today()
    client = _redis_client()
    if client is not None:
        try:
            minute = int(time.time() // 60)
            keys = [
                f'chilon:retrieval:rate:{user_key}:{minute}',
                f'chilon:retrieval:daily:{user_key}:{today.isoformat()}',
                f'chilon:retrieval:hr:{user_key}:{today.isoformat()}',
            ]
            values = client.mget(keys)
            return {
                'daily_queries': int(values[1] or 0),
                'daily_hr': int(values[2] or 0),
                'minute_window': int(values[0] or 0),
                'backend': 'redis',
            }
        except Exception:  # noqa: BLE001
            pass
    with _LOCK:
        return {
            'daily_queries': _DAILY[(today, user_key)],
            'daily_hr': _DAILY_HR[(today, user_key)],
            'minute_window': len(_MINUTE[user_key]),
            'backend': 'memory',
        }
