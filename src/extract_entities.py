import json
from pathlib import Path
from src.groq_client import safe_groq_call, set_api_key
from src.db import get_conn
from src.sanitize import sanitize_definition
from src.logger import get_logger
from dotenv import load_dotenv
import os

logger = get_logger(__name__)

load_dotenv()

def _all_keys() -> list[str]:
    """Deduplicated list of every GROQ API key present in the environment."""
    seen = set()
    keys = []
    for name in sorted(os.environ):
        if name.startswith("GROQ_API_KEY") and os.environ[name]:
            val = os.environ[name]
            if val not in seen:
                seen.add(val)
                keys.append(val)
    return keys

_keys = _all_keys()
_key_idx = 0

def _next_key() -> str:
    """Return the next key in round-robin order, advancing the pointer."""
    global _key_idx
    if not _keys:
        raise RuntimeError("No GROQ API keys available")
    key = _keys[_key_idx % len(_keys)]
    _key_idx = (_key_idx + 1) % len(_keys)
    set_api_key(key)
    return key

def _drop_key(key: str):
    """Remove a dead key from the rotation pool."""
    if key in _keys:
        _keys.remove(key)
        logger.warning("extract_drop_key", extra={"key_suffix": key[-6:], "pool_size": len(_keys)})

if _keys:
    logger.info("extract_key_pool", extra={"pool_size": len(_keys)})

GLOSSARY_PATH = Path(__file__).resolve().parents[1] / "data" / "entity_glossary.json"
MODEL = "llama-3.3-70b-versatile"

def get_articles():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, summary FROM articles")
            rows = cur.fetchall()
            col_names = [desc[0] for desc in cur.description]
            dict_rows = [dict(zip(col_names, row)) for row in rows]
    return [{"title": row["title"], "summary": row["summary"]} for row in dict_rows]

_last_error = ""

def extract_entities_from_batch(batch: list[dict]) -> dict:
    system_prompt = (
        "You are an expert cybersecurity entity extractor. "
        "Extract all proper nouns, zero-day codenames (e.g., 'LegacyHive'), "
        "threat actors (e.g., 'O-UNC-066'), CVEs, and specific software names from the provided text. "
        "For each entity, provide a short 1-2 sentence technical definition or list of aliases. "
        "Return the output STRICTLY as a JSON object where keys are the entities and values are the definitions/aliases. "
        "Example: {'LegacyHive': 'Windows User Profile Service (ProfSvc) registry elevation of privilege vulnerability'}"
    )

    text_to_process = ""
    for a in batch:
        text_to_process += f"Title: {a['title']}\nSummary: {a['summary']}\n\n"

    global _last_error
    try:
        completion = safe_groq_call(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Extract entities as a JSON dict from the following text:\n\n{text_to_process}"}
            ],
            temperature=0.1,
            max_tokens=2000
        )
        content = completion.choices[0].message.content
        import re
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(content)
    except Exception as e:
        _last_error = str(e)
        logger.warning("extract_batch_failed", extra={"error": str(e)[:300]})
        return {}

def _extract_with_retry(batch: list[dict]) -> dict:
    """Extract entities. On a dead key (401), drop it and retry with the next key."""
    attempts = max(1, len(_keys))
    for _ in range(attempts):
        key = _next_key()
        entities = extract_entities_from_batch(batch)
        if entities:
            return entities
        if "401" in _last_error or "Invalid API Key" in _last_error:
            _drop_key(key)
            continue
        return {}
    return {}

def main():
    articles = get_articles()
    logger.info("extract_start", extra={"articles": len(articles)})
    
    batch_size = 3
    glossary = {}
    
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        logger.info("extract_batch", extra={"batch": i//batch_size + 1, "size": len(batch)})
        entities = _extract_with_retry(batch)
        glossary.update({k: sanitize_definition(v) for k, v in entities.items()})
        import time
        time.sleep(18)
        
    logger.info("extract_complete", extra={"entities": len(glossary)})
    
    with open(GLOSSARY_PATH, 'w') as f:
        json.dump(glossary, f, indent=2)
    logger.info("extract_saved", extra={"path": str(GLOSSARY_PATH), "entities": len(glossary)})

if __name__ == "__main__":
    main()
