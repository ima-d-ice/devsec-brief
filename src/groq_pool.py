import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Generator

from dotenv import load_dotenv
from groq import Groq

from src import obs
from src.logger import get_logger
from src.resilience import CircuitBreaker, CircuitOpenError, UpstreamUnavailable
from src.settings import settings

log = get_logger("groq_pool")

load_dotenv()

# Model chain. Defaults are intentionally conservative; override via env.
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "qwen/qwen3.8-27b")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "qwen/qwen3.6-27b")
SAFETY_NET_MODEL = os.getenv("SAFETY_NET_MODEL", "openai/gpt-oss-120b")
# groq>=1.7 uses an empty base_url if the environment variable is present but
# blank. Compose deliberately passes GROQ_BASE_URL= for the real provider, so
# make the official endpoint explicit instead of relying on SDK defaults.
# The Groq SDK appends /openai/v1/chat/completions itself; this must be the
# host root, not the API prefix.
DEFAULT_GROQ_BASE_URL = "https://api.groq.com"

# Free-tier thresholds per key (qwen3.8-27b / qwen3.6-27b / gpt-oss-120b class:
# 30 RPM | 1K req/day | 8K TPM | 200K TPD)
RPM_LIMIT = 30
TPM_LIMIT = 8000
RPD_LIMIT = 1000
TPD_LIMIT = 200000
COOLDOWN_SECONDS = settings.groq_cooldown_seconds


def _parse_key_group(env_name: str, default: list[int]) -> list[int]:
    raw = os.getenv(env_name)
    if not raw:
        return default
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        return default


SERVE_KEYS = _parse_key_group("GROQ_SERVE_KEYS", list(range(1, 9)))
GEN_KEYS = _parse_key_group("GROQ_GEN_KEYS", [9, 10])
JUDGE_KEYS = _parse_key_group("GROQ_JUDGE_KEYS", [11, 12])
ROLE_GROUPS = {"serve": SERVE_KEYS, "gen": GEN_KEYS, "judge": JUDGE_KEYS}

_CIRCUIT = CircuitBreaker(
    "groq",
    failure_threshold=settings.circuit_failure_threshold,
    recovery_seconds=settings.circuit_recovery_seconds,
)


def _set_circuit_metric() -> None:
    obs.GROQ_CIRCUIT_STATE.set(_CIRCUIT.state)


def estimate_messages_tokens(messages: list[dict], max_tokens: int = 0) -> int:
    """Rough input+output estimate: ~4 chars per token."""
    chars = 0
    try:
        for m in messages or []:
            c = m.get("content", "") if isinstance(m, dict) else str(m)
            chars += len(c) if isinstance(c, str) else len(str(c))
    except Exception:
        chars = 0
    return chars // 4 + (max_tokens or 0)


def _parse_retry_after(err_msg: str) -> float | None:
    m = re.search(r"retry\s*(?:after|in)\s*(\d+(?:\.\d+)?)\s*s", err_msg)
    if m:
        try:
            return min(float(m.group(1)), 60.0)
        except ValueError:
            return None
    return None


def _classify_error(exc: Exception) -> str:
    """Map provider errors to a small, metric-safe outcome vocabulary."""
    status = getattr(exc, "status_code", None)
    message = str(exc).lower()
    if status == 429 or "429" in message or "rate_limit" in message or "rate limit" in message:
        return "rate_limit"
    if status is not None and 500 <= int(status) < 600:
        return "server_error"
    if "timeout" in message or "timed out" in message or "time out" in message:
        return "timeout"
    if "connection" in message or "connect" in message or "network" in message:
        return "connection_error"
    if "model_not_found" in message or "does not exist" in message or "not supported" in message:
        return "model_error"
    if status in (401, 403) or "authentication" in message or "invalid api key" in message:
        return "auth_error"
    return "other"


def _is_retryable(outcome: str) -> bool:
    return outcome in {"rate_limit", "server_error", "timeout", "connection_error"}


def _retry_delay(attempt: int) -> float:
    base = settings.groq_backoff_base_seconds * (2 ** max(0, attempt - 1))
    return min(8.0, base) + random.uniform(0, 0.5)


