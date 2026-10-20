from __future__ import annotations

import asyncio
import json
import os
import queue
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from src import obs, rag
from src.db import (
    check_db,
    close_pool,
    get_chat_history,
    open_pool,
    save_chat_message,
    save_semantic_cache,
)
from src.logger import bind, get_logger, get_request_id, set_request_id
from src.rag import (
    CONTEXT_DOC_LIMIT,
    build_context,
    check_cache_for_query,
    generate_answer_from_context,
    retrieve_super,
    stream_answer_from_context,
)
from src.resilience import CircuitOpenError, TokenBucketLimiter, UpstreamUnavailable
from src.sanitize import contains_injection_pattern, sanitize_history, sanitize_query
from src.settings import settings

log = get_logger("api")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_limiter = TokenBucketLimiter(settings.rate_limit_per_minute)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Open the pool once and close it on shutdown.

    A database outage at boot must not make the process unkillable: the API
    starts, liveness stays green, readiness reports 503, and requests fail
    fast with a bounded pool timeout until Postgres recovers.
    """
    try:
        open_pool(wait=True, timeout=5.0)
        log.info("api_starting", extra={"fields": {"db": "opened"}})
    except Exception:
        log.exception("db_open_failed_at_startup")
    try:
        yield
    finally:
        close_pool()
        log.info("api_stopped")


app = FastAPI(
    title="DevSec Brief – Production RAG API",
    description="RAG API with semantic caching, bounded upstream calls, and observable operations.",
    version="2.0.0",
    lifespan=lifespan,
)

_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:5500"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observe_http(request: Request, call_next):
    """Correlation ID, latency header, RED metrics and in-flight gauge."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = set_request_id(request_id)
    obs.HTTP_IN_FLIGHT.inc()
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        log.exception("unhandled_request_error")
        raise
    finally:
        duration = max(0.0, time.perf_counter() - started)
        route = obs.route_template(request)
        obs.HTTP_REQUESTS.labels(
            method=request.method,
            route=route,
            status=obs.status_class(status_code),
        ).inc()
        obs.HTTP_DURATION.labels(method=request.method, route=route).observe(duration)
        obs.HTTP_IN_FLIGHT.dec()
        set_request_id("-")
        _ = token


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception):
    log.exception("unhandled_exception")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": get_request_id(),
        },
    )


