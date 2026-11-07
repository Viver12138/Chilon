"""In-process guardrails for retrieval API/tool traffic.

This is intentionally simple for the first release (single process):
  * per-user sliding-window rate limit;
  * per-user daily query/HR quotas;
  * a global concurrency cap lives in `routed_retrieval` (covers API + agent).

For multi-process deployment these counters need Redis or a gateway limiter;
the interface is kept small so that swap is local.
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


def _int(name: str, default: int) -> int:
    try:
        return max(0, int(settings.get(name, str(default)) or default))
    except ValueError:
        return default


def check_and_record(user_key: str, mode: str = 'auto') -> None:
    """Raise RateLimited/QuotaExceeded before doing any expensive work."""
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


def note_mode(user_key: str, mode: str) -> None:
    """Record an auto-selected HR result (quota is checked on the next request)."""
    if mode == 'HR':
        with _LOCK:
            _DAILY_HR[(date.today(), user_key)] += 1


def snapshot(user_key: str) -> dict:
    today = date.today()
    with _LOCK:
        return {
            'daily_queries': _DAILY[(today, user_key)],
            'daily_hr': _DAILY_HR[(today, user_key)],
            'minute_window': len(_MINUTE[user_key]),
        }
