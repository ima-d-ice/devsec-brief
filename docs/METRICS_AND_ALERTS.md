# Metrics and alerts

## Scrape targets

| Job | Target | Purpose |
|---|---|---|
| `devsec-api` | `api:8000/metrics` | Application RED, retrieval, cache, DB, Groq, SSE |
| `devsec-refresh` | `refresh:9101/metrics` | Ingestion runs, failures, freshness, content age |
| `postgres` | `postgres-exporter:9187` | Database-level metrics (`pg_up`, connections, etc.) |
| `prometheus` | `localhost:9090` | Self-monitoring |

Ingestion and readiness metrics exist in the default registry of **every** app
process. They are meaningful only on their owning job:

- `devsec_ingestion_*{job="devsec-refresh"}` — freshness and run outcomes.
- `devsec_ready{job="devsec-api"}` — API readiness. The refresh worker exports
  `devsec_ready=0` because it has no readiness endpoint; do not use the bare
  metric in alerts or dashboards.

Prometheus retention is **7 days**. The SLO window is therefore 7 days, not 28.

## Application metrics

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `devsec_http_requests_total` | Counter | `method`, `route`, `status` | Completed requests by route template and status class |
| `devsec_http_request_duration_seconds` | Histogram | `method`, `route` | End-to-end request latency |
| `devsec_http_requests_in_flight` | Gauge | — | Concurrent request handlers |
| `devsec_sse_connections_active` | Gauge | — | Open SSE streams |
| `devsec_sse_disconnects_total` | Counter | — | Streams closed by client disconnect |
| `devsec_sse_stream_duration_seconds` | Histogram | — | SSE stream lifetime |
| `devsec_retrieval_stage_duration_seconds` | Histogram | `stage` | embedding, db_search, rrf, rerank, parent_lookup, total |
| `devsec_retrieval_failures_total` | Counter | `stage`, `reason` | Retrieval failures by stage |
| `devsec_cache_lookups_total` | Counter | `result` | exact/semantic/miss |
| `devsec_rerank_candidates` | Histogram | — | Candidate count sent to reranker |
| `devsec_db_pool_in_use` | Gauge | — | Checked-out connections |
| `devsec_db_pool_wait_seconds` | Histogram | — | Pool acquisition wait |
| `devsec_db_query_duration_seconds` | Histogram | `operation` | Application-observed query latency |
| `devsec_db_connection_failures_total` | Counter | — | Pool acquisition failures |
| `devsec_ingestion_runs_total` | Counter | `result` | success/partial/failed/interrupted |
| `devsec_ingestion_duration_seconds` | Histogram | — | Run duration |
| `devsec_ingestion_articles_total` | Counter | `result` | inserted/updated/skipped/failed |
| `devsec_ingestion_feed_failures_total` | Counter | `feed` | Feed-level failures |
| `devsec_ingestion_last_success_timestamp_seconds` | Gauge | — | Last successful run completion |
| `devsec_ingestion_content_age_seconds` | Gauge | — | Age of newest ingested article |
| `devsec_groq_requests_total` | Counter | `model`, `outcome` | success/rate_limit/timeout/server_error/etc. |
| `devsec_groq_request_duration_seconds` | Histogram | `model` | Upstream attempt latency |
| `devsec_groq_rate_limited_total` | Counter | `key` | 429s by key index |
| `devsec_groq_fallbacks_total` | Counter | `model` | Requests reaching a fallback model |
| `devsec_groq_circuit_state` | Gauge | — | 0 closed, 1 half-open, 2 open |
| `devsec_ready` | Gauge | — | Readiness state |

### Cardinality rules

- Route labels use FastAPI templates, never raw URLs.
- Status labels are `2xx`/`3xx`/`4xx`/`5xx`, never individual codes.
- Query text, session IDs, URLs, keys and exception messages are never labels.
- `feed` is a bounded configured name; a user-supplied feed name would be a
  cardinality risk and is not exposed as a label.

## Alerts

| Alert | Condition | Severity | Runbook |
|---|---|---|---|
| `DevsecApiDown` | `up{job="devsec-api"} == 0` for 2m | critical | `api-down.md` |
| `DevsecNoMetrics` | `absent(devsec_http_requests_total)` for 5m | critical | `api-down.md` |
| `DevsecNotReady` | `devsec_ready{job="devsec-api"} == 0` for 5m | warning | `database-down.md` |
| `DevsecHighErrorRate` | 5xx ratio >2% for 10m | warning | `high-latency.md` |
| `DevsecLatencyP95High` | p95 >6s for 10m | warning | `high-latency.md` |
| `DevsecDbPoolSaturated` | pool in use >=8 for 10m | warning | `database-down.md` |
| `DevsecDbConnectionFailures` | acquisition failures in 5m | critical | `database-down.md` |
| `DevsecPostgresDown` | `pg_up == 0` for 2m | critical | `database-down.md` |
| `DevsecIngestionStale` | `time() - max(devsec_ingestion_last_success_timestamp_seconds{job="devsec-refresh"}) > 8h` for 10m | warning | `ingestion-stale.md` |
| `DevsecIngestionFailed` | failed run in 2h (`job="devsec-refresh"`) | warning | `ingestion-stale.md` |
| `DevsecIngestionNoSuccessMetric` | freshness series absent for 30m | warning | `ingestion-stale.md` |
| `DevsecGroqRateLimited` | >20% 429s for 10m | warning | `groq-outage.md` |
| `DevsecGroqCircuitOpen` | circuit state 2 for 2m | critical | `groq-outage.md` |
| `DevsecSseDisconnects` | >10 disconnects in 10m | warning | `high-latency.md` |
| `Watchdog` | `vector(1)` | none | alert pipeline test |

SLO burn-rate alerts are in `monitoring/rules/slo.yml`. They require at least 20
eligible requests in the 1-hour window, so a zero- or low-traffic period cannot
look like a 0% availability outage. The availability and latency ratio rules
divide directly rather than clamping a zero denominator.

## Dashboards

- **DevSec Brief — Service Overview**: availability, request rate, p95,
  readiness, status classes, cache hit ratio, retrieval stages, DB pool, SSE,
  Groq outcomes, ingestion freshness/runs.
- **DevSec Brief — SLOs**: 7-day availability, error budget remaining, burn
  rate, latency SLI, freshness, ingestion success, readiness.

## Verification status

Verified live on 2026-10-20:

- Prometheus targets `devsec-api`, `devsec-refresh`, `postgres`, and
  `prometheus` are **UP**.
- Prometheus loaded 15 alert rules and 9 SLO rules across 6 rule groups.
- `Watchdog` is firing, proving rule evaluation and the Alertmanager route are
  active.
- `DevsecPostgresDown` was observed **firing** after 150s of Postgres downtime,
  appeared as active in Alertmanager, and **resolved** after recovery.
  Evidence: [`evidence/alert-fire-resolve.txt`](evidence/alert-fire-resolve.txt).
- The drill also fired the availability burn-rate alerts because the injected
  database failures produced real 503 responses. This is expected under the
  documented policy; it is not a false positive.
- Grafana reports ready; both dashboards are provisioned (12 and 9 panels), and
  a Grafana datasource query for the overview request-rate panel returned live
  data.
- The no-op Alertmanager receiver is intentional in this local stack; no paging
  integration is configured.

Re-run the checks with:

```bash
curl -s http://127.0.0.1:9090/api/v1/targets | jq '.data.activeTargets[] | {job,health}'
curl -s http://127.0.0.1:9093/api/v2/alerts | jq
./scripts/failure/alert_check.sh
./scripts/failure/alert_fire_resolve.sh
```
