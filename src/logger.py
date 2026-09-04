"""Minimal structured logging: stdlib only, one JSON line per event."""

import json
import logging
import os
import sys
from datetime import datetime, timezone

_configured = False


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": "devsec-brief",
            "logger": record.name,
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload)


def get_logger(name: str) -> logging.Logger:
    global _configured
    logger = logging.getLogger(name)
    if not _configured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root = logging.getLogger()
        root.handlers = [handler]
        root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
        _configured = True
    return logger


def bind(logger: logging.Logger, **fields) -> logging.LoggerAdapter:
    """Attach structured fields: bind(log, cache_hit=True, ms=12).info('ask')."""
    return logging.LoggerAdapter(logger, {"fields": fields})
