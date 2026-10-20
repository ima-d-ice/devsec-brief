# DevSec-Brief SRE Upgrade — Live TODO

Last updated: 2026-10-20 08:45 UTC
Status: **hardened and locally verified; not production-proven**

Legend: `[x]` done and verified · `[~]` implemented/partly verified · `[ ]` pending

Progress estimate: **~97% overall** · implementation 100% of scoped work ·
local end-to-end verification ~98% · production evidence ~85%

The remaining percentage is deployment/operability evidence, not missing
application code:

- full-history clone, image build/boot from a clone, and GitHub-hosted CI
- backup/restore
- multi-replica and DB failover behavior
- real-Groq capacity and production query mix

## Baseline

- [x] Audit repository (API, RAG, DB, ingestion, Groq, refresh, CI/CD, frontend)
- [x] Branch `sre/hardening`
- [x] Baseline suite: 14 passed
- [x] Current suite: **33 passed** (unit + Postgres integration)
- [x] Real `/ask` and `/ask/stream` success through Groq
- [x] Full Compose stack running on `arm64` / 8 vCPU / ~3.83 GiB Docker VM

## Phase 1 — P0 reliability

- [x] Lazy DB pool; no connections at import
- [x] Pool open/close in FastAPI lifespan
- [x] `/health/live` and dependency-aware `/health/ready`
- [x] Bounded Groq timeouts, retries with jitter, per-key cooldown, circuit breaker
- [x] Explicit default Groq base URL (fixed doubled `/openai/v1` path)
- [x] SSE heartbeat, bounded queue, client-disconnect handling
- [x] SSE synchronous retrieval moved off the event loop
- [x] SSE disconnect counted for both poll and generator-close paths
- [x] Graceful shutdown / pool close
- [x] Regression tests for health, SSE, retries, pool lifecycle

## Phase 2 — Observability

- [x] Prometheus metrics module (HTTP, retrieval, DB, ingestion, Groq, SSE)
- [x] `/metrics` endpoint
- [x] Request correlation IDs and structured JSON logs
- [x] Prometheus scrape config for API, refresh worker, Postgres, self
- [x] 15 alert rules (availability, latency, DB, ingestion, Groq, SSE, meta)
- [x] 9 SLO recording/burn-rate rules
- [x] Alertmanager config and Prometheus `alerting` target
- [x] Grafana provisioning + overview dashboard (12 panels)
- [x] Grafana SLO dashboard (9 panels)
- [x] All four Prometheus targets **UP**
- [x] Grafana/Alertmanager ready; dashboards loaded
- [x] Grafana datasource query for overview panel returns live data
- [x] Watchdog alert firing (rule evaluation proven)
- [x] Real service alert fires and resolves: `DevsecPostgresDown` **firing**
      after 150s, active in Alertmanager, resolved 30s after Postgres recovery
- [x] Readiness alert/dashboard filtered to `job="devsec-api"`
- [x] SLO burn alerts require ≥20 eligible requests/hour (no idle paging)
- [x] SLO ratio rules no longer turn a zero denominator into 0% availability

## Phase 3 — Ingestion reliability

- [x] Per-feed isolation (`return_exceptions=True`)
- [x] Bounded retries with backoff/jitter
- [x] Duplicate-safe upserts and counts
- [x] PostgreSQL advisory lock (no overlapping runs)
- [x] `ingestion_runs` / `ingestion_feed_runs` tables
- [x] Last-success/freshness metrics exposed by refresh worker on `:9101`
- [x] Prometheus scrape job `devsec-refresh`
- [x] Per-article transactional indexing
- [x] Unit tests for feed isolation and config override
- [x] Live partial run: CISA succeeds, HN fails HTTP 419, other feeds continue
- [x] Stale `running` run reconciled to `interrupted` after worker restart
- [x] Freshness alert cleared after a productive partial run
- [x] Feed failure drill: good feed succeeds, bad feed reports HTTP 500

## Phase 4 — Migrations / startup

- [x] Migration runner (`python -m src.migrate`)
- [x] Baseline + `002_ingestion_runs.sql`
- [x] Schema DDL removed from API entrypoint
- [x] Migration integration tests
- [x] Compose `migrate` exits 0 before API/refresh start
- [x] `schema_migrations` contains baseline + 002

## Phase 5 — Load testing

- [x] Mock Groq service built
- [x] k6 smoke, REST, SSE, soak scripts
- [x] Fixed 24-article synthetic load seed
- [x] Cache-bypass mode for cold-path tests
- [x] Baseline REST run: 76 req, 0 failed, 0.939 req/s, p95 15.67s
- [x] SSE run: 62 streams, 0 failed, 1.005 streams/s, p95 13.81s
- [x] Bottleneck identified: CPU ONNX embedding + rerank (~4.4s / 4.6s retrieval)
- [x] 2-worker/2-thread comparison: 0.929 req/s, no gain, 1.82 GiB
- [x] Production cache path: 408 req, 0 failed, 5.079 req/s, p95 44.45ms
- [x] Cache hit rate measured: 397/408 (97.3%)
- [x] Bottleneck/optimization report filled: `docs/LOAD_TEST_REPORT.md`
- [x] Raw evidence saved under `docs/evidence/`

## Phase 6 — Failure injection / incident

