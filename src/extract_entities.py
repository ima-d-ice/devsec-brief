import json
import re
import time
from src.groq_pool import safe_groq_call
from src.db import get_conn, rows_to_dicts
from src.sanitize import sanitize_definition
from src.paths import GLOSSARY_PATH

def get_articles():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, summary FROM articles")
            dict_rows = rows_to_dicts(cur)
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
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Extract entities as a JSON dict from the following text:\n\n{text_to_process}"}
            ],
            temperature=0.1,
            max_tokens=700,
            role="gen",
        )
        content = completion.choices[0].message.content
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
        glossary.update({k: sanitize_definition(v) for k, v in entities.items()})
        time.sleep(4)
        
    print(f"Extracted {len(glossary)} total entities.")
    
    with open(GLOSSARY_PATH, 'w') as f:
        json.dump(glossary, f, indent=2)
    print(f"Saved to {GLOSSARY_PATH}")

if __name__ == "__main__":
    main()
