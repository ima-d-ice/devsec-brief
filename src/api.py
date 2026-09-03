import json
import time
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from src.rag import retrieve_super, build_context, stream_answer_from_context, CONTEXT_DOC_LIMIT
from src.sanitize import sanitize_query, sanitize_history, contains_injection_pattern
from src.logger import get_logger, set_request_id, request_id_var

logger = get_logger(__name__)

app = FastAPI(
    title="DevSec Brief – RAG API",
    description="RAG-powered dev & cybersec news assistant (PostgreSQL + pgvector + Groq Llama 3.3).",
    version="0.2.0",
)


@app.middleware("http")
async def add_process_time(request: Request, call_next):
    """Measures end-to-end request latency, adds headers and structured logs."""
    # Correlation ID: use incoming header or generate
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        # Ensure we log even if handler raises
        pass
    ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{ms:.1f}"
    response.headers["X-Request-ID"] = rid
    logger.info(
        "request_complete",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round(ms, 1),
            "request_id": rid,
        },
    )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

chat_history: Dict[str, list] = {}

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

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, request: Request):
    """Standard JSON endpoint (non-streaming)."""
    rid = request.headers.get("X-Request-ID") or set_request_id()
    request_id_var.set(rid)
    topic = req.topic if req.topic not in ("all", "") else None
    safe_query = sanitize_query(req.query)
    logger.info("ask_request", extra={"query_len": len(safe_query), "k": req.k, "topic": topic, "request_id": rid})
    res = retrieve_super(safe_query, topic=topic, k=req.k)
    context = build_context(res)

    if not context.strip():
        logger.info("ask_no_context", extra={"request_id": rid})
        return AskResponse(answer="No relevant news found in the index.", sources=[])

    history = sanitize_history(chat_history.get(req.session_id, [])) if req.session_id else []
    
    from src.rag import generate_answer_from_context
    t0 = time.perf_counter()
    answer = generate_answer_from_context(context, safe_query, history)
    gen_ms = (time.perf_counter() - t0) * 1000
    logger.info("ask_generate_complete", extra={"ms": round(gen_ms, 1), "answer_len": len(answer), "request_id": rid})

    if req.session_id:
        if req.session_id not in chat_history:
            chat_history[req.session_id] = []
        chat_history[req.session_id].append({"role": "user", "content": safe_query})
        chat_history[req.session_id].append({"role": "assistant", "content": answer})

    sources_raw = res.get("metadatas") or []
    sources = [Source(**s) for s in sources_raw[0][:CONTEXT_DOC_LIMIT]] if sources_raw else []
    
    return AskResponse(answer=answer, sources=sources)

@app.post("/ask/stream")
def ask_stream(req: AskRequest, request: Request):
    """SSE Streaming endpoint. Returns sources first, then tokens."""
    rid = request.headers.get("X-Request-ID") or set_request_id()
    request_id_var.set(rid)
    topic = req.topic if req.topic not in ("all", "") else None
    safe_query = sanitize_query(req.query)
    logger.info("ask_stream_request", extra={"query_len": len(safe_query), "k": req.k, "topic": topic, "request_id": rid})
    res = retrieve_super(safe_query, topic=topic, k=req.k)
    context = build_context(res)

    if not context.strip():
        logger.info("ask_stream_no_context", extra={"request_id": rid})
        def error_stream():
            yield f"event: error\ndata: {json.dumps({'message': 'No relevant news found.'})}\n\n"
            yield f"event: done\ndata: {json.dumps({})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    sources_raw = res.get("metadatas") or []
    sources = sources_raw[0][:CONTEXT_DOC_LIMIT] if sources_raw else []
    
    session_id = req.session_id or str(uuid.uuid4())
    history = sanitize_history(chat_history.get(session_id, []))

    def event_stream():
        # Propagate request_id into generator thread
        request_id_var.set(rid)
        sources_payload = json.dumps({"sources": sources, "session_id": session_id})
        yield f"event: sources\ndata: {sources_payload}\n\n"
        
        full_answer = ""
        token_count = 0
        stream_start = time.perf_counter()
        first_token_time = None
        
        for token in stream_answer_from_context(context, safe_query, history):
            if first_token_time is None:
                first_token_time = time.perf_counter()
                ttft_ms = (first_token_time - stream_start) * 1000
                logger.info("ttft", extra={"ttft_ms": round(ttft_ms, 1), "request_id": rid})
            
            full_answer += token
            token_count += 1
            token_payload = json.dumps({"content": token})
            yield f"event: token\ndata: {token_payload}\n\n"
        
        if first_token_time and token_count > 1:
            generation_time = time.perf_counter() - first_token_time
            tps = token_count / generation_time if generation_time > 0 else 0
            total_time_ms = (time.perf_counter() - stream_start) * 1000
            logger.info(
                "stream_complete",
                extra={
                    "tokens": token_count,
                    "total_ms": round(total_time_ms, 1),
                    "tps": round(tps, 1),
                    "request_id": rid,
                },
            )
            
        if session_id not in chat_history:
            chat_history[session_id] = []
        chat_history[session_id].append({"role": "user", "content": safe_query})
        chat_history[session_id].append({"role": "assistant", "content": full_answer})
        
        yield f"event: done\ndata: {json.dumps({})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