- [x] DB down drill: live 200, ready 503, ask 503, ready recovers
- [x] DB slow drill: 503 after 5.72s under a 15s lock; ready recovers
- [x] Groq timeout drill: bounded 503 in 27.71s; live 200
- [x] Feed failure drill: healthy feed completes, bad feed isolated
- [x] SSE disconnect drill: stream started, counter 1→2, active gauge 0
- [x] API restart drill: 64 samples; final live/ready/ask all 200
- [x] Alert fire/resolve drill: `DevsecPostgresDown` at 150s; resolved
- [x] Interrupted refresh run reconciled after restart
- [x] Real postmortem: `docs/incidents/2026-10-20-sse-disconnect-metric.md`
- [x] Failure-injection report filled: `docs/FAILURE_INJECTION.md`

## Phase 7 — SLOs

- [x] SLO rules and burn-rate alerts
- [x] `docs/SLOS.md` with SLI definitions and exclusions
- [x] Error-budget policy documented
- [x] Real alert fire/resolve validated
- [x] Low-traffic/idle guard added and `promtool` validated
- [~] 7-day SLO compliance — **not demonstrated**; no production traffic window
- [ ] Backup/restore drill
- [ ] Multi-replica / DB failover validation

## Phase 8 — Docker / CI/CD

- [x] Multi-stage non-root Dockerfile; image built and imported
- [x] Models reused from local build context (no 2.5 GB download)
- [x] `.dockerignore`
- [x] Compose: postgres, migrate, api, refresh, monitoring, loadtest profiles
- [x] Healthchecks/restart policies/resource limits; refresh healthcheck disabled
- [x] Mock Groq / load-test profiles
- [x] Compose and loadtest profile config validate
- [x] CI: lint, unit, integration, build, security scan (written)
- [ ] CI run on GitHub (not executed locally)
- [x] Deployment/rollback docs
- [x] Fresh shallow clone at `0c93848`: Compose configs valid, 33 tests passed
- [ ] Full image build/boot from a fresh clone on a clean host

## Phase 9 — Docs / final verification

- [x] README rewrite with architecture, verification snapshot, honest limits
- [x] Architecture doc
- [x] Metrics/alerts reference (updated for refresh target and job filters)
- [x] SLO doc (updated with measured status)
- [x] Runbooks
- [x] Known limitations (memory sequencing, HN 419, CPU bottleneck, no backup)
- [x] Security posture
- [x] Load-test report with measured numbers
- [x] Failure-injection report with measured drills
- [x] Incident postmortem with real timeline
- [x] Fresh-clone verification (shallow; config + tests)
- [x] Final hardening commit `0c93848` on `sre/hardening`

## Live verification (2026-10-20)

- [x] `docker compose up -d postgres migrate api` healthy
- [x] Migrate exits 0; applied 2 versions
- [x] `/health/live` 200, `/health/ready` 200
- [x] Metrics endpoint serves Prometheus text
- [x] Prometheus targets: `devsec-api`, `devsec-refresh`, `postgres`,
      `prometheus` all **UP**
- [x] Grafana `/api/health` 200; both dashboards provisioned
- [x] Alertmanager `/-/ready` 200; Watchdog active
- [x] Real `/ask`: 200, 4.36s, 310-char answer, 3 sources
- [x] Cached `/ask`: 200, ~4–10ms
- [x] Real `/ask/stream`: 200, 1,726 bytes, 7 tokens, metrics + done
- [x] k6 smoke: 21/21 checks, 0 failed
- [x] k6 REST cold: 0.939 req/s, p95 15.67s, 0 failed
- [x] k6 REST cache: 5.079 req/s, p95 44.45ms, 0 failed
- [x] k6 SSE: 1.005 streams/s, p95 13.81s, 0 failed
- [x] DB-down and DB-slow recovery evidence
- [x] Groq timeout evidence
- [x] SSE disconnect evidence
- [x] API restart evidence
- [x] Alert fire/resolve evidence
- [x] Feed failure and ingestion restart evidence

## Truthful status notes

- The stack is **production-shaped, not production-proven**.
- Load numbers use a deterministic mock Groq service. Do not call them
  real-provider capacity.
- The cold path misses the 6s latency SLO target on this host (p95 15.67s at
  10 VUs). The cache path is fast only for repeated queries (97.3% hits on a
  fixed set).
- The database drill intentionally produced 503s; the availability burn-rate
  alert fired because the drill consumed real error budget. This is expected
  under the documented policy.
- HN returns HTTP 419 from the Docker network, so ingestion is expected to be
  `partial` unless that feed is fixed/disabled.
- The 3.83 GiB Docker VM cannot run all model services at once; seed/API/refresh
  and mock API must be serialized.
- The fresh-clone gate used a shallow clone of the final branch. A full-history
  clone was blocked by iCloud-evicted historical Git objects on this Mac; a
  full image build/boot from a clone and GitHub CI are still unverified.
- Backup/restore, multi-replica behavior, and real-Groq capacity are still
  unverified.

## Remaining critical path

Completed for this local milestone:

- [x] Final tests and static/config checks.
- [x] Fresh shallow clone validates Compose and the 33-test suite.
- [x] Hardening work committed on `sre/hardening` at `0c93848`; evidence and
      TODO closure committed separately.
- [x] Final tree and unrelated frontend changes preserved.

Production gates still open:

- [ ] Backup/restore drill.
- [ ] Multi-replica / DB failover validation.
- [ ] Real-Groq capacity and production query mix.
- [ ] GitHub-hosted CI run.
- [ ] Full-history clone and full image build/boot from a clean host.

No hard blocker for the local milestone.
