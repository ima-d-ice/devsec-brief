# DevSec-Brief

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker" alt="Docker">
  <img src="https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/Groq-Llama_3.3-f55036.svg" alt="Groq Llama 3.3">
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg?logo=postgresql" alt="PostgreSQL pgvector">
</div>

<br>

A full-stack RAG-powered AI news system that aggregates, processes, and serves developer and cybersecurity news.

---

## Architecture & Tech Stack

- **Backend:** Python, FastAPI
- **AI/RAG:** Groq (`qwen/qwen3.8-27b` → `qwen/qwen3.6-27b` → `openai/gpt-oss-120b` fallback chain), ONNX embeddings (`BAAI/bge-m3`), ONNX Cross-Encoder (`mMARCO`)
- **Database:** PostgreSQL 16 + pgvector (Persistent vector and metadata storage)
- **Infrastructure:** Docker, Docker Compose



---

## Core Features

- Scheduled fetching of DevSec feeds (6 RSS sources, 6-hour loop with overlap lock via `refresh` service, `src/refresh.py` + `src/fetch_feeds.py`).
- Entity extraction and semantic chunking using zero-VRAM CPU-optimized ONNX binaries.
- RAG-augmented querying with hybrid search and cross-encoder reranking (`rag.py`).
- Server-Sent Events (SSE) streaming endpoint for frontend integration (`api.py`).

---

## Quick Start (Docker)

```bash
# Clone the repo
git clone https://github.com/ima-d-ice/devsec-brief.git
cd devsec-brief

# Set up environment variables
touch .env
# Add: GROQ_API_KEY=gsk_your_groq_api_key_here

# Build and run the containers
docker compose up --build -d
```

> [!NOTE] 
> On the first boot, the container compiles the INT8 ONNX binaries into `/data`. The API is exposed on `http://127.0.0.1:8000`.

---

## API Reference

**`POST /ask`**
Standard JSON response containing the full synthesized answer and source citations.

```bash
curl -X POST "http://127.0.0.1:8000/ask" \
     -H "Content-Type: application/json" \
     -d '{"query": "What are the latest zero-day vulnerabilities in Linux?", "k": 5}'
```

**`POST /ask/stream`**
For real-time UI integrations. Streams the sources array first, followed by live LLM tokens.

```bash
curl -N -X POST "http://127.0.0.1:8000/ask/stream" \
     -H "Content-Type: application/json" \
     -d '{"query": "How is quantum computing impacting RSA encryption?", "k": 5}'
```

---
 
## Security

### Prompt Injection Mitigations

The system implements defense-in-depth against prompt injection attacks:

| Layer | Protection |
|-------|------------|
| **Ingestion** | RSS feed content sanitized before database storage (`src/fetch_feeds.py`) |
| **Glossary** | Entity definitions sanitized at extraction time (`src/extract_entities.py`) |
| **API Input** | Pydantic validation rejects queries with injection patterns (`src/api.py`) |
| **Query Processing** | User queries sanitized before retrieval and LLM calls (`src/sanitize.py`) |
| **Prompt Structure** | Explicit delimiters (`<<<CONTEXT>>>`, `<<<QUERY>>>`) separate context from instructions (`src/rag.py`) |
| **Chat History** | Conversation history sanitized before re-sending to LLM |

**Implementation:**
- Centralized sanitization utility: `src/sanitize.py` (16 regex patterns covering common injection techniques)
- Input validation: `AskRequest` model rejects queries >2000 chars or containing suspicious patterns
- Structured prompts: System prompt instructs LLM to only use content between explicit delimiters
- Tests: `tests/test_sanitize.py` + `tests/test_api_validation.py` (11 unit tests, CI on every push) + `tests/test_retrieval_integration.py` (3 DB-backed tests: upsert lifecycle, keyword search, cache round-trip; run via `python -m pytest tests/ -q -m integration` with live Postgres)

---

## Project Structure

- `/src`: Python backend (RAG logic, API endpoints, entity extraction, ONNX compilation).
- `/data`: Persistent Volume (compiled ONNX models, JSON glossary).
- `Dockerfile` & `docker-compose.yml`: Container configuration.
- `entrypoint.sh`: Boot script for automated model compilation and API startup.

---

## Retrieval Context

How context is built for every answer (`src/rag.py`, `src/db.py`):

- **Hybrid search:** dense pgvector search over 400-char child chunks runs in parallel with `tsvector` keyword search (CVE-aware tokenization), fused with source-weighted, time-decayed Reciprocal Rank Fusion.
- **Big-to-small:** the CrossEncoder reranks small child chunks for precision then expands hits to deduplicated 1500-char parent docs (`parent_docs`), so the LLM gets coherent passages, not fragments.
- **Capped prompts:** context is capped at 3 parents (~1100 tokens) to stay inside the 8K TPM free-tier budget per Groq key; history is truncated to the last 4 turns.
- **Topic-aware semantic cache:** exact-match fast path first, then vector match (`>0.92` similarity) scoped by topic with 30-day TTL (1-day negative TTL for empty results). Cache hits cost zero LLM calls.
- **Grounded generation:** the system prompt only allows claims from text between `<<<CONTEXT>>>` delimiters; retrieval misses yield "Not enough info" instead of hallucinations (faithfulness: 1.000 measured).

## Benchmarks

### Latency Performance (measured, 94-question probe, k=6, Docker: 6 CPU / 3 GB)
End-to-end retrieval over the live index (321 articles, 1525 chunks), no LLM calls:

| Stage | Avg | p50 | p95 |
|---|---|---|---|
| Query embedding (bge-m3 INT8 ONNX) | 57ms | 55ms | 85ms |
| Hybrid DB search (pgvector + keyword) | 12ms | 11ms | 14ms |
| RRF fusion | 1ms | 1ms | 3ms |
| Cross-encoder rerank, pool of 20 (mMARCO INT8 ONNX) | 358ms | 332ms | 593ms |
| **Total retrieval** | **~431ms** | **~406ms** | **~654ms** |

Tuning: thread-pinned ORT sessions (`intra_op=4`), `OMP/MKL/OpenBLAS=4`, boot warmup, guaranteed container CPUs/RAM — same models and recall, ~2.9× faster than untuned defaults (~1257ms). Rerank is 83% of total and the next lever. Reproduce: temp probe script pattern in `src/eval.py --retrieval-only` (retrieval timings per question, zero Groq calls).


### Evaluation Scores (LLM-as-judge, 94 grounded questions)
The system is evaluated with a Groq LLM judge (separate key shard) over a
94-question corpus grounded in the live index (see `src/eval.py`, `data/eval_corpus.json`):
- **Context Precision:** 94.1% (0.941)
- **Faithfulness (no hallucinations):** 100% (1.000)
- **Answer Relevancy:** 94.5% (0.945)
- **Semantic Similarity (ground truth):** 93.8% (0.938)
- **Avg generation latency:** ~675ms
