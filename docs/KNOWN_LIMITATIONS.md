# Known limitations

This is a deliberate, honest list. None of these are hidden by the README.

## Reliability

- Postgres is a single primary; there is no automatic failover. The optional
  replication overlay supports manual standby promotion only.
- Compose restarts crashed containers, but there is no orchestrator-level
  rescheduling or node failure handling.
- The API starts even when Postgres is down (by design) and reports not-ready;
  `depends_on` only gates initial startup, not later outages.
- Groq key state, cooldowns and the optional rate limiter are per process.
  The optional two-replica overlay shares Postgres cache/chat state, but cannot
  enforce a global admission limit without shared state.
- The circuit breaker is per process; a restart resets it.
- SSE producer threads are daemon threads. A hard disconnect can leave a
  blocked upstream read until the client timeout; the request no longer holds
  the response, but it is not an instant upstream cancellation.
- The refresh lock prevents overlapping runs but does not resume a partially
  completed run; the next run starts from current articles/hashes. A hard worker
  crash leaves a `running` row until the next startup reconciliation (30-minute
  threshold) marks it `interrupted`.
- The 3.83 GiB Docker VM cannot run the seed job, API, refresh worker, and
  `api-mock` model process at the same time. Concurrent model loading caused an
  OOM kill (`ExitCode=137`) during this work. Run those jobs sequentially.
- Hacker News returns HTTP 419 from the Docker network. Ingestion records a
  `partial` run when the other feeds succeed; this is expected behavior in this
  environment, not a successful full-feed run.

## Data

- Ingestion is append/update only; there is no article deletion policy for
  upstream removals beyond optional chunk pruning.
- The semantic cache has a TTL but no explicit invalidation when an article
  changes. Cache entries can outlive source updates until expiry.
- Backups are manual logical `pg_dump` archives; there is no continuous WAL
  archiving, off-host copy, or point-in-time recovery. A restore was executed
  into a scratch database and row counts matched. RPO is the newest dump age.
- No data retention policy for chat history or cache.
- Chat history persistence is completed-only; interrupted streams do not save a
  partial answer.

## Retrieval quality

- The committed eval misses three of four targets; see the README/eval
  artifacts. Reliability work does not claim to improve retrieval quality.
- Reranking 20 candidates is the dominant retrieval cost. Cold-path throughput
  on the recorded 8-vCPU host was ~0.94 req/s with p95 ~15.7s at 10 VUs. This is
  below the 6s latency SLO target; the service does not claim SLO compliance.
- Adding a second Uvicorn worker did not improve throughput on the fixed CPU
  budget and used ~1.82 GiB. The bottleneck is CPU ONNX inference, not the
  event loop.
- The eval corpus is not a production traffic sample.

## Observability

- Prometheus retention is 7 days; no long-term remote storage.
- No distributed tracing (OpenTelemetry) yet.
- Both Grafana dashboards are provisioned and loaded; a datasource query for
  the overview request-rate panel returned live data. Panels were not
  screenshot-reviewed on every viewport.
- Alertmanager uses a no-op local receiver; no paging integration.
- SLO burn alerts require at least 20 eligible requests in the 1-hour window to
  avoid low-traffic pages. A full idle-period live test was not run.
- Postgres exporter provides database metrics, but no query-level slow-log
  pipeline.

## Security / operations

- No TLS, user identity, RBAC or WAF in this stack.
- Optional API key and rate limit are not a complete public API security model.
- No automated dependency update bot or SBOM publication yet.
- No multi-region, disaster-recovery or chaos testing beyond the documented
  drills.
- Frontend security and accessibility were not part of this milestone.

## Verification status

The Compose stack has been booted and the API, migrations, scrape targets,
Grafana, Alertmanager, ingestion path, real `/ask`/SSE path, load runs, failure
drills, alert fire/resolve, backup/restore, two-replica routing, and a manual
standby promotion have been exercised. A full-history clone validated both
Compose configurations and the 33-test suite. Automatic failover, full
point-in-time recovery, real-Groq capacity, and hosted CI remain unverified.
This is **production-shaped, not production-proven**.
