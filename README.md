# DevSec-Brief

A security/dev news RAG service with hybrid Postgres retrieval, CPU-only ONNX
models, grounded Groq generation, REST + SSE APIs, and an SRE-focused Docker
Compose deployment.

> **Status: hardened and locally verified; not production-proven.**
> The Compose stack, real provider path, 33-test suite, load tests, failure
> drills, alert fire/resolve, backup/restore, two-replica routing, and manual
> standby promotion have been exercised on one host. The service is still a
> single-primary, single-host deployment with mock-upstream capacity numbers;
> automatic failover, real-Groq capacity, and hosted CI are not established.
> See [`TODO.md`](TODO.md) and the measured reports:
> [`LOAD_TEST_REPORT.md`](docs/LOAD_TEST_REPORT.md) and
> [`FAILURE_INJECTION.md`](docs/FAILURE_INJECTION.md).

## Why this exists

Most RAG demos stop at “the model answered.” This project treats retrieval and
generation as an operated service:

- what happens when Postgres disappears mid-request?
- what happens when every Groq key is rate-limited?
- how do you know ingestion is stale while `/health` still says OK?
- how do you stream tokens without leaking dead connections?
- how do you prove any of it?

## Architecture

```mermaid
flowchart LR
    Client[Next.js / curl] -->|REST + SSE| API[api: FastAPI]
    API -->|pgvector + tsvector| PG[(Postgres 16 + pgvector)]
    API -->|grounded generation| Groq[Groq / mock-groq]
    Refresh[refresh worker] -->|RSS + index| PG
    Migrate[migrate one-shot] -->|schema| PG
    Prom[Prometheus] -->|scrape /metrics| API
    Prom -->|scrape :9101| Refresh
    Prom -->|scrape| PGExp[postgres-exporter]
    Prom --> AM[Alertmanager]
    Grafana --> Prom
```

Startup is gated: **Postgres healthy → migrate exits 0 → API + refresh start**.
The API no longer creates schema at boot. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Retrieval path

1. Validate and sanitize the query.
2. Exact semantic-cache fast path; then vector cache lookup.
3. On miss: query expansion + bge-m3 INT8 embedding.
4. Parallel pgvector (HNSW) and CVE-aware `tsvector` search.
5. Source-weighted, time-decayed RRF.
6. Cross-encoder rerank; top-k deduplicated **parent** passages fetched in one
   query.
7. Groq generation with bounded retries, model fallback and a circuit breaker.

### Streaming contract

```text
event: sources
event: token
event: token
...
event: metrics
event: done
```

SSE now has client-disconnect detection, heartbeats, a hard duration ceiling,
active/disconnect metrics, and completed-only answer persistence.

## Reliability changes

| Defect | Change |
|---|---|
| DB pool connected at import and leaked at interpreter shutdown | Lazy pool, explicit `open_pool`/`close_pool`, lifespan shutdown |
| `/health` always returned OK | `/health/live` + dependency-aware `/health/ready` (DB + models) |
| Groq calls had no app-level timeout/retry policy | Explicit SDK timeout, bounded attempts, jittered backoff, per-key cooldown, circuit breaker |
| SSE could hang after disconnect | `request.is_disconnected()`, producer queue, heartbeat, max duration; generator-close paths counted in `finally` |
| SSE disconnect alert undercounted real closes | Incomplete streams are counted once on exit; live drill verifies the counter delta |
| One RSS failure aborted the whole ingestion gather | Per-feed isolation and per-entry DB error isolation |
| Refresh failures were masked by a shell loop | One-shot/loop worker with run records, freshness metrics, graceful shutdown |
| Restarted worker left a stale `running` run | Startup reconciliation marks old runs `interrupted` |
| Freshness metrics were invisible to Prometheus | Worker exposes `/metrics` on `refresh:9101`; alert rules filter `job="devsec-refresh"` |
| Overlapping refresh runs | Postgres advisory lock |
| Indexing could delete chunks and fail before insert | Per-article transaction replacement |
| Schema DDL in API entrypoint | Dedicated `migrate` service; API starts only after success |
| No visibility into retrieval stages/DB/upstream | Prometheus metrics + dashboards + alerts |
| Root container | Multi-stage, non-root UID 10001, cap-drop, no-new-privileges |

See [`docs/METRICS_AND_ALERTS.md`](docs/METRICS_AND_ALERTS.md) and
[`docs/SLOS.md`](docs/SLOS.md).

## Verification snapshot (2026-10-20)

Local Docker Desktop: 8 vCPU, ~3.83 GiB RAM, `arm64`. This is a verification
snapshot, not a production capacity claim.

