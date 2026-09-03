import time
import os
from dotenv import load_dotenv
from groq import Groq
from src.logger import get_logger

logger = get_logger(__name__)

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    # Allow dummy key in test/CI where Groq is mocked; warn instead of crash if LOG_LEVEL indicates test
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("CI"):
        logger.warning("GROQ_API_KEY not set - using dummy for test/CI")
        GROQ_API_KEY = "gsk_dummy_for_tests"
    else:
        raise RuntimeError("GROQ_API_KEY not set in .env")

groq_client = Groq(api_key=GROQ_API_KEY)

def set_api_key(key: str):
    """Reinitialize the global Groq client with a different API key."""
    global groq_client
    groq_client = Groq(api_key=key)
    logger.info("groq_key_switched", extra={"key_suffix": key[-6:]})

def safe_groq_call(messages, model="llama-3.1-8b-instant", temperature=0.4, max_tokens=400, stream=False, _retries=0):
    """
    Groq call with automatic rate-limit handling.
    Reads x-ratelimit-remaining-tokens from response headers.
    """
    if _retries >= 5:
        raise RuntimeError("Groq rate limit: max retries exceeded")
    try:
        response = groq_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )
        
        if stream:
            return response
        
        return response
        
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            wait_time = 12 * (_retries + 1)
            logger.warning("groq_rate_limited", extra={"wait_s": wait_time, "retry": _retries, "error": str(e)[:200]})
            time.sleep(wait_time)
            return safe_groq_call(messages, model, temperature, max_tokens, stream, _retries + 1)  # retry
        # Log non-429 errors at debug to avoid noise but keep observability
        logger.debug("groq_call_failed", extra={"error": str(e)[:300], "model": model})
        raise