class KeyState:
    """Tracks rate limits and health for a single Groq API key."""

    def __init__(self, key: str, index: int):
        self.key = key
        self.index = index
        client_kwargs: dict = {
            "api_key": key,
            "base_url": settings.groq_base_url or DEFAULT_GROQ_BASE_URL,
            "timeout": settings.groq_timeout_seconds,
            "max_retries": 0,
        }
        self.client = Groq(**client_kwargs)
        self.request_timestamps: list[float] = []
        self.estimated_tokens: list[tuple[float, int]] = []
        self.cooldown_until: float = 0.0
        self.daily_day: str = self._today()
        self.daily_requests: int = 0
        self.daily_tokens: int = 0

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_day(self):
        today = self._today()
        if today != self.daily_day:
            self.daily_day = today
            self.daily_requests = 0
            self.daily_tokens = 0

    def is_available(self) -> bool:
        now = time.time()
        if now < self.cooldown_until:
            return False

        self._roll_day()
        self.request_timestamps = [t for t in self.request_timestamps if now - t < 60]
        self.estimated_tokens = [item for item in self.estimated_tokens if now - item[0] < 60]

        current_rpm = len(self.request_timestamps)
        current_tpm = sum(tokens for _, tokens in self.estimated_tokens)
        return (
            current_rpm < RPM_LIMIT
            and current_tpm < TPM_LIMIT
            and self.daily_requests < RPD_LIMIT
            and self.daily_tokens < TPD_LIMIT
        )

    def record_usage(self, token_estimate: int = 400):
        now = time.time()
        self._roll_day()
        self.request_timestamps.append(now)
        self.estimated_tokens.append((now, token_estimate))
        self.daily_requests += 1
        self.daily_tokens += token_estimate

    def trigger_cooldown(self, seconds: float = COOLDOWN_SECONDS):
        self.cooldown_until = time.time() + seconds