| Check | Measured result |
|---|---|
| Test suite | **33 passed** (unit + Postgres integration) |
| Full-history clone | 14 commits reconstructed from origin + local bundle; `git fsck` clean |
| Backup/restore | 16.1 MB dump; all table counts matched; restore **7s** |
| Two-replica routing | 21 health requests split across both nginx upstreams; REST + SSE 200 |
| Standby promotion | promoted DB writable; API ready; real `/ask` **200**, 432 chars, 3 sources, 2s |
| Real `/ask` | **200**, 4.36s, 310-character answer, 3 sources |
| Cached `/ask` | **200**, ~4–10ms after warm-up |
| Real `/ask/stream` | **200**, 1,726 bytes: `sources`, 7 `token`, `metrics`, `done` |
| REST cold path (mock upstream) | 76 req, 0 failed, **0.94 req/s**, p95 **15.67s** |
| REST cache path (mock upstream) | 408 req, 0 failed, **5.08 req/s**, p95 **44.45ms**, 97.3% cache hits |
| SSE (mock upstream) | 62 streams, 0 failed, **1.0 stream/s**, p95 **13.81s** |
| DB down / slow | liveness held; readiness 503; bounded 503s; ready recovered |
| Groq timeout | bounded 503 in 27.71s; liveness 200 |
| SSE disconnect | stream started, disconnect counted, active gauge returned to 0 |
| API restart | liveness/readiness/retrieval all returned 200 |
| Alert fire/resolve | `DevsecPostgresDown` fired at 150s and resolved after recovery |
| Prometheus targets | `devsec-api`, `devsec-refresh`, `postgres`, `prometheus` all UP |
| Grafana | both dashboards provisioned (12 + 9 panels) and loaded |

Full evidence is in [`docs/evidence/`](docs/evidence/). The full clone was
reconstructed from GitHub origin plus a bundle of the two local-only commits
because this Mac's iCloud had evicted historical local Git objects; a clean
image build from that clone and GitHub CI are being completed. The load numbers
use a deterministic mock Groq service, not real provider capacity. The
cold-path p95 is above the 6s latency SLO target; that is a measured limitation
on this host, not an SLO pass.

## Quick start

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD, at least one GROQ_API_KEY, optional API_KEY
docker compose up -d --build

curl -s http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready
```

Services and UIs:

| Service | URL |
|---|---|
| API | `http://127.0.0.1:8000` |
| Prometheus | `http://127.0.0.1:9090` |
| Grafana | `http://127.0.0.1:3001` |
| Alertmanager | `http://127.0.0.1:9093` |

Ask:

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is CVE-2024-3094 and how do I remediate it?","k":6}'
```

Stream:

```bash
curl -N -X POST http://127.0.0.1:8000/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is CVE-2024-3094?","k":6}'
```

Optional auth/rate limit: set `API_KEY` and `RATE_LIMIT_PER_MINUTE` in `.env`.
When `API_KEY` is set, send `X-API-Key`.

### Load-test stack (no real Groq quota)

```bash
docker compose --profile loadtest up -d postgres migrate mock-groq seed api-mock
docker compose --profile loadtest run --rm k6 run /scripts/smoke.js
```

See [`loadtest/README.md`](loadtest/README.md).

## API

| Endpoint | Behavior |
|---|---|
| `GET /health/live` | Process liveness; no DB dependency |
| `GET /health/ready` | 200 only when DB + models are ready; 503 otherwise |
| `GET /metrics` | Prometheus text |
| `POST /ask` | JSON answer, sources, model, cache flag, per-stage latency |
| `POST /ask/stream` | SSE: sources → tokens → metrics → done |

There is no public TLS, user identity or RBAC in this Compose stack. Put it
behind an authenticated TLS reverse proxy before exposing it. See
[`docs/SECURITY.md`](docs/SECURITY.md).

## Evaluation

The committed eval artifact (`data/eval_results_full.json`) contains **139
questions**. The numbers below are from that artifact, not from the new
reliability work:

| Metric | Score | Target | Status |
|---|---:|---:|---|
| Context precision | 0.647 | ≥ 0.70 | misses |
| Faithfulness | 1.000 | ≥ 0.85 | passes |
| Answer relevancy | 0.647 | ≥ 0.80 | misses |
| Semantic similarity | 0.636 | ≥ 0.75 | misses |
| Avg retrieval latency | 3616 ms | — | — |
| Avg generation latency | 645 ms | — | — |

Reproduce with:

```bash
docker compose --profile eval up --build
```

Reliability changes do not claim retrieval-quality improvements. If retrieval
logic changes, re-run the eval before citing these numbers.

## Load and failure evidence

- [`docs/LOAD_TEST_REPORT.md`](docs/LOAD_TEST_REPORT.md) — measured REST/SSE numbers, bottleneck analysis, cache comparison
- [`docs/FAILURE_INJECTION.md`](docs/FAILURE_INJECTION.md) — DB, Groq, feed, SSE, restart, and alert drills
- [`docs/RUNBOOKS/backup-restore.md`](docs/RUNBOOKS/backup-restore.md) — logical backup, scratch restore, and measured restore time
- [`docs/RUNBOOKS/db-failover.md`](docs/RUNBOOKS/db-failover.md) — streaming standby and manual promotion
- [`docs/RUNBOOKS/multi-replica.md`](docs/RUNBOOKS/multi-replica.md) — nginx two-replica routing
- [`scripts/failure/`](scripts/failure/) — executable drills
- [`docs/incidents/2026-10-20-sse-disconnect-metric.md`](docs/incidents/2026-10-20-sse-disconnect-metric.md) — incident review for the disconnect-counter defect
- [`docs/evidence/`](docs/evidence/) — raw k6, recovery, scale, and drill output

Do not read these results as real-Groq capacity, multi-host availability, or SLO
compliance. The cold path was CPU-saturated at about 0.94 req/s on this host;
the cache path was measured with a repeated query set.

## Testing

```bash
# Unit (no DB required)
python -m pytest -m "not integration" -v

