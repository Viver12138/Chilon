"""Retrieval-router gray rollout decision.

This is the control plane for H/HR gray: it does not run retrieval, it returns the
QueryPlan and the mode the caller should use. Keeping it separate lets the product
API and the agent tool share one decision.

Flags:
  CHILON_RETRIEVAL_ROUTER=off|shadow|on  (default off)
  CHILON_RETRIEVAL_ROUTER_PERCENT=0..100 (default 100, used by on)
"""

from __future__ import annotations

import hashlib

from app import settings
from app.services import query_plan


def _bucket(key: str) -> int:
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
    return int(digest[:8], 16) % 100


def decide(query: str, *, user_key: str = '', flag: str | None = None,
           percent: int | None = None) -> dict:
    query = (query or '').strip()
    if not query:
        raise ValueError('query is empty')
    plan = query_plan.build_plan(query)
    auto_mode = query_plan.preferred_mode(plan)
    flag = (flag if flag is not None else settings.get('CHILON_RETRIEVAL_ROUTER', 'off')).lower()
    if flag not in ('off', 'shadow', 'on'):
        flag = 'off'
    if percent is None:
        try:
            percent = int(settings.get('CHILON_RETRIEVAL_ROUTER_PERCENT', '100'))
        except ValueError:
            percent = 100
    percent = max(0, min(100, percent))
    bucket = _bucket(f'{user_key}|{query}')

    if flag == 'off':
        mode = 'H'
        shadow = None
    elif flag == 'shadow':
        mode = 'H'
        shadow = auto_mode
    else:  # on
        mode = auto_mode if bucket < percent else 'H'
        shadow = None

    return {
        'query': query,
        'mode': mode,
        'auto_mode': auto_mode,
        'shadow_mode': shadow,
        'router_flag': flag,
        'rollout_bucket': bucket,
        'rollout_percent': percent,
        'plan': plan,
    }