def require_api_key(request: Request) -> None:
    """Optional API-key gate. Disabled unless API_KEY is configured."""
    if not settings.api_key:
        return
    supplied = request.headers.get("X-API-Key", "")
    if not supplied or not secrets.compare_digest(supplied, settings.api_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def enforce_rate_limit(request: Request) -> None:
    """Per-client token bucket; disabled when RATE_LIMIT_PER_MINUTE=0."""
    if not _limiter.enabled:
        return
    client = request.client.host if request.client else "unknown"
    key = request.headers.get("X-API-Key") or client
    if not _limiter.allow(key):
        retry_after = _limiter.retry_after_seconds(key)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


class AskRequest(BaseModel):
    query: str
    topic: Optional[str] = None
    k: int = 6
    session_id: Optional[str] = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Query must not be empty")
        if len(v) > 2000:
            raise ValueError("Query too long (max 2000 chars)")
        if contains_injection_pattern(v):
            raise ValueError("Query contains suspicious patterns")
        return v

    @field_validator("k")
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


_ready_cache: tuple[float, bool, bool, bool] = (0.0, False, False, False)
_ready_lock = asyncio.Lock()


async def _readiness() -> tuple[bool, bool, bool]:
    global _ready_cache
    now = time.monotonic()
    cached_at, ready, db_ok, models_ok = _ready_cache
    if now - cached_at < settings.readiness_cache_seconds:
        return ready, db_ok, models_ok
    async with _ready_lock:
        cached_at, ready, db_ok, models_ok = _ready_cache
        if time.monotonic() - cached_at < settings.readiness_cache_seconds:
            return ready, db_ok, models_ok
        db_ok = await asyncio.to_thread(
            check_db, settings.readiness_db_timeout_seconds
        )
        models_ok = rag.is_ready()
        ready = bool(db_ok and models_ok)
        _ready_cache = (time.monotonic(), ready, db_ok, models_ok)
        obs.READY.set(1 if ready else 0)
        return ready, db_ok, models_ok


@app.get("/health")
async def health():
    """Backward-compatible liveness endpoint."""
    return {"status": "ok"}


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    ready, db_ok, models_ok = await _readiness()
    payload = {
        "status": "ready" if ready else "not_ready",
        "database": db_ok,
        "models": models_ok,
    }
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/metrics")
async def metrics():
    return obs.metrics_response()


def _sources_from_retrieval(retrieval_res: dict) -> list[Source]:
    sources_raw = retrieval_res.get("metadatas") or []
    if not sources_raw:
        return []
    return [Source(**s) for s in sources_raw[0][:CONTEXT_DOC_LIMIT]]


def _http_503(detail: str, retry_after: int = 30) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)])
def ask(req: AskRequest, response: Response):
    # Sync endpoint: FastAPI runs this in its worker threadpool, so retrieval,
    # reranking, and synchronous Groq calls cannot block the event loop.
    """JSON endpoint with semantic caching, bounded retrieval and generation."""
    safe_query = sanitize_query(req.query)
    topic = req.topic if req.topic not in ("all", "") else None
    started = time.perf_counter()

    cached = None
    q_emb = []
    if settings.cache_enabled:
        try:
            cached, q_emb = check_cache_for_query(safe_query, topic=topic)
        except Exception:
            log.exception("cache_lookup_failed")
            raise _http_503("Database temporarily unavailable") from None

    if cached:
        obs.CACHE_LOOKUPS.labels(result="exact" if cached.get("exact") else "semantic").inc()
        response.headers["X-Cache-Hit"] = "true"
        response.headers["X-Model-Used"] = cached["model_used"]
        bind(
            log,
            event_type="cache_hit",
            topic=topic,
            model=cached["model_used"],
            lookup_ms=cached.get("cache_time_ms"),
        ).info("ask_cache_hit")
        return AskResponse(
            answer=cached["answer"],
            sources=[
                Source(
                    **{
                        k: s.get(k)
                        for k in ("title", "url", "source", "category", "published_at")
                    }
                )
                for s in cached["sources"]
            ],
            model_used=cached["model_used"],
            cache_hit=True,
            latency_breakdown_ms={
                "cache_lookup_ms": cached.get("cache_time_ms"),
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )

    obs.CACHE_LOOKUPS.labels(result="miss").inc()

    try:
        retrieval_res = retrieve_super(
            safe_query, topic=topic, k=req.k, precomputed_q_emb=q_emb or None
        )
    except Exception:
        log.exception("retrieval_failed")
        raise _http_503("Retrieval temporarily unavailable") from None

    context = build_context(retrieval_res)
    if not context.strip():
        return AskResponse(
            answer="No relevant news found in the index.",
            sources=[],
            cache_hit=False,
            latency_breakdown_ms=retrieval_res.get("timings"),
        )

    history = []
    if req.session_id:
        try:
            history = sanitize_history(get_chat_history(req.session_id, limit=6))
        except Exception:
            log.warning("chat_history_unavailable")

    try:
        answer, model_used = generate_answer_from_context(context, safe_query, history)
    except (CircuitOpenError, UpstreamUnavailable) as exc:
        log.warning("generation_unavailable", extra={"fields": {"reason": type(exc).__name__}})
        raise _http_503("Answer generation temporarily unavailable") from None
    except Exception:
        log.exception("generation_failed")
        raise _http_503("Answer generation failed") from None

    sources = _sources_from_retrieval(retrieval_res)

    if req.session_id:
        try:
            save_chat_message(req.session_id, "user", safe_query)
            save_chat_message(req.session_id, "assistant", answer)
        except Exception as exc:
            log.warning("persist_chat_failed", extra={"fields": {"error": type(exc).__name__}})

    if settings.cache_enabled:
        try:
            save_semantic_cache(
                safe_query,
                q_emb,
                answer,
                [s.model_dump() for s in sources],
                model_used,
                topic=topic,
            )
        except Exception as exc:
            log.warning("cache_write_failed", extra={"fields": {"error": type(exc).__name__}})

    response.headers["X-Cache-Hit"] = "false"
    response.headers["X-Model-Used"] = model_used
    bind(
        log,
        event_type="ask_served",
        topic=topic,
        model=model_used,
        retrieval_ms=retrieval_res.get("timings", {}).get("total_retrieval_ms"),
        total_ms=round((time.perf_counter() - started) * 1000, 2),
    ).info("ask_served")

    timings = dict(retrieval_res.get("timings") or {})
    timings["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return AskResponse(
        answer=answer,
        sources=sources,
        model_used=model_used,
        cache_hit=False,
        latency_breakdown_ms=timings,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/ask/stream", dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)])
async def ask_stream(req: AskRequest, request: Request):
    """SSE streaming endpoint with heartbeats, disconnect detection and metrics."""
    safe_query = sanitize_query(req.query)
    topic = req.topic if req.topic not in ("all", "") else None
    session_id = req.session_id or str(uuid.uuid4())

    cached = None
    q_emb = []
    if settings.cache_enabled:
        try:
            cached, q_emb = await asyncio.to_thread(
                check_cache_for_query, safe_query, topic=topic
            )
        except Exception:
            log.exception("cache_lookup_failed_stream")
            raise _http_503("Database temporarily unavailable") from None

    if cached:
        obs.CACHE_LOOKUPS.labels(result="exact" if cached.get("exact") else "semantic").inc()

        async def cached_stream():
            started = time.perf_counter()
            obs.SSE_ACTIVE.inc()
            completed = False
            try:
                yield _sse(
                    "sources",
                    {
                        "sources": cached["sources"],
                        "session_id": session_id,
                        "cache_hit": True,
                    },
                )
                yield _sse("token", {"content": cached["answer"]})
                yield _sse(
                    "metrics",
                    {
                        "cache_hit": True,
                        "model_used": cached["model_used"],
                        "cache_lookup_ms": cached.get("cache_time_ms"),
                        "tokens": len(cached["answer"].split()),
                        "stream_duration_ms": round(
                            (time.perf_counter() - started) * 1000, 2
                        ),
                    },
                )
                completed = True
                yield _sse("done", {})
            finally:
                obs.SSE_ACTIVE.dec()
                obs.SSE_DURATION.observe(max(0.0, time.perf_counter() - started))
                if not completed:
                    obs.SSE_DISCONNECTS.inc()

        return StreamingResponse(
            cached_stream(), media_type="text/event-stream", headers=SSE_HEADERS
        )

    obs.CACHE_LOOKUPS.labels(result="miss").inc()

    try:
        retrieval_res = await asyncio.to_thread(
            retrieve_super,
            safe_query,
            topic=topic,
            k=req.k,
            precomputed_q_emb=q_emb or None,
        )
    except Exception:
        log.exception("retrieval_failed_stream")
        raise _http_503("Retrieval temporarily unavailable") from None

    context = build_context(retrieval_res)
    if not context.strip():

        async def error_stream():
            yield _sse("error", {"message": "No relevant news found."})
            yield _sse("done", {})

        return StreamingResponse(
            error_stream(), media_type="text/event-stream", headers=SSE_HEADERS
        )

    sources_raw = retrieval_res.get("metadatas") or []
    sources = sources_raw[0][:CONTEXT_DOC_LIMIT] if sources_raw else []

    history = []
    try:
        history = sanitize_history(
            await asyncio.to_thread(get_chat_history, session_id, limit=6)
        )
    except Exception:
        log.warning("chat_history_unavailable_stream")

    try:
        token_gen, model_used = await asyncio.to_thread(
            stream_answer_from_context, context, safe_query, history
        )
    except (CircuitOpenError, UpstreamUnavailable):
        log.warning("stream_open_unavailable")
        raise _http_503("Answer generation temporarily unavailable") from None
    except Exception:
        log.exception("stream_open_failed")
        raise _http_503("Answer generation failed") from None

    async def event_stream():
        started = time.perf_counter()
        obs.SSE_ACTIVE.inc()
        completed = False
        stream_finished = False
        disconnected = False
        full_answer = ""
        token_count = 0
        first_token_time: float | None = None
        stop = threading.Event()
        events: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=256)

        def put_event(item: tuple[str, str | None]) -> bool:
            """Bounded put that unblocks when the client disconnects."""
            while not stop.is_set():
                try:
                    events.put(item, timeout=0.5)
                    return True
                except queue.Full:
                    continue
            return False

        def produce() -> None:
            try:
                for token in token_gen:
                    if stop.is_set():
                        return
                    if not put_event(("token", token)):
                        return
                put_event(("done", None))
            except Exception as exc:  # noqa: BLE001 - surfaced as a safe event
                put_event(("error", type(exc).__name__))

        producer = threading.Thread(target=produce, name="sse-producer", daemon=True)
        producer.start()

        try:
            yield _sse(
                "sources",
                {
                    "sources": sources,
                    "session_id": session_id,
                    "cache_hit": False,
                },
            )

            while True:
                if await request.is_disconnected():
                    disconnected = True
                    stop.set()
                    log.info("sse_client_disconnected", extra={"fields": {"session_id": session_id}})
                    break

                elapsed = time.perf_counter() - started
                if elapsed > settings.sse_max_duration_seconds:
                    yield _sse(
                        "error",
                        {"message": "Stream exceeded the maximum duration."},
                    )
                    break

                try:
                    kind, payload = await asyncio.to_thread(
                        events.get, True, settings.sse_heartbeat_seconds
                    )
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue

                if kind == "token" and payload is not None:
                    if first_token_time is None:
                        first_token_time = time.perf_counter()
                    full_answer += payload
                    token_count += 1
                    yield _sse("token", {"content": payload})
                elif kind == "done":
                    completed = True
                    break
                elif kind == "error":
                    log.warning(
                        "sse_upstream_error",
                        extra={"fields": {"error": payload, "session_id": session_id}},
                    )
                    yield _sse(
                        "error",
                        {"message": "Answer generation was interrupted."},
                    )
                    break

            if disconnected:
                # The client is gone; do not write further events or persist
                # a partial answer. The producer observes ``stop`` and exits.
                return

            ttft_ms = (
                round((first_token_time - started) * 1000, 2)
                if first_token_time is not None
                else 0
            )
            generation_time = (
                time.perf_counter() - first_token_time
                if first_token_time is not None
                else 0.001
            )
            tps = round(token_count / generation_time, 1) if generation_time > 0 else 0
            total_stream_ms = round((time.perf_counter() - started) * 1000, 2)

            yield _sse(
                "metrics",
                {
                    "cache_hit": False,
                    "model_used": model_used,
                    "retrieval_timings": retrieval_res.get("timings"),
                    "ttft_ms": ttft_ms,
                    "tokens": token_count,
                    "tps": tps,
                    "stream_duration_ms": total_stream_ms,
                },
            )

            bind(
                log,
                event_type="stream_completed",
                model=model_used,
                ttft_ms=ttft_ms,
                tps=tps,
                tokens=token_count,
                stream_ms=total_stream_ms,
                disconnected=disconnected,
            ).info("stream_completed")

            if completed and full_answer and not disconnected:
                try:
                    await asyncio.to_thread(
                        save_chat_message, session_id, "user", safe_query
                    )
                    await asyncio.to_thread(
                        save_chat_message, session_id, "assistant", full_answer
                    )
                    if settings.cache_enabled:
                        await asyncio.to_thread(
                            save_semantic_cache,
                            safe_query,
                            q_emb,
                            full_answer,
                            sources,
                            model_used,
                            topic=topic,
                        )
                except Exception as exc:
                    log.warning(
                        "stream_persist_failed",
                        extra={"fields": {"error": type(exc).__name__}},
                    )

            stream_finished = True
            yield _sse("done", {})
        finally:
            stop.set()
            if not stream_finished:
                # Covers both request.is_disconnected() and the case where
                # Starlette closes the generator without a detectable poll.
                obs.SSE_DISCONNECTS.inc()
            obs.SSE_ACTIVE.dec()
            obs.SSE_DURATION.observe(max(0.0, time.perf_counter() - started))
            # Give the producer a moment to observe stop. Only close the
            # generator if its thread is no longer iterating it; closing a
            # generator from another thread while it is executing raises and
            # can mask the real disconnect.
            try:
                producer.join(timeout=1.0)
            except RuntimeError:
                pass
            if not producer.is_alive():
                try:
                    token_gen.close()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )
