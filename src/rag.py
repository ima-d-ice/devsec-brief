# src/rag.py

from pathlib import Path
import os
import time
import functools
import sqlite3
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor

import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder
from dotenv import load_dotenv
from src.groq_client import safe_groq_call
from src.db import search_keyword
from datetime import datetime, timezone
from typing import Generator
from dateutil import parser

# -------------------- Env & Groq setup --------------------

load_dotenv()

# fast + good model on Groq
GROQ_MODEL = "llama-3.1-8b-instant"
# you can later try: "llama-3.1-8b-instant"

# -------------------- Embeddings & Chroma setup --------------------

CHROMA_PATH = Path(__file__).resolve().parents[1] / "data" / "chroma"
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
collection = chroma_client.get_or_create_collection(
    name="news_articles",
    metadata={"hnsw:space": "cosine"},
)

EMBED_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
embed_model = SentenceTransformer(EMBED_MODEL_NAME, trust_remote_code=True, device="mps")

# NEW: Initialize Cross-Encoder for reranking (Multilingual mMARCO model)
RERANKER_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
reranker_model = CrossEncoder(RERANKER_MODEL_NAME)

# Shared constant: number of documents fed to the LLM context.
# Used by build_context() and api.py to ensure returned sources match what the model reads.
CONTEXT_DOC_LIMIT = 3

# Max characters to pass to the CrossEncoder per document.
# CrossEncoders typically have a 512-token limit (~2000 chars). Using 1000 chars
# keeps the most relevant opening content and avoids silent truncation.
CROSSENCODER_MAX_CHARS = 1000


# -------------------- Latency Measurement --------------------


