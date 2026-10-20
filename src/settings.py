"""Environment-backed runtime settings.

No third-party settings library is required: the surface area is small and
keeping configuration explicit makes the container contract easy to audit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace


def _str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    groq_base_url: str | None
    groq_timeout_seconds: float
    groq_total_timeout_seconds: float
    groq_max_attempts: int
    groq_backoff_base_seconds: float
    groq_cooldown_seconds: float
    circuit_failure_threshold: int
    circuit_recovery_seconds: float
    sse_heartbeat_seconds: float
    sse_max_duration_seconds: float
    readiness_cache_seconds: float
    readiness_db_timeout_seconds: float
    refresh_interval_hours: float
    api_key: str | None
    rate_limit_per_minute: int
    cache_enabled: bool
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=_str(
                "DATABASE_URL", "postgresql://devsec:devsec@localhost:5432/devsec"
            )
            or "postgresql://devsec:devsec@localhost:5432/devsec",
            groq_base_url=_str("GROQ_BASE_URL"),
            groq_timeout_seconds=_float("GROQ_TIMEOUT_SECONDS", 45.0),
            groq_total_timeout_seconds=_float("GROQ_TOTAL_TIMEOUT_SECONDS", 90.0),
            groq_max_attempts=_int("GROQ_MAX_ATTEMPTS", 3),
            groq_backoff_base_seconds=_float("GROQ_BACKOFF_BASE_SECONDS", 0.5),
            groq_cooldown_seconds=_float("GROQ_COOLDOWN_SECONDS", 10.0),
            circuit_failure_threshold=_int("CIRCUIT_FAILURE_THRESHOLD", 5),
            circuit_recovery_seconds=_float("CIRCUIT_RECOVERY_SECONDS", 30.0),
            sse_heartbeat_seconds=_float("SSE_HEARTBEAT_SECONDS", 15.0),
            sse_max_duration_seconds=_float("SSE_MAX_DURATION_SECONDS", 300.0),
            readiness_cache_seconds=_float("READINESS_CACHE_SECONDS", 5.0),
            readiness_db_timeout_seconds=_float("READINESS_DB_TIMEOUT_SECONDS", 2.0),
            refresh_interval_hours=_float("REFRESH_INTERVAL_HOURS", 6.0),
            api_key=_str("API_KEY"),
            rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 0),
            cache_enabled=_bool("CACHE_ENABLED", True),
            log_level=(_str("LOG_LEVEL", "INFO") or "INFO").upper(),
        )


settings = Settings.from_env()


def reload_settings() -> Settings:
    """Re-read environment variables. Intended for tests and local tooling."""
    global settings
    settings = replace(Settings.from_env())
    return settings
