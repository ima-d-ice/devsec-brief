
from pathlib import Path
import os
import time
import functools
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor

from sentence_transformers import SentenceTransformer, CrossEncoder
import numpy as np
from dotenv import load_dotenv
from src.groq_client import safe_groq_call
from src.db import search_keyword, search_semantic
from datetime import datetime, timezone
from typing import Generator
from dateutil import parser


load_dotenv()

GROQ_MODEL = "llama-3.3-70b-versatile"

EMBED_MODEL_NAME = "BAAI/bge-m3"
ONNX_EMBED_PATH = Path(__file__).resolve().parents[1] / "data" / "onnx_st" / "bge-m3-onnx"
if ONNX_EMBED_PATH.exists():
    print(f"Loading INT8 ONNX Embedding model from {ONNX_EMBED_PATH}...")
    embed_model = SentenceTransformer(
        str(ONNX_EMBED_PATH),
        backend="onnx",
        model_kwargs={
            "file_name": "onnx/model_qint8_arm64.onnx",
            "provider": "CPUExecutionProvider"
        }
    )
else:
    print("Loading Embedding model (MPS)...")
    embed_model = SentenceTransformer(EMBED_MODEL_NAME, trust_remote_code=True, device="mps")

RERANKER_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
ONNX_RERANK_PATH = Path(__file__).resolve().parents[1] / "data" / "onnx_st" / "mmarco-onnx"
if ONNX_RERANK_PATH.exists():
    print(f"Loading INT8 ONNX CrossEncoder from {ONNX_RERANK_PATH}...")
    reranker_model = CrossEncoder(
        str(ONNX_RERANK_PATH),
        backend="onnx",
        model_kwargs={
            "file_name": "onnx/model_qint8_arm64.onnx",
            "provider": "CPUExecutionProvider"
        }
    )
else:
    print("Loading CrossEncoder natively...")
    reranker_model = CrossEncoder(RERANKER_MODEL_NAME, device="mps")

CONTEXT_DOC_LIMIT = 3

CROSSENCODER_MAX_CHARS = 1000




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




GLOSSARY_PATH = Path(__file__).resolve().parents[1] / "data" / "entity_glossary.json"
_entity_glossary = {}

def _load_glossary():
    global _entity_glossary
    try:
        with open(GLOSSARY_PATH, 'r') as f:
            _entity_glossary = json.load(f)
        print(f"  [glossary] Loaded {len(_entity_glossary)} entities for query enrichment.")
    except Exception as e:
        print(f"  [glossary] Could not load: {e}")
        _entity_glossary = {}

_load_glossary()

def get_query_variants(query: str) -> list[str]:
    """Returns multiple query variants for Multi-Vector Retrieval."""
    if not _entity_glossary:
        return [query]
        
    query_lower = query.lower()
    injections = []
    
    for entity, definition in _entity_glossary.items():
        if entity.lower() in query_lower:
            injections.append(str(definition))
            
    if injections:
        return [query, query + " " + " ".join(injections)]
    return [query]





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
                pass
                
            base_score = 1 / (60 + rank + 1)
            
            source = item["metadata"].get("source", "")
            source_weight = SOURCE_WEIGHTS.get(source, 1.0)
            
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


@timeit
def retrieve_super(query: str, topic: str | None = None, k: int = 6):
    """
    HYBRID SEARCH (optimized):
      1. Single pass dense semantic search with BAAI/bge-m3 + keyword search
      2. RRF merge
      3. CrossEncoder rerank → top K
    """
    timings = {}
    where = {"category": topic} if topic else None

    t_emb = time.perf_counter()
    query_variants = get_query_variants(query)
    q_embs = embed_model.encode(query_variants, batch_size=len(query_variants)).tolist()
    print(f"     [debug] get_query_variants & embed_model.encode took {time.perf_counter() - t_emb:.4f}s")

    def _run_pgvector_search():
        return search_semantic(q_embs, k=20, topic=topic)

    def _run_keyword():
        return search_keyword(query_variants[-1], limit=20, topic=topic)

    with ThreadPoolExecutor(max_workers=2) as ex:
        chroma_future = ex.submit(_run_pgvector_search)
        keyword_future = ex.submit(_run_keyword)
        
        original_res = chroma_future.result()
        keyword_results = keyword_future.result()

    timings["semantic+keyword"] = time.perf_counter() - t_emb

    semantic_result_lists = []
    if original_res.get("documents"):
        for i in range(len(original_res["documents"])):
            if original_res["documents"][i]:
                query_results = []
                for doc, meta in zip(original_res["documents"][i], original_res["metadatas"][i]):
                    query_results.append({"document": doc, "metadata": meta})
                semantic_result_lists.append(query_results)

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

    timing_str = " | ".join(f"{k}: {v:.4f}s" for k, v in timings.items())
    print(f"⏱️  [retrieve_super stages] {timing_str}")

    return {
        "documents": [top_k_docs],
        "metadatas": [top_k_metas]
    }




@timeit
def build_context(res) -> str:
    """Build a readable context string from retrieved docs + metadata.
    Uses CONTEXT_DOC_LIMIT to control how many documents are fed to the LLM."""
    if not res or not res.get("documents"):
        return ""

    docs = res["documents"][0]
    metas = res["metadatas"][0]

    chunks = []
    for doc, meta in zip(docs[:CONTEXT_DOC_LIMIT], metas[:CONTEXT_DOC_LIMIT]):
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

    sources = res["metadatas"][0][:CONTEXT_DOC_LIMIT] if res.get("metadatas") else []
    return {
        "answer": answer,
        "sources": sources,
    }


if __name__ == "__main__":
    q = "Any important recent web development or JavaScript updates?"
    result = answer_question(q, topic="webdev", k=6)

    print("QUESTION:", q)
    print("\n" + "=" * 80 + "\n")
    print("ANSWER:\n", result["answer"])
    print("\nSOURCES:")
    for s in result["sources"]:
        print("-", s["source"], "=>", s["title"], "(", s["url"], ")")

