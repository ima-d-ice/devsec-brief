import json
from pathlib import Path
from src.groq_client import safe_groq_call, set_api_key
from src.db import get_conn
from dotenv import load_dotenv
import os

load_dotenv()
key_4 = os.getenv("GROQ_API_KEY_4")
if key_4:
    set_api_key(key_4)

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "articles.db"
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
        print(f"Failed to extract from batch: {e}")
        return {}

def main():
    articles = get_articles()
    print(f"Loaded {len(articles)} articles.")
    
    batch_size = 3
    glossary = {}
    
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        print(f"Processing batch {i//batch_size + 1}...", flush=True)
        entities = extract_entities_from_batch(batch)
        glossary.update(entities)
        import time
        time.sleep(18)
        
    print(f"Extracted {len(glossary)} total entities.")
    
    with open(GLOSSARY_PATH, 'w') as f:
        json.dump(glossary, f, indent=2)
    print(f"Saved to {GLOSSARY_PATH}")

if __name__ == "__main__":
    main()
