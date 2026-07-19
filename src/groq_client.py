import time
import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not set in .env")

groq_client = Groq(api_key=GROQ_API_KEY)

def set_api_key(key: str):
    """Reinitialize the global Groq client with a different API key."""
    global groq_client
    groq_client = Groq(api_key=key)
    print(f"  [groq_client] Switched to new API key (ending ...{key[-6:]})")

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
            print(f"Rate limited (429). Waiting {wait_time} seconds before retrying...")
            time.sleep(wait_time)
            return safe_groq_call(messages, model, temperature, max_tokens, stream, _retries + 1)  # retry
        raise
