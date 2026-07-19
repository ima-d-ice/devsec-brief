import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.rag import retrieve_super, build_context, stream_answer_from_context, CONTEXT_DOC_LIMIT

app = FastAPI(
    title="DevSec Brief – RAG API",
    description="RAG-powered dev & cybersec news assistant (Chroma + Groq Llama 3.1).",
    version="0.2.0",
)


@app.middleware("http")
async def add_process_time(request: Request, call_next):
    """Measures end-to-end request latency and adds it as a response header."""
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{ms:.1f}"
    print(f"⏱️  {request.method} {request.url.path} -> {ms:.1f}ms")
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
def ask(req: AskRequest):
    """Standard JSON endpoint (non-streaming)."""
    topic = req.topic if req.topic not in ("all", "") else None
    res = retrieve_super(req.query, topic=topic, k=req.k)
    context = build_context(res)

    if not context.strip():
        return AskResponse(answer="No relevant news found in the index.", sources=[])

    history = chat_history.get(req.session_id, []) if req.session_id else []
    
    from src.rag import generate_answer_from_context
    answer = generate_answer_from_context(context, req.query, history)

    if req.session_id:
        if req.session_id not in chat_history:
            chat_history[req.session_id] = []
        chat_history[req.session_id].append({"role": "user", "content": req.query})
        chat_history[req.session_id].append({"role": "assistant", "content": answer})

    sources_raw = res.get("metadatas") or []
    sources = [Source(**s) for s in sources_raw[0][:CONTEXT_DOC_LIMIT]] if sources_raw else []
    
    return AskResponse(answer=answer, sources=sources)

@app.post("/ask/stream")
def ask_stream(req: AskRequest):
    """SSE Streaming endpoint. Returns sources first, then tokens."""
    topic = req.topic if req.topic not in ("all", "") else None
    res = retrieve_super(req.query, topic=topic, k=req.k)
    context = build_context(res)

    if not context.strip():
        def error_stream():
            yield f"event: error\ndata: {json.dumps({'message': 'No relevant news found.'})}\n\n"
            yield f"event: done\ndata: {json.dumps({})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    sources_raw = res.get("metadatas") or []
    sources = sources_raw[0][:CONTEXT_DOC_LIMIT] if sources_raw else []
    
    session_id = req.session_id or str(uuid.uuid4())
    history = chat_history.get(session_id, [])

    def event_stream():
        sources_payload = json.dumps({"sources": sources, "session_id": session_id})
        yield f"event: sources\ndata: {sources_payload}\n\n"
        
        full_answer = ""
        token_count = 0
        stream_start = time.perf_counter()
        first_token_time = None
        
        for token in stream_answer_from_context(context, req.query, history):
            if first_token_time is None:
                first_token_time = time.perf_counter()
                ttft_ms = (first_token_time - stream_start) * 1000
                print(f"⏱️  TTFT (Time to First Token): {ttft_ms:.1f}ms")
            
            full_answer += token
            token_count += 1
            token_payload = json.dumps({"content": token})
            yield f"event: token\ndata: {token_payload}\n\n"
        
        if first_token_time and token_count > 1:
            generation_time = time.perf_counter() - first_token_time
            tps = token_count / generation_time if generation_time > 0 else 0
            total_time_ms = (time.perf_counter() - stream_start) * 1000
            print(f"⏱️  Streaming complete: {token_count} tokens in {total_time_ms:.1f}ms | TPS: {tps:.1f}")
            
        if session_id not in chat_history:
            chat_history[session_id] = []
        chat_history[session_id].append({"role": "user", "content": req.query})
        chat_history[session_id].append({"role": "assistant", "content": full_answer})
        
        yield f"event: done\ndata: {json.dumps({})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
