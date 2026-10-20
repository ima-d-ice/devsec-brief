"""Small, dependency-free reliability primitives.

These are deliberately explicit: bounded retries, jitter, a circuit breaker and
a token-bucket limiter. They are shared by the Groq client and the API layer so
failure policy is testable in isolation.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when a dependency circuit is open and calls must fail fast."""


class UpstreamUnavailable(RuntimeError):
    """Raised when a dependency cannot serve a request after bounded retries."""


class CircuitBreaker:
    """Thread-safe closed/open/half-open circuit breaker."""

    CLOSED = 0
    HALF_OPEN = 1
    OPEN = 2

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_seconds = max(0.1, recovery_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> int:
        with self._lock:
            return self._state

    def allow(self) -> bool:
        with self._lock:
            if self._state == self.OPEN:
                if self._clock() - self._opened_at < self.recovery_seconds:
                    return False
                self._state = self.HALF_OPEN
            return True

    def record_success(self) -> None:
        with self._lock:
            self._state = self.CLOSED
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == self.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = self.OPEN
                self._opened_at = self._clock()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state,
                "failures": self._failures,
                "opened_at": self._opened_at,
            }


@dataclass
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 5.0
    jitter_seconds: float = 0.25
    retry_on: tuple[type[BaseException], ...] = (Exception,)

    def delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter, capped."""
        exponential = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** max(0, attempt - 1)),
        )
        return exponential + random.uniform(0, self.jitter_seconds)


def retry_call(
    func: Callable[[], T],
    policy: RetryPolicy | None = None,
    *,
    should_retry: Callable[[BaseException], bool] | None = None,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``func`` with bounded retries. Re-raises the final exception."""
    policy = policy or RetryPolicy()
    last_error: BaseException | None = None
    for attempt in range(1, max(1, policy.attempts) + 1):
        try:
            return func()
        except BaseException as exc:  # noqa: BLE001 - policy decides
            last_error = exc
            if not isinstance(exc, policy.retry_on):
                raise
            if should_retry is not None and not should_retry(exc):
                raise
            if attempt >= policy.attempts:
                break
            delay = policy.delay(attempt)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)
    assert last_error is not None
    raise last_error


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


@dataclass
class TokenBucketLimiter:
    """Per-key in-process token bucket.

    Suitable for a single API container. For multi-replica deployments the
    limiter should move to a shared store; this is documented as a limitation.
    """

    rate_per_minute: int
    burst: int | None = None
    clock: Callable[[], float] = time.monotonic
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.rate_per_minute = max(0, int(self.rate_per_minute))
        self.burst = max(1, int(self.burst or max(1, self.rate_per_minute)))

    @property
    def enabled(self) -> bool:
        return self.rate_per_minute > 0

    def allow(self, key: str) -> bool:
        if not self.enabled:
            return True
        now = self.clock()
        refill_per_second = self.rate_per_minute / 60.0
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self.burst), updated_at=now)
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(
                    float(self.burst), bucket.tokens + elapsed * refill_per_second
                )
                bucket.updated_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False

    def retry_after_seconds(self, key: str) -> int:
        if not self.enabled:
            return 0
        refill_per_second = self.rate_per_minute / 60.0
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.tokens >= 1.0:
                return 0
            missing = 1.0 - bucket.tokens
            return max(1, int(missing / max(refill_per_second, 0.0001)) + 1)


def summarize_exceptions(results: Iterable[object]) -> list[str]:
    """Compact, non-sensitive exception names for run records and logs."""
    names = []
    for result in results:
        if isinstance(result, BaseException):
            names.append(type(result).__name__)
    return names
