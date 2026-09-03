# DevSec-Brief

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker" alt="Docker">
  <img src="https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/Groq-Llama_3.3-f55036.svg" alt="Groq Llama 3.3">
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg?logo=postgresql" alt="PostgreSQL pgvector">
  <a href="https://github.com/ima-d-ice/devsec-brief/actions/workflows/ci.yml"><img src="https://github.com/ima-d-ice/devsec-brief/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/coverage-76%25-brightgreen.svg" alt="Coverage">
  <img src="https://img.shields.io/badge/logging-JSON%20structured-informational.svg" alt="Logging">
</div>

<br>

A full-stack RAG-powered AI news system that aggregates, processes, and serves developer and cybersecurity news.

---

## Architecture & Tech Stack

- **Backend:** Python, FastAPI
- **AI/RAG:** Groq (`llama-3.3-70b-versatile`), ONNX embeddings (`BAAI/bge-m3`), ONNX Cross-Encoder (`mMARCO`)
- **Database:** PostgreSQL 16 + pgvector (Persistent vector and metadata storage)
- **Infrastructure:** Docker, Docker Compose



---

## Core Features

- Automated fetching of DevSec feeds (`fetch_feeds.py`).
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
- Tests: `tests/test_prompt_injection.py` (13 tests) + `tests/test_api_validation.py` (4 tests)

---

## Reliability & Observability

**Testing:** Pytest unit + integration (`76%` coverage). Unit mocks ONNX/DB (`tests/conftest.py`), integration uses `testcontainers` `pgvector/pgvector:pg16` + `TestClient` `src/api.py:14`.

```bash
pip install -r requirements-dev.txt
pytest -q                          # unit + existing (no DB)
pytest -m integration -v          # pgvector integration (needs docker)
pytest -q --cov=src --cov-fail-under=55
```

**Structured Logging:** JSON with `request_id` correlation (`src/logger.py`).

```bash
docker compose up --build -d
docker logs devsec_postgres 2>&1 | jq  # or: docker logs <api> | jq 'select(.stage=="total_retrieval")'
curl -i http://127.0.0.1:8000/ask -H "X-Request-ID: demo-123"  # propagated via X-Request-ID + X-Process-Time-Ms
```

Every stage `embedding` `db_search` `rrf` `rerank` `total_retrieval` `src/rag.py:186` + `TTFT`/`TPS` `src/api.py:137` logs `ms` + `request_id` for `p50/p95` via `jq`.

**CI/CD:** `.github/workflows/ci.yml` → `lint (ruff)` → `test (pytest --cov)` → `integration (pgvector service)` → `docker build + /health smoke` with `actions/cache` for `data/onnx_st` `src/export_st_onnx.py:14`. `cd.yml` pushes `ghcr.io` on `v*.*.*`.

**Docker Hardened:** Non-root `appuser` `HEALTHCHECK curl /health` `EXPOSE 8000` `src/db.py:15 configure=...` fix, `ssl=True` via `certifi` `src/fetch_feeds.py:135`, volume `./data:/app/data` fix `src/rag.py:25`, `restart: unless-stopped`.

---

## Project Structure

- `/src`: Python backend (RAG logic, API endpoints, entity extraction, ONNX compilation).
- `/data`: Persistent Volume (compiled ONNX models, JSON glossary).
- `Dockerfile` & `docker-compose.yml`: Container configuration.
- `entrypoint.sh`: Boot script for automated model compilation and API startup.

---

## Benchmarks

### Latency Performance
The end-to-end RAG pipeline has been heavily optimized for CPU execution. Based on a 50-query benchmark running purely on ONNX across multiple API keys, it yields the following average latencies:

- **Query Expansion & Semantic Embedding:** ~179ms
- **Hybrid DB Search (pgvector + keyword):** ~45ms
- **Cross-Encoder Reranking:** ~264ms
- **Total Retrieval Latency:** `~489ms`


### RAGAS Evaluation Scores
The system has been evaluated using the RAGAS framework for accuracy and contextual relevance:
- **Context Precision:** 83.0% (0.8300)
- **Faithfulness:** 75.7% (0.7570)
- **Answer Relevancy:** 64.3% (0.6430)
