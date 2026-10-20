# Runbook: high latency

Alerts: `DevsecLatencyP95High`, `DevsecHighErrorRate`,
`DevsecSseDisconnects`.

## Triage by stage
1. Open the **Service Overview** dashboard.
2. Compare p95 for:
   - `embedding`
   - `db_search`
   - `rrf`
   - `rerank`
   - `parent_lookup`
   - `total_retrieval`
3. Check `devsec_rerank_candidates` (20 is the current pool).
4. Check DB pool in use / wait and Postgres exporter metrics.
5. Check Groq latency and outcomes; generation time is separate from retrieval.

## Likely causes
- Rerank over 20 candidates on a constrained CPU.
- HNSW/tsvector query contention or missing indexes.
- Pool saturation from slow queries.
- SSE client/proxy timeouts causing reconnects.
- Upstream Groq tail latency.

## Action
- CPU saturation: reduce retrieval concurrency or increase CPU allocation.
- DB saturation: identify slow queries; do not raise pool size without evidence.
- Rerank dominates: reduce candidate pool only after checking retrieval quality;
  this is a quality/latency trade-off, not a free win.
- SSE disconnects: confirm reverse-proxy buffering is disabled and heartbeat is
  below the proxy idle timeout.
- Upstream: follow [groq-outage.md](groq-outage.md).

## Verification
- p95 returns below 6s for `/ask`.
- SSE `done` events complete and active gauge returns to 0 after clients leave.
- Error rate is below 2%.
