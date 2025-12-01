# src/rag.py

from pathlib import Path
import os

import chromadb
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from groq import Groq

# -------------------- Env & Groq setup --------------------

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not set in .env")

groq_client = Groq(api_key=GROQ_API_KEY)

# fast + good model on Groq
GROQ_MODEL = "llama-3.1-8b-instant"
# you can later try: "llama-3.1-70b-versatile"

# -------------------- Embeddings & Chroma setup --------------------

CHROMA_PATH = Path(__file__).resolve().parents[1] / "data" / "chroma"
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
collection = chroma_client.get_or_create_collection(
    name="news_articles",
    metadata={"hnsw:space": "cosine"},
)

EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
embed_model = SentenceTransformer(EMBED_MODEL_NAME)


# -------------------- Query expansion via Groq --------------------


def expand_query_groq(query: str, n_variants: int = 2) -> list[str]:
    """
    Use Groq LLM to generate a few alternative search queries
    for better recall (multi-query retrieval).
    """
    system_prompt = (
        "You rewrite search queries for a developer & cybersecurity news search engine. "
        "Generate alternative phrasings and closely related queries that would help find "
        "relevant articles about the same topic."
    )
    user_prompt = (
        f"Original query: {query}\n\n"
        f"Generate {n_variants} alternative phrasings or closely related queries.\n"
        f"Return ONLY the queries, one per line, no bullets, no numbering."
    )

    completion = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=128,
    )

    text = completion.choices[0].message.content
    variants = [line.strip() for line in text.splitlines() if line.strip()]
    return variants[:n_variants]


# -------------------- Super retrieval with Chroma (multi-query) --------------------


def retrieve_super(query: str, topic: str | None = None, k: int = 6):
    """
    Super retrieval using Chroma only:
      - expand query via Groq
      - run multiple semantic searches in Chroma
      - merge + deduplicate by URL
    Returns a dict similar to Chroma's query() output.
    """
    queries = [query]

    try:
        expansions = expand_query_groq(query, n_variants=2)
        queries.extend(expansions)
    except Exception as e:
        print("Query expansion failed, using original query only:", e)

    where = {"category": topic} if topic else None

    docs_out = []
    metas_out = []
    seen_urls = set()

    for q in queries:
        q_emb = embed_model.encode([q]).tolist()
        res = collection.query(
            query_embeddings=q_emb,
            n_results=k,
            where=where,
        )

        if not res.get("documents"):
            continue

        for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
            url = meta.get("url")
            if url and url in seen_urls:
                continue
            seen_urls.add(url)
            docs_out.append(doc)
            metas_out.append(meta)
            if len(docs_out) >= k:
                break

        if len(docs_out) >= k:
            break

    if not docs_out:
        return {
            "documents": [[]],
            "metadatas": [[]],
        }

    return {
        "documents": [docs_out],
        "metadatas": [metas_out],
    }


# -------------------- Build context & generation --------------------


def build_context(res) -> str:
    """Build a readable context string from retrieved docs + metadata."""
    if not res or not res.get("documents"):
        return ""

    docs = res["documents"][0]
    metas = res["metadatas"][0]

    chunks = []
    for doc, meta in zip(docs, metas):
        snippet = doc[:900].strip().replace("\n\n", "\n")
        chunks.append(
            f"[{meta.get('source')} | {meta.get('category')} | {meta.get('published_at')}]\n"
            f"Title: {meta.get('title')}\n"
            f"URL: {meta.get('url')}\n"
            f"Snippet:\n{snippet}\n"
            f"{'-'*80}"
        )

    return "\n\n".join(chunks)


def generate_answer_from_context(context: str, query: str) -> str:
    """
    Use Groq (Llama 3.1) to answer based on the retrieved context.
    """
    system_prompt = (
        "You are an assistant for software developers and cybersecurity professionals. "
        "You answer using ONLY the provided news excerpts. "
        "If there is not enough information, say: 'Not enough info from sources.' "
        "Be concise but specific, and reference technologies, CVEs, frameworks, versions, etc. when relevant."
    )

    user_prompt = f"""
NEWS EXCERPTS:
{context}

QUESTION:
{query}

ANSWER:
"""

    completion = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=400,
    )

    return completion.choices[0].message.content.strip()


# -------------------- Public RAG API --------------------


def answer_question(query: str, topic: str | None = None, k: int = 6) -> dict:
    """
    SUPER RAG (Chroma-only version):
      1. expand query with Groq
      2. multi-query semantic retrieval in Chroma
      3. build context
      4. ask Groq LLM to answer from context
    """
    res = retrieve_super(query, topic=topic, k=k)
    context = build_context(res)

    if not context.strip():
        return {
            "answer": "No relevant news found in the index.",
            "sources": [],
        }

    answer = generate_answer_from_context(context, query)

    return {
        "answer": answer,
            "sources": res["metadatas"][0] if res.get("metadatas") else [],
    }


if __name__ == "__main__":
    # quick manual test
    q = "Any important recent web development or JavaScript updates?"
    result = answer_question(q, topic="webdev", k=6)

    print("QUESTION:", q)
    print("\n" + "=" * 80 + "\n")
    print("ANSWER:\n", result["answer"])
    print("\nSOURCES:")
    for s in result["sources"]:
        print("-", s["source"], "=>", s["title"], "(", s["url"], ")")

