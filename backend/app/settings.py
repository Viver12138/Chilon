"""Configuration loading.

Values are read from the environment; nothing is hard-coded here on purpose so
deployment can override without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    platform_rights_policy: str = "A_classroom"


def load() -> Settings:
    return Settings(
        database_url=os.environ.get("CHILON_DATABASE_URL", ""),
        redis_url=os.environ.get("CHILON_REDIS_URL", ""),
        platform_rights_policy=os.environ.get("CHILON_PLATFORM_RIGHTS_POLICY", "A_classroom"),
    )
