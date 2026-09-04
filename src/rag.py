from pathlib import Path
import os
import time
import functools
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Generator
from dateutil import parser
from sentence_transformers import SentenceTransformer, CrossEncoder

from src.sanitize import sanitize_definition
from src.db import search_keyword, search_semantic, check_semantic_cache, check_exact_cache, get_parent_text
from src.groq_pool import safe_groq_call, stream_groq_call, PRIMARY_MODEL
from src.paths import ONNX_EMBED_PATH, GLOSSARY_PATH


def _ort_session_options():
    """Pinned CPU session options: quality-neutral, latency-only tuning."""
    import onnxruntime as ort
    opts = ort.SessionOptions()
    try:
        opts.intra_op_num_threads = int(os.getenv("ONNX_INTRA_OP_THREADS", "4"))
    except ValueError:
        opts.intra_op_num_threads = 4
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return opts


_ORT_OPTS = _ort_session_options()

EMBED_MODEL_NAME = "BAAI/bge-m3"

if ONNX_EMBED_PATH.exists():
    print(f"Loading INT8 ONNX Embedding model from {ONNX_EMBED_PATH}...")
    embed_model = SentenceTransformer(
        str(ONNX_EMBED_PATH),
        backend="onnx",
        model_kwargs={
            "file_name": "onnx/model_qint8_arm64.onnx",
            "provider": "CPUExecutionProvider",
            "session_options": _ORT_OPTS,
        }
    )
else:
    print("Loading Embedding model (CPU)...")
    embed_model = SentenceTransformer(
        EMBED_MODEL_NAME,
        trust_remote_code=True,
        device="cpu"
    )

RERANKER_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
ONNX_RERANK_PATH = Path(__file__).resolve().parents[1] / "data" / "onnx_st" / "mmarco-onnx"
if ONNX_RERANK_PATH.exists():
    print(f"Loading INT8 ONNX CrossEncoder from {ONNX_RERANK_PATH}...")
    reranker_model = CrossEncoder(
        str(ONNX_RERANK_PATH),
        backend="onnx",
        model_kwargs={
            "file_name": "onnx/model_qint8_arm64.onnx",
            "provider": "CPUExecutionProvider",
            "session_options": _ORT_OPTS,
        }
    )
else:
    print("Loading CrossEncoder natively...")
    reranker_model = CrossEncoder(
        RERANKER_MODEL_NAME,
        device="cpu"
    )

# Warmup: initialize ORT arenas before real traffic (kills slow-first-request tail)
try:
    embed_model.encode(["warmup"])
    reranker_model.predict([["warmup query", "warmup passage"]])
except Exception as _warm_e:
    print(f"Warmup skipped: {_warm_e}")

CONTEXT_DOC_LIMIT = 3
CROSSENCODER_MAX_CHARS = 1000
# TPM budget: 8K/min/key on free tier. 3 x 1500 chars ~= 1100 tokens input.
PARENT_SNIPPET_CHARS = 1500
GENERATION_MAX_TOKENS = 700

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
            injections.append(sanitize_definition(str(definition)))
            
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
    """Calculates a multiplier. 1.0 for today, drops 1% per day, min 0.5."""
    if not published_at:
        return 0.8
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
    """Reciprocal Rank Fusion across multiple ranked result lists."""
    rrf_scores = {}
    doc_data = {}

    def process_list(results):
        for rank, item in enumerate(results):
            url = item["metadata"].get("url")
            if not url:
                continue
            if url not in rrf_scores:
                rrf_scores[url] = 0.0
                doc_data[url] = item
                
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

