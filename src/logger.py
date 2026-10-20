"""Structured JSON logging: stdlib only, one JSON line per event.

Every request binds a correlation ID into a ContextVar so async/sync handlers,
threads and background work can correlate log lines without passing IDs around.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
_configured = False


def set_request_id(value: str) -> None:
    _request_id.set(value or "-")


def get_request_id() -> str:
    return _request_id.get()


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": "devsec-brief",
            "env": os.getenv("APP_ENV", "local"),
            "logger": record.name,
            "request_id": get_request_id(),
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exception_type"] = getattr(exc_type, "__name__", "Exception")
            payload["exception_message"] = str(exc_value)[:500]
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    global _configured
    logger = logging.getLogger(name)
    if not _configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root = logging.getLogger()
        root.handlers = [handler]
        root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
        # Keep noisy dependency loggers from flooding the structured stream.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        _configured = True
    return logger


def bind(logger: logging.Logger, **fields) -> logging.LoggerAdapter:
    """Attach structured fields: bind(log, cache_hit=True, ms=12).info('ask')."""
    return logging.LoggerAdapter(logger, {"fields": fields})
