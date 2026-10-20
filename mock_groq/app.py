"""Deterministic OpenAI-compatible mock for latency/load and failure drills.

It implements the one endpoint the Groq SDK needs. Modes let us exercise
429s, 5xxs, timeouts and slow-token streams without touching real keys.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODE = os.getenv("MOCK_GROQ_MODE", "ok")
DELAY_MS = int(os.getenv("MOCK_GROQ_DELAY_MS", "5"))
STREAM_DELAY_MS = int(os.getenv("MOCK_GROQ_STREAM_DELAY_MS", "5"))
ANSWER = os.getenv(
    "MOCK_GROQ_ANSWER",
    "This is a deterministic mock answer for load testing. "
    "It is intentionally short and stable so latency numbers reflect the service.",
)
TIMEOUT_SECONDS = float(os.getenv("MOCK_GROQ_TIMEOUT_SECONDS", "90"))

app = FastAPI(title="Mock Groq")
_flaky_counter = 0


def _completion_body(model: str, content: str) -> dict:
    prompt_tokens = 100
    completion_tokens = max(1, len(content.split()))
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _stream_chunks(model: str, content: str):
    created = int(time.time())
    words = content.split(" ")
    for index, word in enumerate(words):
        token = word if index == len(words) - 1 else word + " "
        payload = {
            "id": "chatcmpl-mock",
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": token},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(payload)}\n\n"
    final = {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


async def _maybe_fail() -> JSONResponse | None:
    global _flaky_counter
    if MODE == "timeout":
        await asyncio.sleep(TIMEOUT_SECONDS)
        return JSONResponse(status_code=504, content={"error": "mock timeout"})
    if MODE == "429":
        return JSONResponse(
            status_code=429,
            content={"error": {"message": "mock rate limit", "type": "rate_limit_error"}},
            headers={"retry-after": "1"},
        )
    if MODE == "500":
        return JSONResponse(
            status_code=500, content={"error": {"message": "mock upstream failure"}}
        )
    if MODE == "flaky":
        _flaky_counter += 1
        if _flaky_counter % 3 != 0:
            return JSONResponse(
                status_code=500, content={"error": {"message": "mock flaky failure"}}
            )
    return None


@app.get("/health")
async def health():
    return {"status": "ok", "mode": MODE}


@app.post("/openai/v1/chat/completions")
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "mock-primary")
    stream = bool(body.get("stream"))
    failure = await _maybe_fail()
    if failure is not None:
        return failure

    if DELAY_MS:
        await asyncio.sleep(DELAY_MS / 1000)

    if not stream:
        return JSONResponse(content=_completion_body(model, ANSWER))

    async def token_stream():
        for chunk in _stream_chunks(model, ANSWER):
            if STREAM_DELAY_MS:
                await asyncio.sleep(STREAM_DELAY_MS / 1000)
            yield chunk

    return StreamingResponse(
        token_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