# Integration (Postgres/pgvector required)
DATABASE_URL=postgresql://devsec:devsec@localhost:5432/devsec \
  python -m pytest -m integration -v
```

Current local suite: **33 passed** (unit + integration against local Postgres).
CI adds Ruff syntax/undefined-name checks, migration + integration tests,
Compose config validation, Gitleaks, Trivy, and an image import smoke test.

## Project layout

```text
src/
  api.py               FastAPI, health/readiness, metrics, SSE, auth/rate limit
  rag.py               hybrid retrieval, stage metrics, batch parent expansion
  db.py                lazy pool, schema, cache/chat, ingestion-run records
  groq_pool.py         key pool, timeouts, retries, circuit breaker
  fetch_feeds.py       per-feed async ingestion with isolation
  refresh.py           advisory-locked run loop + freshness metrics
  embed_index.py       per-article transactional index replacement
  migrate.py           idempotent baseline + ordered SQL migrations
  obs.py               Prometheus metric definitions
  resilience.py        retry, circuit breaker, token bucket
  settings.py          environment-backed runtime settings
monitoring/            Prometheus, Alertmanager, Grafana provisioning
loadtest/              k6 smoke/REST/SSE/soak scripts
scripts/failure/       failure drills
docs/                  architecture, SLOs, runbooks, reports
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment and rollback](docs/DEPLOYMENT.md)
- [Metrics and alerts](docs/METRICS_AND_ALERTS.md)
- [SLOs and error-budget policy](docs/SLOS.md)
- [Security posture](docs/SECURITY.md)
- [Runbooks](docs/RUNBOOKS/README.md)
- [Backup and restore](docs/RUNBOOKS/backup-restore.md)
- [Database standby and manual failover](docs/RUNBOOKS/db-failover.md)
- [Two-replica API](docs/RUNBOOKS/multi-replica.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Baseline](docs/BASELINE.md)
- [Live TODO](TODO.md)

## Known limitations (short list)

- Single Postgres primary; manual standby promotion is tested, automatic failover is not.
- Single API worker by default; the two-replica overlay is tested, but Groq key state, circuit breakers, and rate limits remain per process.
- Manual logical backup/restore only; no continuous WAL archiving, PITR, or off-host copy.
- No TLS, user identity, RBAC or WAF in this stack.
- Semantic cache has TTL but no article-change invalidation.
- Mock-upstream load numbers are not real-Groq benchmarks; real-provider sampling is not capacity proof.
- GitHub-hosted CI and a full clean-clone image build remain unproven until run.
- Hacker News still returns HTTP 419 inside Compose; ingestion is expected to report `partial` with that feed failing.
- The 3.83 GiB Docker VM cannot run seed, API, refresh, and api-mock model processes concurrently; model-heavy jobs must be serialized.

Full list: [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

## Tech stack

Python 3.12 · FastAPI · PostgreSQL 16 + pgvector · bge-m3 + mMARCO INT8 ONNX
(CPU) · Groq · Docker Compose · Prometheus · Grafana · Alertmanager · k6 ·
GitHub Actions · Trivy.

## Contact

- GitHub: [ima-d-ice](https://github.com/ima-d-ice)
- Repo: `ima-d-ice/devsec-brief`
