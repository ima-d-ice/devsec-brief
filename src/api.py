import json
import time
import uuid
from typing import List, Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from src.rag import (
    retrieve_super, 
    build_context, 
    stream_answer_from_context, 
    generate_answer_from_context, 
    check_cache_for_query,
    CONTEXT_DOC_LIMIT
)
from src.sanitize import sanitize_query, sanitize_history, contains_injection_pattern
from src.db import get_chat_history, save_chat_message, save_semantic_cache
from src.logger import get_logger

log = get_logger("api")

app = FastAPI(
    title="DevSec Brief – Production RAG API",
    description="High-performance RAG API with semantic caching, 12-key Groq pool, and persistent chat.",
    version="1.0.0",
)

@app.middleware("http")
async def add_process_time(request: Request, call_next):
    """Measures end-to-end request latency and adds it as a response header."""
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{ms:.1f}"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskRequest(BaseModel):
    query: str
    topic: Optional[str] = None
    k: int = 6
    session_id: Optional[str] = None

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        if len(v) > 2000:
            raise ValueError('Query too long (max 2000 chars)')
        if contains_injection_pattern(v):
            raise ValueError('Query contains suspicious patterns')
        return v

    @field_validator('k')
    @classmethod
    def validate_k(cls, v: int) -> int:
        return max(1, min(v, 20))

class Source(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    category: Optional[str] = None
    published_at: Optional[str] = None

class AskResponse(BaseModel):
    answer: str
    sources: List[Source]
    model_used: Optional[str] = None
    cache_hit: bool = False
    latency_breakdown_ms: Optional[dict] = None

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, response: Response):
    """Standard JSON endpoint with semantic caching and persistent chat."""
    safe_query = sanitize_query(req.query)
    topic = req.topic if req.topic not in ("all", "") else None

    # Step 1: Check Semantic Cache (exact fast path, then vector)
    cached, q_emb = check_cache_for_query(safe_query, topic=topic)
    if cached:
        response.headers["X-Cache-Hit"] = "true"
        response.headers["X-Model-Used"] = cached["model_used"]
        return AskResponse(
            answer=cached["answer"],
            sources=[Source(**{k: s.get(k) for k in ("title", "url", "source", "category", "published_at")}) for s in cached["sources"]],
            model_used=cached["model_used"],
            cache_hit=True,
            latency_breakdown_ms={"cache_lookup_ms": cached["cache_time_ms"]}
        )

    # Step 2: Hybrid Retrieval
    retrieval_res = retrieve_super(safe_query, topic=topic, k=req.k, precomputed_q_emb=q_emb or None)
    context = build_context(retrieval_res)

    if not context.strip():
        return AskResponse(answer="No relevant news found in the index.", sources=[], cache_hit=False)

    # Step 3: Fetch Persistent Chat History from PostgreSQL
    history = []
    if req.session_id:
        try:
            db_history = get_chat_history(req.session_id, limit=6)
            history = sanitize_history(db_history)
        except Exception:
            history = []

    # Step 4: Generation with Key Pool and Fallback
    answer, model_used = generate_answer_from_context(context, safe_query, history)

    sources_raw = retrieval_res.get("metadatas") or []
    sources = [Source(**s) for s in sources_raw[0][:CONTEXT_DOC_LIMIT]] if sources_raw else []

    # Step 5: Persist chat and update semantic cache
    if req.session_id:
        try:
            save_chat_message(req.session_id, "user", safe_query)
            save_chat_message(req.session_id, "assistant", answer)
        except Exception as e:
            log.warning(f"persist chat failed: {e}")

    try:
        sources_dicts = [s.model_dump() for s in sources]
        save_semantic_cache(safe_query, q_emb, answer, sources_dicts, model_used, topic=topic)
    except Exception as e:
        log.warning(f"semantic cache write failed: {e}")

    response.headers["X-Cache-Hit"] = "false"
    response.headers["X-Model-Used"] = model_used

    return AskResponse(
        answer=answer, 
        sources=sources, 
        model_used=model_used, 
        cache_hit=False,
        latency_breakdown_ms=retrieval_res.get("timings")
    )

