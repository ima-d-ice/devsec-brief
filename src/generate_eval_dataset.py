# src/generate_eval_dataset.py
import json
import os
import time
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai
from src.db import get_conn

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

DATASET_PATH = Path(__file__).resolve().parents[1] / "data" / "evaluation_dataset.json"

def generate_dataset(num_questions=5):
    print(f"=== Generating Dynamic Golden Dataset ({num_questions} questions) ===")
    conn = get_conn()
    articles = conn.execute("""
        SELECT title, content, summary, url FROM articles 
        WHERE length(content) > 200 ORDER BY RANDOM() LIMIT ?
    """, (num_questions,)).fetchall()
    conn.close()
    
    if not articles:
        print("❌ No articles found in DB. Run `python3 -m src.refresh` first.")
        return

    model = genai.GenerativeModel("gemini-3.1-flash-lite")
    dataset = []

    for row in articles:
        print(f"Generating question for: {row['title'][:50]}...")
        text_snippet = (row['content'] or row['summary'])[:1000]
        
        prompt = f"""
Read the following tech news article snippet and generate a specific question that a developer or security professional would ask.
Then, provide a concise expected answer based ONLY on the snippet.

Article Title: {row['title']}
Article Snippet: {text_snippet}

Respond in STRICT JSON format:
{{
  "question": "...",
  "expected_answer": "..."
}}
"""
        try:
            response = model.generate_content(prompt)
            # Clean up markdown code blocks if present
            clean_json = response.text.strip().replace("```json", "").replace("```", "")
            result = json.loads(clean_json)
            
            dataset.append({
                "question": result["question"],
                "expected_answer": result["expected_answer"],
                "expected_source_url": row["url"]
            })
            time.sleep(4.5) # Safety delay to respect 15 RPM limit
        except Exception as e:
            print(f"  -> Failed: {e}")

    with open(DATASET_PATH, 'w') as f:
        json.dump(dataset, f, indent=2)
    print(f"\n✅ Saved {len(dataset)} questions.")

if __name__ == "__main__":
    generate_dataset(num_questions=5)