def check_cache_for_query(query: str, topic: str | None = None) -> tuple[dict | None, list[float]]:
    """Exact-match fast path (0 embed) then topic-aware semantic cache."""
    t0 = time.perf_counter()
    try:
        exact = check_exact_cache(query, topic=topic)
    except Exception:
        exact = None
    if exact:
        exact["cache_time_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        # Still need an embedding for a future cache write on miss paths;
        # on exact hit callers can reuse a fresh encode only if they miss, so return empty placeholder.
        # Encode lazily here to keep the fast path fast: return cached with empty emb.
        return exact, []
    q_emb = embed_model.encode([query])[0].tolist()
    cached = check_semantic_cache(q_emb, max_distance=0.08, topic=topic)
    cache_time_ms = (time.perf_counter() - t0) * 1000
    if cached:
        cached["cache_time_ms"] = round(cache_time_ms, 2)
    return cached, q_emb

@timeit
def retrieve_super(query: str, topic: str | None = None, k: int = 6, precomputed_q_emb: list[float] = None) -> dict:
    """
    HYBRID SEARCH with fine-grained latency profiling:
      1. Query expansion + Dense Embedding (bge-m3)
      2. Parallel DB Search (pgvector + tsvector)
      3. RRF Merge (source weighted + temporal decay)
      4. CrossEncoder Rerank (mMARCO) -> top K
    """
    timings = {}
    t_start = time.perf_counter()

    # Stage 1: Query expansion + Embedding
    t1 = time.perf_counter()
    query_variants = get_query_variants(query)
    if len(query_variants) == 1 and precomputed_q_emb is not None:
        q_embs = [precomputed_q_emb]
    else:
        q_embs = embed_model.encode(query_variants, batch_size=len(query_variants)).tolist()
    timings["embedding_ms"] = round((time.perf_counter() - t1) * 1000, 2)

    # Stage 2: Parallel DB search (semantic + keyword)
    t2 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as ex:
        semantic_future = ex.submit(lambda: search_semantic(q_embs, k=20, topic=topic))
        keyword_future = ex.submit(lambda: search_keyword(query_variants[-1], limit=20, topic=topic))
        original_res = semantic_future.result()
        keyword_results = keyword_future.result()
    timings["db_search_ms"] = round((time.perf_counter() - t2) * 1000, 2)

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
        timings["total_retrieval_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
        return {"documents": [[]], "metadatas": [[]], "timings": timings, "q_emb": q_embs[0]}

    # Stage 3: RRF merge
    t3 = time.perf_counter()
    merged = rrf_merge(*non_empty_lists, pool_size=20)
    timings["rrf_ms"] = round((time.perf_counter() - t3) * 1000, 2)
    
    merged_docs = merged["documents"][0]
    merged_metas = merged["metadatas"][0]

    if not merged_docs:
        timings["total_retrieval_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
        return {"documents": [[]], "metadatas": [[]], "timings": timings, "q_emb": q_embs[0]}

    # Stage 4: CrossEncoder reranking
    t4 = time.perf_counter()
    pairs = [[query, doc[:CROSSENCODER_MAX_CHARS]] for doc in merged_docs]
    rerank_scores = reranker_model.predict(pairs)
    timings["rerank_ms"] = round((time.perf_counter() - t4) * 1000, 2)

    scored_results = list(zip(rerank_scores, merged_docs, merged_metas))
    scored_results.sort(key=lambda x: x[0], reverse=True)

    # Big-to-small: reranked children -> expand to capped parent docs, deduped
    seen_parents: set[tuple] = set()
    top_k_docs: list[str] = []
    top_k_metas: list[dict] = []
    for _, child_doc, meta in scored_results:
        if len(top_k_docs) >= k:
            break
        aid = meta.get("article_id")
        pidx = meta.get("parent_index", 0) or 0
        key = (aid, pidx, meta.get("url"))
        if key in seen_parents:
            continue
        seen_parents.add(key)
        parent_text = None
        if aid is not None:
            try:
                parent_text = get_parent_text(aid, pidx, max_chars=PARENT_SNIPPET_CHARS)
            except Exception:
                parent_text = None
        top_k_docs.append((parent_text or child_doc)[:PARENT_SNIPPET_CHARS])
        top_k_metas.append(meta)
    timings["total_retrieval_ms"] = round((time.perf_counter() - t_start) * 1000, 2)

    return {
        "documents": [top_k_docs],
        "metadatas": [top_k_metas],
        "timings": timings,
        "q_emb": q_embs[0]
    }

def build_context(res: dict, max_chars_per_doc: int = PARENT_SNIPPET_CHARS) -> str:
    """Builds capped context string from top retrieved documents and metadata."""
    if not res or not res.get("documents"):
        return ""

    docs = res["documents"][0]
    metas = res["metadatas"][0]

    chunks = []
    for doc, meta in zip(docs[:CONTEXT_DOC_LIMIT], metas[:CONTEXT_DOC_LIMIT]):
        snippet = doc[:max_chars_per_doc].strip().replace("\n\n", "\n")
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
        "You are an expert cybersecurity and software development news assistant. "
        "Answer using ONLY the provided excerpts between <<<CONTEXT>>> and <<<END_CONTEXT>>>. "
        "The user question is between <<<QUERY>>> and <<<END_QUERY>>>. "
        "If there is not enough information, state: 'Not enough info from sources.' "
        "Be concise, precise, and reference technologies, CVE IDs, versions, and security advisories when present."
    )

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-4:])
        
    user_prompt = f"""<<<CONTEXT>>>
{context}
<<<END_CONTEXT>>>

<<<QUERY>>>
{query}
<<<END_QUERY>>>"""
    messages.append({"role": "user", "content": user_prompt})
    return messages

@timeit
def generate_answer_from_context(context: str, query: str, history: list[dict] = None, role: str | None = "serve") -> tuple[str, str]:
    """Generates answer using Groq key pool and returns (answer, model_used)."""
    messages = prepare_messages(context, query, history)
    completion = safe_groq_call(
        messages=messages,
        temperature=0.2,
        max_tokens=GENERATION_MAX_TOKENS,
        role=role,
    )
    content = completion.choices[0].message.content or ""
    model_used = completion.model if hasattr(completion, "model") else PRIMARY_MODEL
    return content.strip(), model_used

def stream_answer_from_context(context: str, query: str, history: list[dict] = None, role: str | None = "serve") -> tuple[Generator[str, None, None], str]:
    """Streams answer tokens using Groq key pool and returns (generator, model_used)."""
    messages = prepare_messages(context, query, history)
    return stream_groq_call(
        messages=messages,
        temperature=0.2,
        max_tokens=GENERATION_MAX_TOKENS,
        role=role,
    )
