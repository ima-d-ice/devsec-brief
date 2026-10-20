# SLOs and error-budget policy

## Scope

User-facing endpoints are `/ask` and `/ask/stream`. Health, readiness, metrics
and validation-rejected requests are excluded from the availability SLI:
client mistakes (4xx) are not service failures.

## SLOs

| SLO | SLI | Target | Window |
|---|---|---|---|
| Availability | non-5xx / all requests on `/ask` + `/ask/stream` | **99.5%** | rolling 7 days |
| Latency | fraction of `/ask` requests under **6s** | **95%** | rolling 7 days |
| Freshness | last successful ingestion < **8h** old | **99%** of time | rolling 7 days |
| Ingestion success | successful runs / all runs | **95%** | rolling 7 days |

Why 7 days: Prometheus retention is 7 days. A 28-day SLO would require remote
storage and is intentionally not claimed.

## Error budget

Availability budget = `1 - 0.995 = 0.5%` of eligible requests over 7 days.

- **Burn rate 1h > 14.4x**: page; budget exhausted in ~2 days at this rate.
- **Burn rate 1h > 6x**: ticket; investigate within the same day.
- **Budget exhausted**: freeze non-reliability changes until the budget
  recovers; reliability work takes priority.
- **Fast burn during a known upstream outage**: follow `groq-outage.md`; do not
  relax the SLO to hide the incident.

## PromQL

```promql
# Availability ratio, 5m
sum(rate(devsec_http_requests_total{route=~"/ask|/ask/stream",status!~"5xx"}[5m]))
/
clamp_min(sum(rate(devsec_http_requests_total{route=~"/ask|/ask/stream"}[5m])), 1e-9)

# Latency SLI, 1h
sum(rate(devsec_http_request_duration_seconds_bucket{route="/ask",le="6"}[1h]))
/
clamp_min(sum(rate(devsec_http_request_duration_seconds_count{route="/ask"}[1h])), 1e-9)

# Freshness (worker scrape job)
time() - max(devsec_ingestion_last_success_timestamp_seconds{job="devsec-refresh"})
```

## Exclusions and caveats

- SSE latency is measured separately (TTFT, tokens/s, stream duration); a long
  stream is not automatically a latency SLO failure.
- Planned maintenance is not excluded automatically. If maintenance creates
  5xx responses, it consumes budget; this is deliberate.
- The load-test stack uses a mock upstream. Load-test numbers do not prove the
  production Groq SLO; they prove the service's own behavior under controlled
  upstream latency.
- No multi-region or multi-replica availability claim is made. Postgres is a
  single primary in this Compose deployment.
- The SLO rules are defined and `promtool`-validated. One real alert
  (`DevsecPostgresDown`) has fired and resolved. That is alert-path evidence,
  not 7-day SLO compliance.
- The measured cold-path p95 of 15.67s at 10 VUs misses the 6s latency target;
  the cache path p95 was 44.45ms on a repeated query set. See
  `docs/LOAD_TEST_REPORT.md`. No production traffic sample exists, so the SLO
  remains **defined, not demonstrated**.
- SLO burn alerts require at least 20 eligible requests in the 1-hour window to
  avoid paging on idle or tiny samples. A full idle-period live validation was
  not run.
