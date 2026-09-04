"""Generate grounded eval Q&A pairs from indexed articles (uses gen key shard).

Usage:
    python -m src.generate_eval_dataset --limit 60 --out data/eval_corpus_new.json --sleep 4
Human step (required): verify each ground_truth span exists in the source
parent text before merging into data/eval_corpus.json.
"""
import argparse
import json
import re
import time
from pathlib import Path

from src.db import get_conn, rows_to_dicts
from src.groq_pool import safe_groq_call

GEN_PROMPT = """You create RAG evaluation items from a news article.
Return STRICT JSON: {{"question": "...", "ground_truth": "2-3 sentences with versions/CVE IDs as in text", "keywords": ["..."], "type": "cve|advisory|howto|comparison", "difficulty": "easy|medium|hard"}}
Rules: question must be answerable ONLY from the text; ground_truth must copy facts verbatim (no outside knowledge); keywords 3-6 exact terms from text.
Article:
<<<ARTICLE>>>
{article}
<<<END>>>"""


def fetch_articles(limit: int, category: str | None = None) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            sql = "SELECT id, title, summary, content, category, url FROM articles ORDER BY created_at DESC LIMIT %s"
            params: list = [limit * 3]
            if category:
                sql = "SELECT id, title, summary, content, category, url FROM articles WHERE category = %s ORDER BY created_at DESC LIMIT %s"
                params = [category, limit * 3]
            cur.execute(sql, params)
            return rows_to_dicts(cur)


def gen_for_article(article: dict) -> dict | None:
    text = f"Title: {article.get('title')}\nURL: {article.get('url')}\n{(article.get('content') or article.get('summary') or '')[:3000]}"
    try:
        completion = safe_groq_call(
            messages=[
                {"role": "system", "content": "You output only raw JSON."},
                {"role": "user", "content": GEN_PROMPT.format(article=text)},
            ],
            temperature=0.0,
            max_tokens=400,
            role="gen",
        )
        content = completion.choices[0].message.content or "{}"
        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        if not data.get("question") or not data.get("ground_truth"):
            return None
        return {
            "id": f"gen_{article['id']}",
            "category": article.get("category", "general"),
            "question": data["question"].strip(),
            "ground_truth": data["ground_truth"].strip(),
            "keywords": data.get("keywords", [])[:6],
            "type": data.get("type", "advisory"),
            "difficulty": data.get("difficulty", "medium"),
            "source_urls": [article.get("url")],
        }
    except Exception as e:
        print(f"⚠️ gen failed for article {article.get('id')}: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", type=str, default="data/eval_corpus_new.json")
    ap.add_argument("--sleep", type=float, default=4.0)
    ap.add_argument("--category", type=str, default=None)
    args = ap.parse_args()

    articles = fetch_articles(args.limit, args.category)
    print(f"Loaded {len(articles)} articles, targeting {args.limit} items (gen shard keys 9-10)...")
    items = []
    for i, a in enumerate(articles):
        if len(items) >= args.limit:
            break
        print(f"[{len(items)+1}/{args.limit}] article {a['id']}: {str(a.get('title'))[:60]}")
        item = gen_for_article(a)
        if item:
            items.append(item)
        time.sleep(args.sleep)

    out = Path(args.out)
    out.write_text(json.dumps(items, indent=2))
    print(f"✅ Wrote {len(items)} candidates to {out}. VERIFY spans before merging.")


if __name__ == "__main__":
    main()
