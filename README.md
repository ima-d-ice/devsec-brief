# DevSec-Brief

A self-hosted RAG service for security and developer news: RSS ingestion → hybrid Postgres retrieval → grounded answers over REST and SSE.

I built this as a final-year B.Tech project around the parts a RAG demo usually skips: ingestion, retrieval quality, streaming, failure handling, and operations. The backend is verified locally and in GitHub Actions; it is production-shaped, not production-proven.

[![CI](https://github.com/ima-d-ice/devsec-brief/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ima-d-ice/devsec-brief/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.150-005571?logo=fastapi)
![Postgres](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

## Key highlights

- **Hybrid retrieval:** bge-m3 INT8 ONNX embeddings + pgvector HNSW, Postgres full-text search, source-weighted/time-decayed RRF, and mMARCO reranking — all on CPU.
- **Measured cache impact:** 5.08 req/s at p95 44.45 ms with a 97.3% hit rate on a repeated query set, versus 0.94 req/s at p95 15.67 s on the cold path.
- **Failure drills:** bounded 503s with liveness staying 200 during DB outages; Groq timeout bounded at 27.71 s; SSE disconnects counted correctly.
- **Operational surface:** 15 alert rules, 9 SLO rules, two Grafana dashboards, Alertmanager routing, 33 tests, and CI image/import checks.
- **Measured quality:** 139-question evaluation; faithfulness 1.000, context precision 0.647, answer relevancy 0.647, semantic similarity 0.636.

## Demo

`[TODO: replace with a 20–30 second demo GIF at assets/demo.gif]`

Record: `docker compose ps` → `/health/ready` → a real `/ask` JSON response → `/ask/stream` (`sources` → `token` → `metrics` → `done`) → Grafana for 2–3 s. Use 1280×720 or larger, keep the GIF under ~10 MB, and save it at `assets/demo.gif`.

A real-provider smoke request returned **200 in 4.36 s**, with a 310-character answer and 3 sources. The stream returned 1,726 bytes: one `sources` event, seven `token` events, one `metrics` event, and `done`.

## Architecture

Startup is gated: **Postgres healthy → `migrate` exits 0 → API and refresh worker start**. After startup, the API survives a database outage: liveness stays green and readiness reports 503 until dependencies recover.

```mermaid
flowchart LR
    Client[curl / Next.js shell] -->|REST + SSE| API[FastAPI api]
    API -->|hybrid search| PG[(Postgres 16 + pgvector)]
    API -->|grounded answer| Groq[Groq API / mock]
    Refresh[refresh worker] -->|6 RSS feeds| Feeds[External feeds]
    Refresh -->|upsert + index| PG
    Migrate[migrate one-shot] -->|schema| PG
    Prom[Prometheus] -->|scrape| API
    Prom -->|scrape| Refresh
    Prom -->|scrape| PGX[postgres-exporter]
    Prom --> AM[Alertmanager]
    Grafana --> Prom
```

Request path: validate/sanitize → exact/semantic cache → embedding → parallel pgvector and `tsvector` search → RRF fusion → cross-encoder rerank → parent passage lookup → Groq generation.

SSE contract: `sources` → repeated `token` → `metrics` → `done`, with heartbeats, a bounded queue, disconnect detection, a duration ceiling, and completed-only persistence.

## Features

**Retrieval and generation**
- Hybrid dense + keyword search with source weights and temporal decay.
- Big-to-small retrieval: 400-character children embedded; 1,500-character parent passages sent to the model.
- Exact and near-duplicate semantic cache (cosine similarity > 0.92).
- CPU ONNX embedding/reranking; multi-key Groq pool with primary, fallback, and safety-net models.

**Ingestion**
- Six RSS feeds with per-feed isolation, retries, and duplicate-safe upserts.
- Transactional per-article index replacement.
- Postgres advisory lock prevents overlapping runs.
- Run history, per-feed outcomes, and freshness metrics.

**Reliability and API**
- Separate liveness and dependency-aware readiness endpoints.
- Lazy DB pool, bounded acquisition, and `statement_timeout`.
- Groq timeout, bounded retries, jittered backoff, key cooldowns, and circuit breaker.
- SSE heartbeats, disconnect handling, and graceful shutdown.
- Idempotent migrations; no schema DDL at API boot.

**Observability, security, operations**
- Prometheus metrics for HTTP, retrieval, cache, DB, ingestion, Groq, and SSE.
- 15 alert rules, 9 SLO rules, Grafana dashboards, Alertmanager routing.
- Optional API key, token-bucket rate limit, CORS allow-list, query caps, and injection-pattern rejection.
- Non-root image, dropped capabilities, `no-new-privileges`; secrets via `.env`.
- Optional two-replica nginx overlay and manual Postgres standby promotion.

## Benchmarks / Results

**Method:** Apple Silicon `arm64`, Docker Desktop, 8 vCPU / ~3.83 GiB RAM. API 6 CPU / 3 GiB, one Uvicorn worker, four ONNX threads. Upstream is deterministic `mock-groq`; dataset 54 articles / 1,126 chunks / 280 parents; k6 0.54.0; REST 10 VUs for 60 s; SSE 5 VUs for 60 s.

| Scenario | Requests / streams | Failures | Throughput | p95 |
|---|---:|---:|---:|---:|
| REST cold path, cache bypassed | 76 | 0 | 0.939 req/s | 15.67 s |
| REST cache path | 408 | 0 | 5.079 req/s | 44.45 ms |
| SSE | 62 | 0 | 1.005 streams/s | 13.81 s |
| Real Groq `/ask` sample | 1 | 0 | 4.36 s total | — |

The cache result is a 97.3% hit rate on a fixed repeated query set, not a general throughput claim. The cold path is CPU-bound and misses the 6-second latency target. A second Uvicorn worker did not improve throughput (0.929 req/s) and used ~1.82 GiB.

**Evaluation:** 139 questions, generated with `qwen/qwen3.8-27b`.

| Metric | Score | Target | Result |
|---|---:|---:|---|
| Context precision | 0.647 | ≥ 0.70 | misses |
| Faithfulness | 1.000 | ≥ 0.85 | passes |
| Answer relevancy | 0.647 | ≥ 0.80 | misses |
| Semantic similarity | 0.636 | ≥ 0.75 | misses |
| Avg retrieval latency | 3,616 ms | — | — |
| Avg generation latency | 645 ms | — | — |

Reproduce the load tests:

```bash
docker compose --profile loadtest up -d postgres migrate mock-groq seed api-mock
docker compose --profile loadtest run --rm k6 run /scripts/smoke.js
docker compose --profile loadtest run --rm -e DURATION=60s k6 run /scripts/rest.js
docker compose --profile loadtest run --rm -e VUS=5 -e DURATION=60s k6 run /scripts/sse.js
```

Cache-path runs need `LOADTEST_CACHE_ENABLED=true`. See [`loadtest/README.md`](loadtest/README.md).

## Design decisions and trade-offs

**Hybrid retrieval over dense-only.** CVEs, product names, and version strings are exact-token problems; dense search alone misses them. Combining pgvector with `tsvector` and RRF improves keyword coverage at the cost of more ranking state. The evaluation still misses context precision, so this is not solved.

**Big-to-small retrieval.** Embedding 400-character children improves recall; expanding to 1,500-character parents gives the model better context. Parents are fetched in one query to avoid N+1 lookups. The trade-off is a second storage layer and more index maintenance.

**CPU ONNX plus semantic cache over a GPU dependency.** CPU inference runs on an ordinary Docker host. The cache accelerates repeated questions but not cold retrieval; the cold path remains CPU-bound. A GPU or smaller reranker is the next capacity decision, not a free win.

**Fail fast on dependency problems.** Bounded retries, pool timeouts, and a circuit breaker return 503s while liveness stays 200, instead of hanging for the duration of a DB lock or upstream timeout. The cost is visible failure during a prolonged outage.

**SSE producer thread plus bounded queue.** Groq's Python stream is synchronous; blocking the event loop would stall other requests. A daemon producer feeds a bounded queue while the async loop handles heartbeats, disconnects, and the duration ceiling. A hard disconnect can leave an upstream read blocked until the client timeout.

## Quick start

Requires Docker Compose v2.24+, ~8 GB RAM recommended, and a Groq API key. No GPU. The first build downloads and bakes ONNX models, so it takes several minutes.

```bash
git clone https://github.com/ima-d-ice/devsec-brief.git
cd devsec-brief

cp .env.example .env
# Set GROQ_API_KEY, POSTGRES_PASSWORD, and optional API_KEY / GRAFANA_ADMIN_PASSWORD

docker compose up -d --build
docker compose ps
```

```bash
curl -s http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready

curl -s -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the latest CISA advisory about Schneider Electric?","k":3}'

curl -N -X POST http://127.0.0.1:8000/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is CVE-2024-3094?","k":3}'
```

| Service | URL |
|---|---|
| API | `http://127.0.0.1:8000` |
| Prometheus | `http://127.0.0.1:9090` |
| Grafana | `http://127.0.0.1:3001` |
| Alertmanager | `http://127.0.0.1:9093` |

Stop with `docker compose down`; add `-v` only to delete the Postgres volume. No-quota load-test path:

```bash
docker compose --profile loadtest up -d postgres migrate mock-groq seed api-mock
docker compose --profile loadtest run --rm k6 run /scripts/smoke.js
```

## Project structure

```text
src/
  api.py               FastAPI routes, health/readiness, SSE, auth, rate limits
  rag.py               hybrid retrieval, cache, reranking, prompt construction
  db.py                lazy pool, schema, pgvector/tsvector queries, cache/chat
  groq_pool.py         key pool, retries, cooldowns, circuit breaker
  fetch_feeds.py       six RSS feeds with per-feed isolation
  refresh.py           advisory-locked ingestion loop + freshness metrics
  embed_index.py       chunking, parent documents, transactional indexing
  migrate.py           idempotent baseline + ordered SQL migrations
  obs.py               Prometheus metric definitions
  resilience.py        retry, circuit breaker, token bucket
  settings.py          environment-backed runtime settings
tests/                 33 unit and Postgres integration tests
migrations/            ordered SQL migrations
loadtest/              k6 smoke, REST, SSE, and soak scripts
monitoring/            Prometheus rules, Alertmanager, Grafana provisioning
scripts/               backup, replication, and failure-injection drills
devsec-brief-frontend/ minimal Next.js shell; not part of the verified API scope
```

## Testing

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d postgres
set -a; source .env; set +a
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"
python -m src.migrate
pytest -q
```

Current suite: **33 passed**. Coverage includes validation/sanitization, health/readiness, metrics, SSE event order, retry deadlines, circuit breaking, token-bucket refill, ingestion isolation, migration idempotency, DB pool lifecycle, and Postgres retrieval/cache integration.

Unit tests stub transformer imports in `tests/conftest.py`; integration tests need Postgres + pgvector. CI runs Ruff, compilation, unit and integration tests, Compose validation, Gitleaks, Trivy, a clean image build, baked-model assertions, and an `src.api` import smoke.

## Limitations and future work

- Single Postgres primary. Standby promotion is manual; no automatic failover, fencing, continuous WAL/PITR, or off-host backup copy.
- Cold retrieval is CPU-bound at ~0.94 req/s and misses the 6-second target.
- Load tests use a deterministic mock. One real-provider request proves the path works, not real-Groq capacity.
- The 139-question evaluation misses three of four quality targets.
- Rate limits, Groq key state, and circuit breakers are per process; a multi-replica deployment needs a shared store.
- No TLS, identity, RBAC, or WAF. Use an authenticated TLS proxy before exposing the stack.
- The tracked frontend is a minimal shell; the UI and accessibility pass are future work.

Next: improve retrieval/reranking quality, add shared rate-limit and circuit state, automated HA/PITR, and finish the UI.

## Tech stack

- **Backend:** Python 3.12, FastAPI, Uvicorn, psycopg 3
- **Retrieval:** Postgres 16 + pgvector, `tsvector`, bge-m3 ONNX, mMARCO ONNX
- **Generation:** Groq (`qwen/qwen3.8-27b`, fallback and safety-net models)
- **Infrastructure:** Docker Compose, Prometheus, Grafana, Alertmanager
- **Testing:** pytest, k6, GitHub Actions, Gitleaks, Trivy

## Contact

GitHub: [@ima-d-ice](https://github.com/ima-d-ice)

`[TODO: add email or LinkedIn]`
