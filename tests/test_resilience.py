"""Unit tests for bounded retries, circuit breaking and rate limiting."""

import threading
import time
from dataclasses import replace

import pytest

from src import groq_pool
from src.resilience import (
    CircuitBreaker,
    RetryPolicy,
    TokenBucketLimiter,
    UpstreamUnavailable,
    retry_call,
)


def test_groq_total_deadline_bounds_model_fallbacks(monkeypatch):
    fake_settings = replace(
        groq_pool.settings,
        groq_total_timeout_seconds=0.2,
        groq_backoff_base_seconds=0.01,
        groq_max_attempts=3,
    )
    monkeypatch.setattr(groq_pool, "settings", fake_settings)
    monkeypatch.setattr(
        groq_pool,
        "_CIRCUIT",
        CircuitBreaker("deadline-test", failure_threshold=99, recovery_seconds=1),
    )

    pool = object.__new__(groq_pool.GroqKeyPool)
    pool._lock = threading.Lock()
    pool._current_index = 0
    pool.keys = [groq_pool.KeyState("test-key", 1)]

    def slow_failure(client, **kwargs):
        _ = client, kwargs
        time.sleep(0.05)
        raise TimeoutError("timed out")

    started = time.monotonic()
    with pytest.raises(UpstreamUnavailable, match="deadline"):
        pool.execute_with_fallback(slow_failure)
    assert time.monotonic() - started < 1.0


def test_groq_key_state_sets_explicit_default_base_url(monkeypatch):
    captured = {}

    class FakeGroq:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(groq_pool, "Groq", FakeGroq)
    monkeypatch.setattr(
        groq_pool, "settings", replace(groq_pool.settings, groq_base_url=None)
    )

    groq_pool.KeyState("test-key", 1)

    assert captured["base_url"] == groq_pool.DEFAULT_GROQ_BASE_URL
    assert captured["base_url"].startswith("https://")


def test_circuit_breaker_opens_and_half_opens():
    now = [0.0]
    breaker = CircuitBreaker(
        "test", failure_threshold=2, recovery_seconds=10, clock=lambda: now[0]
    )
    assert breaker.allow() is True
    breaker.record_failure()
    assert breaker.allow() is True
    breaker.record_failure()
    assert breaker.state == CircuitBreaker.OPEN
    assert breaker.allow() is False

    now[0] = 11.0
    assert breaker.allow() is True
    assert breaker.state == CircuitBreaker.HALF_OPEN
    breaker.record_success()
    assert breaker.state == CircuitBreaker.CLOSED


def test_retry_is_bounded_and_backs_off():
    calls = []
    sleeps = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")
        return "ok"

    result = retry_call(
        flaky,
        RetryPolicy(attempts=3, base_delay_seconds=0.01, jitter_seconds=0),
        sleep=sleeps.append,
    )
    assert result == "ok"
    assert len(calls) == 3
    assert len(sleeps) == 2


def test_retry_does_not_swallow_non_retryable():
    def bad():
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        retry_call(
            bad,
            RetryPolicy(attempts=3, retry_on=(RuntimeError,)),
        )


def test_token_bucket_refills():
    now = [0.0]
    limiter = TokenBucketLimiter(
        rate_per_minute=60, burst=2, clock=lambda: now[0]
    )
    assert limiter.allow("client") is True
    assert limiter.allow("client") is True
    assert limiter.allow("client") is False
    now[0] = 1.1
    assert limiter.allow("client") is True