class GroqKeyPool:
    """Round-robin key rotation with rate limits, retries and model fallback.

    Limitation: key state is per process. A multi-worker deployment needs a
    shared limiter (Postgres/Redis); this is documented rather than hidden.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._current_index = 0
        self.keys: list[KeyState] = []

        for i in range(1, 13):
            val = os.getenv(f"GROQ_API_KEY_{i}")
            if val and val.strip():
                self.keys.append(KeyState(val.strip(), i))

        if not self.keys:
            single = os.getenv("GROQ_API_KEY")
            if single and single.strip():
                self.keys.append(KeyState(single.strip(), 1))

        if not self.keys:
            raise RuntimeError("No Groq API keys found in environment (.env)")

        log.info("groq_pool_ready", extra={"fields": {"keys": len(self.keys), "rpm_each": RPM_LIMIT}})

    def _get_next_key(self, role: str | None = None) -> KeyState:
        with self._lock:
            candidates = self.keys
            if role and role in ROLE_GROUPS:
                wanted = set(ROLE_GROUPS[role])
                filtered = [k for k in self.keys if k.index in wanted]
                if filtered:
                    candidates = filtered
            total = len(candidates)
            for _ in range(total):
                state = candidates[self._current_index % len(candidates)]
                self._current_index = (self._current_index + 1) % max(1, len(self.keys))
                if state.is_available():
                    return state
            return min(candidates, key=lambda k: k.cooldown_until)

    def execute_with_fallback(
        self,
        func,
        *args,
        role: str | None = None,
        messages: list[dict] | None = None,
        **kwargs,
    ):
        """Attempt primary -> fallback -> safety-net models within a bounded policy."""
        if not _CIRCUIT.allow():
            _set_circuit_metric()
            raise CircuitOpenError("Groq circuit is open")

        models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL, SAFETY_NET_MODEL]
        last_error: Exception | None = None
        max_tokens = kwargs.get("max_tokens", 500)
        token_estimate = estimate_messages_tokens(messages, max_tokens) if messages else max_tokens
        deadline = time.monotonic() + max(1.0, settings.groq_total_timeout_seconds)
        deadline_exceeded = False

        for model_index, model in enumerate(models_to_try):
            if time.monotonic() >= deadline:
                deadline_exceeded = True
                break
            if model_index > 0:
                obs.GROQ_FALLBACKS.labels(model=model).inc()
            call_kwargs = {k: v for k, v in kwargs.items() if k != "model"}

            for attempt in range(1, max(1, settings.groq_max_attempts) + 1):
                if time.monotonic() >= deadline:
                    deadline_exceeded = True
                    break
                key_state = self._get_next_key(role=role)
                started = time.perf_counter()
                try:
                    key_state.record_usage(token_estimate=token_estimate)
                    result = func(key_state.client, model=model, *args, **call_kwargs)
                    obs.GROQ_REQUESTS.labels(model=model, outcome="success").inc()
                    _CIRCUIT.record_success()
                    _set_circuit_metric()
                    return result, model
                except Exception as exc:  # noqa: BLE001 - classified below
                    last_error = exc
                    outcome = _classify_error(exc)
                    obs.GROQ_REQUESTS.labels(model=model, outcome=outcome).inc()

                    if outcome == "rate_limit":
                        wait = _parse_retry_after(str(exc)) or COOLDOWN_SECONDS
                        wait += random.uniform(0, 1.0)
                        key_state.trigger_cooldown(seconds=wait)
                        obs.GROQ_RATE_LIMITED.labels(key=str(key_state.index)).inc()
                        log.warning(
                            "groq_rate_limited",
                            extra={"fields": {"key": key_state.index, "cooldown_s": round(wait, 1)}},
                        )
                    elif outcome == "model_error":
                        log.warning("groq_model_unavailable", extra={"fields": {"model": model}})
                        break  # next model
                    elif outcome == "auth_error":
                        key_state.trigger_cooldown(seconds=300)
                        log.error("groq_auth_error", extra={"fields": {"key": key_state.index}})
                    elif outcome not in {"timeout", "connection_error", "server_error"}:
                        _CIRCUIT.record_failure()
                        _set_circuit_metric()
                        raise
                finally:
                    obs.GROQ_DURATION.labels(model=model).observe(
                        max(0.0, time.perf_counter() - started)
                    )

                if attempt < settings.groq_max_attempts:
                    delay = _retry_delay(attempt)
                    if time.monotonic() + delay >= deadline:
                        deadline_exceeded = True
                        break
                    log.warning(
                        "groq_retry",
                        extra={"fields": {"model": model, "attempt": attempt, "delay_s": round(delay, 2)}},
                    )
                    time.sleep(delay)

            if deadline_exceeded:
                break

        _CIRCUIT.record_failure()
        _set_circuit_metric()
        reason = (
            "total deadline exceeded"
            if deadline_exceeded
            else f"bounded retries ({type(last_error).__name__ if last_error else 'unknown'})"
        )
        raise UpstreamUnavailable(f"All Groq models failed after {reason}")


_pool_instance: GroqKeyPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> GroqKeyPool:
    global _pool_instance
    if _pool_instance is None:
        with _pool_lock:
            if _pool_instance is None:
                _pool_instance = GroqKeyPool()
    return _pool_instance


def safe_groq_call(
    messages: list[dict],
    model: str = None,
    temperature: float = 0.2,
    max_tokens: int = 700,
    stream: bool = False,
    role: str | None = None,
):
    """Synchronous completion with multi-key rotation and model fallback."""
    pool = get_pool()

    def _call(client, **kwargs):
        return client.chat.completions.create(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            **kwargs,
        )

    completion, _used_model = pool.execute_with_fallback(
        _call, model=model or PRIMARY_MODEL, role=role, messages=messages
    )
    return completion


def stream_groq_call(
    messages: list[dict],
    model: str = None,
    temperature: float = 0.2,
    max_tokens: int = 700,
    role: str | None = None,
) -> tuple[Generator[str, None, None], str]:
    """Streaming completion returning token generator and model name."""
    pool = get_pool()

    def _stream_call(client, **kwargs):
        return client.chat.completions.create(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )

    response, used_model = pool.execute_with_fallback(
        _stream_call, model=model or PRIMARY_MODEL, role=role, messages=messages
    )

    def token_generator():
        try:
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
            _CIRCUIT.record_success()
            _set_circuit_metric()
        except Exception as exc:  # noqa: BLE001 - stream failures are upstream
            _CIRCUIT.record_failure()
            _set_circuit_metric()
            obs.GROQ_REQUESTS.labels(model=used_model, outcome="stream_error").inc()
            raise UpstreamUnavailable("Groq stream interrupted") from exc

    return token_generator(), used_model
