"""Configuration loading.

Reads a `.env` file at the repository root, then falls back to the real process
environment. Real environment variables win, so deployment can override anything
without editing files.

The parser is deliberately tiny instead of pulling in python-dotenv: we need
KEY=VALUE, comments and blank lines, and nothing else. Fewer dependencies in the
one module every process loads at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # allow "quoted values" but do not require them
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        values[key] = value
    return values


_FILE_VALUES = _parse_env_file(REPO_ROOT / ".env")


def get(name: str, default: str = "") -> str:
    """Process environment first, then .env, then the default."""
    return os.environ.get(name) or _FILE_VALUES.get(name, default)


def get_int(name: str, default: int) -> int:
    raw = get(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    platform_rights_policy: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: int
    deepseek_max_retries: int
    planner: str
    ocr_provider: str
    ocr_cloud_endpoint: str
    ocr_cloud_key: str
    ocr_languages: str
    ocr_min_confidence: float
    ocr_aliyun_key_id: str
    ocr_aliyun_key_secret: str
    ocr_aliyun_image_type: str
    ocr_aliyun_subject: str
    qwen_api_key: str
    qwen_base_url: str
    qwen_region: str
    qwen_timeout_seconds: int
    qwen_embedding_model: str
    qwen_embedding_dim: int
    qwen_rerank_model: str
    qwen_rerank_top_n: int

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key) and bool(self.deepseek_base_url)

    @property
    def qwen_configured(self) -> bool:
        return bool(self.qwen_api_key) and bool(self.qwen_base_url)

    @property
    def ocr_configured(self) -> bool:
        """Whether an OCR provider would actually be able to run.

        `none` is the default and means "refuse scans, say why". Anything else must be
        able to work, otherwise the operator gets a failure at upload time instead of a
        configuration mistake at startup.
        """
        provider = (self.ocr_provider or "none").strip().lower()
        if provider == "none":
            return False
        if provider == "cloud":
            return bool(self.ocr_cloud_endpoint) and bool(self.ocr_cloud_key)
        if provider == "aliyun":
            return bool(self.ocr_aliyun_key_id) and bool(self.ocr_aliyun_key_secret)
        return True


def load() -> Settings:
    return Settings(
        database_url=get("CHILON_DATABASE_URL"),
        redis_url=get("CHILON_REDIS_URL"),
        platform_rights_policy=get("CHILON_PLATFORM_RIGHTS_POLICY", "A_classroom"),
        deepseek_api_key=get("CHILON_DEEPSEEK_API_KEY"),
        deepseek_base_url=get("CHILON_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=get("CHILON_DEEPSEEK_MODEL", "deepseek-chat"),
        deepseek_timeout_seconds=get_int("CHILON_DEEPSEEK_TIMEOUT_SECONDS", 60),
        deepseek_max_retries=get_int("CHILON_DEEPSEEK_MAX_RETRIES", 2),
        planner=get("CHILON_PLANNER", "template"),
        # OCR is off unless an operator turns it on. The cloud provider is a
        # data-egress decision, so it can never become the default by accident.
        ocr_provider=get("CHILON_OCR_PROVIDER", "none"),
        ocr_cloud_endpoint=get("CHILON_OCR_CLOUD_ENDPOINT"),
        ocr_cloud_key=get("CHILON_OCR_CLOUD_KEY"),
        ocr_languages=get("CHILON_OCR_LANGUAGES", "chi_sim+eng"),
        ocr_min_confidence=float(get("CHILON_OCR_MIN_CONFIDENCE", "0.6")),
        ocr_aliyun_key_id=get("CHILON_OCR_ALIYUN_KEY_ID"),
        ocr_aliyun_key_secret=get("CHILON_OCR_ALIYUN_KEY_SECRET"),
        ocr_aliyun_image_type=get("CHILON_OCR_ALIYUN_IMAGE_TYPE", "scan"),
        ocr_aliyun_subject=get("CHILON_OCR_ALIYUN_SUBJECT", "Math"),
        # Qwen / 百炼：embedding + rerank 都走原生 API。
        # 官方 DASHSCOPE_API_KEY 作为回退，方便直接复用百炼文档里的变量名。
        qwen_api_key=get("CHILON_QWEN_API_KEY") or get("DASHSCOPE_API_KEY"),
        qwen_base_url=get("CHILON_QWEN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"),
        qwen_region=get("CHILON_QWEN_REGION", "beijing"),
        qwen_timeout_seconds=get_int("CHILON_QWEN_TIMEOUT_SECONDS", 30),
        qwen_embedding_model=get("CHILON_QWEN_EMBEDDING_MODEL", "qwen3.7-text-embedding"),
        qwen_embedding_dim=get_int("CHILON_QWEN_EMBEDDING_DIM", 1024),
        qwen_rerank_model=get("CHILON_QWEN_RERANK_MODEL", "qwen3.7-text-rerank"),
        qwen_rerank_top_n=get_int("CHILON_QWEN_RERANK_TOP_N", 40),
    )