@app.post("/ask/stream")
def ask_stream(req: AskRequest):
    """SSE Streaming endpoint with TTFT, TPS, metrics payload, and persistent chat."""
    safe_query = sanitize_query(req.query)
    topic = req.topic if req.topic not in ("all", "") else None
    session_id = req.session_id or str(uuid.uuid4())

    # Check Semantic Cache for Instant Stream
    cached, q_emb = check_cache_for_query(safe_query, topic=topic)
    if cached:
        def cached_stream():
            yield f"event: sources\ndata: {json.dumps({'sources': cached['sources'], 'session_id': session_id, 'cache_hit': True})}\n\n"
            yield f"event: token\ndata: {json.dumps({'content': cached['answer']})}\n\n"
            metrics = {
                "cache_hit": True,
                "model_used": cached["model_used"],
                "cache_lookup_ms": cached["cache_time_ms"],
                "tokens": len(cached["answer"].split()),
            }
            yield f"event: metrics\ndata: {json.dumps(metrics)}\n\n"
            yield f"event: done\ndata: {json.dumps({})}\n\n"
        return StreamingResponse(cached_stream(), media_type="text/event-stream")

    # Hybrid Retrieval
    retrieval_res = retrieve_super(safe_query, topic=topic, k=req.k, precomputed_q_emb=q_emb or None)
    context = build_context(retrieval_res)

    if not context.strip():
        def error_stream():
            yield f"event: error\ndata: {json.dumps({'message': 'No relevant news found.'})}\n\n"
            yield f"event: done\ndata: {json.dumps({})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    sources_raw = retrieval_res.get("metadatas") or []
    sources = sources_raw[0][:CONTEXT_DOC_LIMIT] if sources_raw else []
    
    # Load persistent history
    history = []
    try:
        db_history = get_chat_history(session_id, limit=6)
        history = sanitize_history(db_history)
    except Exception:
        pass

    def event_stream():
        yield f"event: sources\ndata: {json.dumps({'sources': sources, 'session_id': session_id, 'cache_hit': False})}\n\n"
        
        full_answer = ""
        token_count = 0
        stream_start = time.perf_counter()
        first_token_time = None
        
        token_gen, model_used = stream_answer_from_context(context, safe_query, history)
        
        for token in token_gen:
            if first_token_time is None:
                first_token_time = time.perf_counter()
                ttft_ms = (first_token_time - stream_start) * 1000
            
            full_answer += token
            token_count += 1
            yield f"event: token\ndata: {json.dumps({'content': token})}\n\n"
        
        ttft_val = round((first_token_time - stream_start) * 1000, 2) if first_token_time else 0
        generation_time = time.perf_counter() - first_token_time if first_token_time else 0.001
        tps_val = round(token_count / generation_time, 1) if generation_time > 0 else 0
        total_stream_ms = round((time.perf_counter() - stream_start) * 1000, 2)

        # Emit metrics event for monitoring & UI
        metrics_payload = {
            "cache_hit": False,
            "model_used": model_used,
            "retrieval_timings": retrieval_res.get("timings"),
            "ttft_ms": ttft_val,
            "tokens": token_count,
            "tps": tps_val,
            "stream_duration_ms": total_stream_ms,
        }
        yield f"event: metrics\ndata: {json.dumps(metrics_payload)}\n\n"

        # Persist session & cache
        try:
            save_chat_message(session_id, "user", safe_query)
            save_chat_message(session_id, "assistant", full_answer)
            save_semantic_cache(safe_query, q_emb, full_answer, sources, model_used, topic=topic)
        except Exception as e:
            log.warning(f"stream background save failed: {e}")
        
        yield f"event: done\ndata: {json.dumps({})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
