# src/api.py

from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.rag import answer_question

# ---------- FastAPI app ----------

app = FastAPI(
    title="DevSec Brief – RAG API",
    description="RAG-powered dev & cybersec news assistant (Chroma + Groq Llama 3.1).",
    version="0.1.0",
)

# ---------- CORS (for frontend) ----------

# In dev we can allow all origins; later you can restrict
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # ["http://localhost:5500", "http://127.0.0.1:5500"] etc. in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Schemas ----------


class AskRequest(BaseModel):
    query: str
    topic: Optional[str] = None  # "webdev", "cybersec", or None
    k: int = 6


class Source(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    category: Optional[str] = None
    published_at: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    sources: List[Source]


# ---------- Routes ----------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    """
    RAG endpoint: given a query (+ optional topic), returns answer + sources.
    """
    topic = req.topic if req.topic not in ("all", "") else None
    result = answer_question(req.query, topic=topic, k=req.k)

    sources_raw: List[Dict[str, Any]] = result.get("sources") or []
    sources = [
        Source(
            title=s.get("title"),
            url=s.get("url"),
            source=s.get("source"),
            category=s.get("category"),
            published_at=s.get("published_at"),
        )
        for s in sources_raw
    ]

    return AskResponse(answer=result["answer"], sources=sources)