def timeit(func):
    """Decorator to measure and log function execution time."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"⏱️  {func.__name__} took {elapsed:.4f}s")
        return result
    return wrapper


# -------------------- Query expansion via Groq --------------------

# Two-tier expansion cache:
#   L1: in-memory dict (instant, lost on restart)
#   L2: SQLite persistent (survives restarts, ~0.1ms lookup)
# Repeat queries skip the ~600ms Groq round-trip entirely.
_expansion_cache: dict[str, list[str]] = {}

EXPANSION_CACHE_DB = Path(__file__).resolve().parents[1] / "data" / "expansion_cache.db"


def _init_expansion_cache_db():
    """Create the persistent expansion cache table if it doesn't exist."""
    conn = sqlite3.connect(EXPANSION_CACHE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expansion_cache (
            key TEXT PRIMARY KEY,
            expansions TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _load_expansion_cache():
    """Preload all cached expansions from SQLite into the in-memory L1 cache."""
    global _expansion_cache
    try:
        conn = sqlite3.connect(EXPANSION_CACHE_DB)
        rows = conn.execute("SELECT key, expansions FROM expansion_cache").fetchall()
        conn.close()
        _expansion_cache = {row[0]: json.loads(row[1]) for row in rows}
        if _expansion_cache:
            print(f"  [expansion cache] Loaded {len(_expansion_cache)} entries from disk")
    except Exception as e:
        print(f"  [expansion cache] Could not load from disk: {e}")
        _expansion_cache = {}


def _save_expansion_to_db(cache_key: str, expansions: list[str]):
    """Persist a new expansion to the SQLite L2 cache."""
    try:
        conn = sqlite3.connect(EXPANSION_CACHE_DB)
        conn.execute(
            "INSERT OR REPLACE INTO expansion_cache (key, expansions) VALUES (?, ?)",
            (cache_key, json.dumps(expansions)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  [expansion cache] Could not save to disk: {e}")


# Initialize persistent cache on module load
_init_expansion_cache_db()
_load_expansion_cache()


@timeit
def expand_query_groq(query: str, n_variants: int = 2) -> list[str]:
    """
    Use Groq LLM to generate a few alternative search queries
    for better recall (multi-query retrieval).
    Results are cached in two tiers:
      L1: in-memory dict (instant)
      L2: SQLite on disk (survives restarts)
    """
    cache_key = f"{query}::{n_variants}"
    if cache_key in _expansion_cache:
        print(f"  [expansion cache hit] skipping Groq call")
        return _expansion_cache[cache_key]

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

    completion = safe_groq_call(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=128,
    )

    text = completion.choices[0].message.content or ""
    variants = [line.strip() for line in text.splitlines() if line.strip()]
    result = variants[:n_variants]
    # Save to both L1 (memory) and L2 (disk)
    _expansion_cache[cache_key] = result
    _save_expansion_to_db(cache_key, result)
    return result


# -------------------- Super retrieval with Chroma (multi-query) --------------------


# -------------------- Source Weights & Temporal Decay --------------------

SOURCE_WEIGHTS = {
    "CISA Cybersecurity Advisories": 1.5,
    "NCSC (NL Cyber Security)": 1.5,
    "MDN Blog": 1.4,
    "web.dev": 1.3,
    "The Hacker News": 1.1,
    "Hacker News": 1.0,
}

def get_temporal_decay(published_at: str) -> float:
    """Calculates a multiplier. 1.0 for today, drops 1% per day, min 0.5.
    Clamped to [0.5, 1.0] so future-dated articles can't get a boost above 1.0."""
    if not published_at:
        return 0.8  # Slight penalty for missing dates
    try:
        pub_date = parser.parse(published_at)
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        
        age_days = (datetime.now(timezone.utc) - pub_date).days
        decay = 1.0 - min(0.5, age_days * 0.01)
        return min(1.0, max(0.5, decay))
    except Exception:
        return 0.8

# -------------------- RRF Merging Logic (Updated) --------------------

def rrf_merge(*result_lists: list[dict], pool_size: int = 20) -> dict:
    """Reciprocal Rank Fusion across multiple ranked result lists.
    Each list is scored independently so that each list's top result starts at rank 0,
    and documents found by multiple lists accumulate score from each."""
    rrf_scores = {}
    doc_data = {}

    def process_list(results):
        for rank, item in enumerate(results):
            url = item["metadata"].get("url")
            if not url: continue
            if url not in rrf_scores:
                rrf_scores[url] = 0.0
                doc_data[url] = item
            else:
                # If we've seen this URL, keep the version with the longest document text
                # This ensures we don't throw away a full FTS article in favor of a small Chroma chunk
                if len(item["document"]) > len(doc_data[url]["document"]):
                    doc_data[url] = item
                
            # Base RRF score
            base_score = 1 / (60 + rank + 1)
            
            # Apply Source Weight
            source = item["metadata"].get("source", "")
            source_weight = SOURCE_WEIGHTS.get(source, 1.0)
            
            # Apply Temporal Decay
            decay = get_temporal_decay(item["metadata"].get("published_at", ""))
            
            rrf_scores[url] += base_score * source_weight * decay

    for result_list in result_lists:
        process_list(result_list)

    sorted_urls = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

    final_docs = [doc_data[url]["document"] for url in sorted_urls[:pool_size]]
    final_metas = [doc_data[url]["metadata"] for url in sorted_urls[:pool_size]]

    return {
        "documents": [final_docs],
        "metadatas": [final_metas]
    }

# -------------------- Super retrieval with Hybrid Search --------------------

@timeit
def retrieve_super(query: str, topic: str | None = None, k: int = 6):
    """
    HYBRID SEARCH (optimized):
      1. Expand query via Groq  ┐
      2. Original Chroma search ┘  (parallel — overlaps ~600ms Groq wait)
      3. Batch-encode expansion queries (single encode() call)
      4. Expansion Chroma searches + keyword search (all parallel)
      5. RRF merge
      6. CrossEncoder rerank → top K
    """
    timings = {}
    where = {"category": topic} if topic else None

    # --- Phase 1: Parallel expand + original semantic search ---
    # Overlaps the ~600ms Groq network wait with the ~80ms original Chroma search.
    t0 = time.perf_counter()

    # DO NOT put embed_model.encode inside the thread; HuggingFace tokenizers can deadlock in threads
    original_q_emb = embed_model.encode([query]).tolist()

    def _run_original_chroma_search():
        """Run the original query's semantic search in a thread."""
        return collection.query(query_embeddings=original_q_emb, n_results=20, where=where)

    with ThreadPoolExecutor(max_workers=2) as ex:
        expand_future = ex.submit(expand_query_groq, query, 2)
        original_future = ex.submit(_run_original_chroma_search)

        original_res = original_future.result()

        try:
            expansions = expand_future.result()
        except Exception as e:
            print("Query expansion failed, using original query only:", e)
            expansions = []

    timings["expand+original"] = time.perf_counter() - t0

    # Collect original query results
    semantic_result_lists = []
    if original_res.get("documents") and original_res["documents"][0]:
        query_results = []
        for doc, meta in zip(original_res["documents"][0], original_res["metadatas"][0]):
            query_results.append({"document": doc, "metadata": meta})
        semantic_result_lists.append(query_results)

    # --- Phase 2: Batch-encode expansions + parallel Chroma queries + keyword search ---
    # Instead of 2 separate encode() calls + 2 sequential Chroma queries + 1 keyword search,
    # we batch-encode in one call then fan out all searches concurrently.
    t1 = time.perf_counter()

    if expansions:
        # Single batched encode for all expansion queries (saves ~30-50ms vs individual calls)
        expansion_embeddings = embed_model.encode(expansions).tolist()

        def _run_expansion_chroma(emb):
            return collection.query(query_embeddings=[emb], n_results=20, where=where)

        def _run_keyword():
            return search_keyword(query, limit=20, topic=topic)

        # Fan out: all expansion Chroma queries + keyword search run concurrently
        with ThreadPoolExecutor(max_workers=len(expansions) + 1) as ex:
            chroma_futures = [ex.submit(_run_expansion_chroma, emb) for emb in expansion_embeddings]
            keyword_future = ex.submit(_run_keyword)

            # Collect expansion Chroma results
            for future in chroma_futures:
                res = future.result()
                if not res.get("documents") or not res["documents"][0]:
                    continue
                query_results = []
                for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
                    query_results.append({"document": doc, "metadata": meta})
                semantic_result_lists.append(query_results)

            keyword_results = keyword_future.result()
    else:
        # No expansions — just run keyword search
        keyword_results = search_keyword(query, limit=20, topic=topic)

    timings["expansion_semantic+keyword"] = time.perf_counter() - t1

    # --- Phase 3: RRF Merge ---
    all_lists = semantic_result_lists + [keyword_results]
    non_empty_lists = [lst for lst in all_lists if lst]

    if not non_empty_lists:
        return {"documents": [[]], "metadatas": [[]]}

    t3 = time.perf_counter()
    merged = rrf_merge(*non_empty_lists, pool_size=20)
    timings["rrf"] = time.perf_counter() - t3
    
    merged_docs = merged["documents"][0]
    merged_metas = merged["metadatas"][0]

    if not merged_docs:
        return {"documents": [[]], "metadatas": [[]]}

    # --- Phase 4: CrossEncoder Reranking ---
    total_semantic = sum(len(lst) for lst in semantic_result_lists)
    print(f"Hybrid Search: Merging {total_semantic} semantic docs and {len(keyword_results)} keyword docs...")
    print(f"Reranking {len(merged_docs)} candidate documents with CrossEncoder...")
    
    t4 = time.perf_counter()
    pairs = [[query, doc[:CROSSENCODER_MAX_CHARS]] for doc in merged_docs]
    rerank_scores = reranker_model.predict(pairs)
    timings["rerank"] = time.perf_counter() - t4

    scored_results = list(zip(rerank_scores, merged_docs, merged_metas))
    scored_results.sort(key=lambda x: x[0], reverse=True)

    top_k_docs = [x[1] for x in scored_results[:k]]
    top_k_metas = [x[2] for x in scored_results[:k]]

    if scored_results:
        print(f"Top document rerank score: {scored_results[0][0]:.4f}")

    # Log per-stage timing
    timing_str = " | ".join(f"{k}: {v:.4f}s" for k, v in timings.items())
    print(f"⏱️  [retrieve_super stages] {timing_str}")

    return {
        "documents": [top_k_docs],
        "metadatas": [top_k_metas]
    }


# -------------------- Build context & generation --------------------


@timeit
def build_context(res) -> str:
    """Build a readable context string from retrieved docs + metadata.
    Uses CONTEXT_DOC_LIMIT to control how many documents are fed to the LLM."""
    if not res or not res.get("documents"):
        return ""

    docs = res["documents"][0]
    metas = res["metadatas"][0]

    chunks = []
    # Use shared constant for doc limit to stay in sync with returned sources
    for doc, meta in zip(docs[:CONTEXT_DOC_LIMIT], metas[:CONTEXT_DOC_LIMIT]):
        # Increased truncation limit to 12000 characters to ensure full articles are evaluated
        # This prevents RAGAS from penalizing faithfulness due to missing context at the bottom of articles.
        snippet = doc[:12000].strip().replace("\n\n", "\n")
        chunks.append(
            f"[{meta.get('source')} | {meta.get('category')} | {meta.get('published_at')}]\n"
            f"Title: {meta.get('title')}\n"
            f"URL: {meta.get('url')}\n"
            f"Snippet:\n{snippet}\n"
            f"{'-'*80}"
        )

    return "\n\n".join(chunks)


def prepare_messages(context: str, query: str, history: list[dict] = None) -> list[dict]:
    system_prompt = (
        "You are an assistant for software developers and cybersecurity professionals. "
        "You answer using ONLY the provided news excerpts. "
        "If there is not enough information, say: 'Not enough info from sources.' "
        "Be concise but specific, and reference technologies, CVEs, frameworks, versions, etc. when relevant."
    )

    messages = [{"role": "system", "content": system_prompt}]
    
    # Inject conversation history (last 4 turns)
    if history:
        messages.extend(history[-4:])
        
    user_prompt = f"""
NEWS EXCERPTS:
{context}

QUESTION:
{query}

ANSWER:
"""
    messages.append({"role": "user", "content": user_prompt})
    return messages

@timeit
def generate_answer_from_context(context: str, query: str, history: list[dict] = None) -> str:
    messages = prepare_messages(context, query, history)
    completion = safe_groq_call(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=1024,  # <--- INCREASED from 400 to 1024
    )
    content = completion.choices[0].message.content or ""
    return content.strip()

# NEW: Streaming generator
def stream_answer_from_context(context: str, query: str, history: list[dict] = None) -> Generator[str, None, None]:
    messages = prepare_messages(context, query, history)
    completion = safe_groq_call(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=1024,  # <--- INCREASED from 400 to 1024
        stream=True  # Enable streaming
    )
    
    for chunk in completion:
        if chunk.choices and chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content


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

    # Slice sources to match CONTEXT_DOC_LIMIT so returned sources = what the LLM saw
    sources = res["metadatas"][0][:CONTEXT_DOC_LIMIT] if res.get("metadatas") else []
    return {
        "answer": answer,
        "sources": sources,
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

