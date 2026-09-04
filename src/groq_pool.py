import os
import random
import re
import time
import threading
from datetime import datetime, timezone
from typing import Generator
from dotenv import load_dotenv
from groq import Groq

from src.logger import get_logger

log = get_logger("groq_pool")

load_dotenv()

PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "qwen/qwen3.8-27b")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "qwen/qwen3.6-27b")
SAFETY_NET_MODEL = os.getenv("SAFETY_NET_MODEL", "openai/gpt-oss-120b")

# Free-tier thresholds per key (qwen3.8-27b / qwen3.6-27b / gpt-oss-120b class:
# 30 RPM | 1K req/day | 8K TPM | 200K TPD)
RPM_LIMIT = 30
TPM_LIMIT = 8000
RPD_LIMIT = 1000
TPD_LIMIT = 200000
COOLDOWN_SECONDS = 10

# Key sharding: serve 1-8, dataset-gen 9-10, judge/eval 11-12.
# Override with env, e.g. GROQ_SERVE_KEYS="1,2,3,4,5,6,7,8"
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


class KeyState:
    """Tracks rate limits and health for a single Groq API key."""
    def __init__(self, key: str, index: int):
        self.key = key
        self.index = index
        self.client = Groq(api_key=key)
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

        # Clean rolling 60-second window
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
    """Manages pool of Groq API keys with round-robin rotation, rate limiting, and model fallback."""
    def __init__(self):
        self._lock = threading.Lock()
        self._current_index = 0
        self.keys: list[KeyState] = []

        # Load GROQ_API_KEY_1 through GROQ_API_KEY_12
        for i in range(1, 13):
            val = os.getenv(f"GROQ_API_KEY_{i}")
            if val and val.strip():
                self.keys.append(KeyState(val.strip(), i))

        # Fallback to single GROQ_API_KEY if numbered keys not present
        if not self.keys:
            single = os.getenv("GROQ_API_KEY")
            if single and single.strip():
                self.keys.append(KeyState(single.strip(), 1))

        if not self.keys:
            raise RuntimeError("No Groq API keys found in environment (.env)")

        log.info(f"groq pool ready keys={len(self.keys)} rpm_each={RPM_LIMIT}")

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
                self._current_index = (self._current_index + 1) % len(self.keys)
                if state.is_available():
                    return state

            # If all are cooling down, pick the one that cools down earliest
            return min(candidates, key=lambda k: k.cooldown_until)

    def execute_with_fallback(self, func, *args, role: str | None = None, messages: list[dict] | None = None, **kwargs):
        """Attempts execution across models: primary -> fallback -> safety_net."""
        models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL, SAFETY_NET_MODEL]
        last_error = None
        max_tokens = kwargs.get("max_tokens", 500)
        token_estimate = estimate_messages_tokens(messages, max_tokens) if messages else max_tokens

        for model in models_to_try:
            # Try available keys for this model
            call_kwargs = {k: v for k, v in kwargs.items() if k != "model"}
            for _ in range(len(self.keys)):
                key_state = self._get_next_key(role=role)
                try:
                    key_state.record_usage(token_estimate=token_estimate)
                    result = func(key_state.client, model=model, *args, **call_kwargs)
                    return result, model
                except Exception as e:
                    err_msg = str(e).lower()
                    last_error = e

                    if "429" in err_msg or "rate_limit" in err_msg or "rate limit" in err_msg:
                        wait = _parse_retry_after(err_msg) or COOLDOWN_SECONDS
                        wait = wait + random.uniform(0, 2.0)
                        log.warning(f"groq 429 key={key_state.index} cooldown_s={wait:.1f}")
                        key_state.trigger_cooldown(seconds=wait)
                        continue  # Try next key

                    if "model_not_found" in err_msg or "does not exist" in err_msg or "not supported" in err_msg:
                        log.warning(f"groq model unavailable model={model}")
                        break  # Break key loop to try next model

                    raise e  # Unrecoverable error

        raise RuntimeError(f"All Groq keys and fallback models failed. Last error: {last_error}")


_pool_instance = None
_pool_lock = threading.Lock()

def get_pool() -> GroqKeyPool:
    global _pool_instance
    if _pool_instance is None:
        with _pool_lock:
            if _pool_instance is None:
                _pool_instance = GroqKeyPool()
    return _pool_instance


def safe_groq_call(messages: list[dict], model: str = None, temperature: float = 0.2, max_tokens: int = 700, stream: bool = False, role: str | None = None):
    """Synchronous completion with multi-key rotation and model fallback."""
    pool = get_pool()

    def _call(client, **kwargs):
        return client.chat.completions.create(messages=messages, temperature=temperature, max_tokens=max_tokens, stream=stream, **kwargs)

    completion, used_model = pool.execute_with_fallback(_call, model=model or PRIMARY_MODEL, role=role, messages=messages)
    return completion


def stream_groq_call(messages: list[dict], model: str = None, temperature: float = 0.2, max_tokens: int = 700, role: str | None = None) -> tuple[Generator[str, None, None], str]:
    """Streaming completion returning token generator and model name."""
    pool = get_pool()

    def _stream_call(client, **kwargs):
        return client.chat.completions.create(messages=messages, temperature=temperature, max_tokens=max_tokens, stream=True, **kwargs)

    response, used_model = pool.execute_with_fallback(_stream_call, model=model or PRIMARY_MODEL, role=role, messages=messages)

    def token_generator():
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content

    return token_generator(), used_model

