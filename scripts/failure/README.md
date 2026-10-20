# Failure injection drills

These scripts are intentionally observable: each prints timestamps, HTTP
status codes, and the recovery check. They do not fabricate results.

Run from the repository root with the base stack up:

```bash
docker compose up -d
```

Then pick a drill. Record the output in `evidence/` before writing the
postmortem.

| Script | What it breaks | Expected behavior |
|---|---|---|
| `db_down.sh` | Postgres stopped | liveness 200, readiness 503, `/ask` 503 with `Retry-After`, recovery after start |
| `db_slow.sh` | table lock for 15s | requests slow or 503, pool does not wedge permanently |
| `groq_timeout.sh` | mock Groq mode=timeout | bounded 503, circuit opens, service stays live |
| `feed_drill.py` | one RSS feed returns 500 | other feed is ingested, result reports one failure |
| `sse_disconnect.sh` | client closes SSE after 2s | active SSE gauge returns to 0, disconnect counter increments |
| `api_restart.sh` | API restart under curl loop | liveness, readiness, and a real `/ask` return 200 after restart |
| `alert_check.sh` | inspect Prometheus rules/alerts | Watchdog is firing; rules are loaded |
| `alert_fire_resolve.sh` | Postgres down past the `for: 2m` window | `DevsecPostgresDown` fires in Prometheus/Alertmanager and resolves after recovery |

`groq_timeout.sh`, `sse_disconnect.sh`, and the load drills use the
`loadtest` profile (`mock-groq` + `api-mock`) so they never touch real keys.
