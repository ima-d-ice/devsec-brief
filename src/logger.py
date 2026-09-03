"""Centralized structured JSON logging with request_id correlation."""
import logging
import os
import sys
import json
import uuid
import contextvars
from datetime import datetime, timezone

# Context var for request_id correlation across async/thread boundaries
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_JSON = os.getenv("LOG_JSON", "1") == "1"  # 1 = JSON, 0 = plain


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get("") or None),
        }
        # Attach extra fields passed via extra={...}
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "process", "processName", "message", "request_id",
            ):
                # Avoid duplicating already handled fields; keep custom extras
                if key not in log_obj:
                    try:
                        json.dumps(value)  # ensure serializable
                        log_obj[key] = value
                    except Exception:
                        log_obj[key] = str(value)
        # Include stack trace if present
        if record.exc_info and record.exc_info[0] is not None:
            log_obj["exc_info"] = self.formatException(record.exc_info)
        # Remove None request_id for cleaner output
        if not log_obj.get("request_id"):
            log_obj.pop("request_id", None)
        return json.dumps(log_obj, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", request_id_var.get(""))
        rid_str = f" [{rid[:8]}]" if rid else ""
        return f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%SZ')} {record.levelname:<7} {record.name}{rid_str} - {record.getMessage()}"


def _get_formatter() -> logging.Formatter:
    return JSONFormatter() if LOG_JSON else PlainFormatter()


_configured = False

def setup_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return
    lvl = getattr(logging, (level or LOG_LEVEL), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_get_formatter())
    root = logging.getLogger()
    # Avoid duplicate handlers on reload
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)
    else:
        # Replace existing handlers formatters
        for h in root.handlers:
            h.setFormatter(_get_formatter())
    root.setLevel(lvl)
    # Quiet noisy libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    logger = logging.getLogger(name)

    # Wrap to auto-inject request_id if not provided
    orig_makeRecord = logger.makeRecord

    def makeRecord_with_request_id(*args, **kwargs):
        rv = orig_makeRecord(*args, **kwargs)
        if not hasattr(rv, "request_id"):
            rv.request_id = request_id_var.get("")
        return rv

    # Monkey-patch only once per logger
    if not hasattr(logger, "_request_id_patched"):
        logger.makeRecord = makeRecord_with_request_id  # type: ignore
        logger._request_id_patched = True  # type: ignore
    return logger


def set_request_id(rid: str | None = None) -> str:
    """Set request_id for current context, return it."""
    rid = rid or str(uuid.uuid4())
    request_id_var.set(rid)
    return rid


def clear_request_id() -> None:
    request_id_var.set("")
