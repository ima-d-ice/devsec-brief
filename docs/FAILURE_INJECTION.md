# Failure injection report

**Status: drills executed on 2026-10-20 against the local Compose stack.**
Every drill writes a timestamped evidence file to `docs/evidence/`. The service
is still a single-host Compose deployment; these results do not prove
multi-node, multi-replica, or cloud failover behavior.

## Matrix

Drills 9–11 cover recovery and scale, not only failure. Backup/restore is
logical and manual; standby promotion is manual; the second API replica shares
Postgres state but not per-process Groq/rate-limit state.

| Drill | Command | Expected | Observed | Result |
|---|---|---|---|---|
| DB down | `bash scripts/failure/db_down.sh` | live 200, ready 503, ask 503, ready recovers | live 200, ready 503, ask 503 in 13s, ready 200 ~6s after start | **PASS** |
| DB slow | `bash scripts/failure/db_slow.sh` | bounded wait/503, ready recovers | 503 after 5.72s while a 15s table lock was held; ready 200 after release | **PASS** |
| Groq timeout | `bash scripts/failure/groq_timeout.sh` | bounded 503, live 200 | 503 after 27.71s, live 200; mock restored | **PASS** |
| Feed failure | `python scripts/failure/feed_drill.py` | healthy feed completes, bad feed reported | good feed success; bad feed HTTP 500 after two retries; no cancellation | **PASS** |
| SSE disconnect | `bash scripts/failure/sse_disconnect.sh` | stream starts, disconnect counted, active gauge returns to 0 | 926-byte partial stream; disconnect counter 1 → 2; active 0 | **PASS** (after fixing a metric defect) |
| API restart | `bash scripts/failure/api_restart.sh` | API restarts, requests resume | 64 samples: 33 × 200, 31 connection failures; final live/ready/ask 200 | **PASS** |
| Alert ingestion | `bash scripts/failure/alert_fire_resolve.sh` | a real service alert fires and resolves | `DevsecPostgresDown` firing at 150s, active in Alertmanager, gone 30s after recovery | **PASS** |
| Watchdog | `bash scripts/failure/alert_check.sh` | rule evaluation and alert pipeline active | `Watchdog` firing; 6 rule groups loaded | **PASS** |
| Ingestion restart | observed during refresh restart | abandoned run marked interrupted; next run completes | run 10 → `interrupted`; run 12 → `partial`; freshness metric current | **PASS** |

## Drill 1: Postgres unavailable

Evidence: [`evidence/db-down.txt`](evidence/db-down.txt)

- Start: `2026-10-20T07:31:55Z`
- Detection: readiness and `/ask` failed while liveness stayed 200.
- User-visible behavior: `/ask` returned
  `503 {"detail":"Database temporarily unavailable"}`.
- Readiness: `503` during the outage.
- Recovery: Postgres started at `07:32:08Z`; readiness returned `200` at
  `07:32:14Z` (about 6s).
- Data loss: none observed in this drill. The API was not writing an answer at
  the moment of shutdown.
- Notes: the API did not restart. It stayed alive and reported dependency
  failure, which is the intended liveness/readiness split.

## Drill 2: Postgres slow

Evidence: [`evidence/db-slow.txt`](evidence/db-slow.txt)

- Start: `2026-10-20T07:39:47Z`
- Injection: `ACCESS EXCLUSIVE` lock on `article_chunks` held for 15s.
- User-visible behavior: `/ask` returned
  `503 {"detail":"Retrieval temporarily unavailable"}` after **5.72s**, rather
  than hanging for the full lock duration.
- Mechanism: the DB pool acquisition timeout bounded the wait.
- Recovery: readiness `200` after the lock was released, at `07:40:04Z`.
- Note: this is a fail-fast response, not a successful slow response. A larger
  pool or longer timeout would trade latency for success; that is a product
  decision, not a free improvement.

## Drill 3: Groq timeout

Evidence: [`evidence/groq-timeout.txt`](evidence/groq-timeout.txt)

- Start: `2026-10-20T07:24:27Z` against `api-mock` with cache bypassed.
- Injection: `mock-groq` switched to timeout mode.
- User-visible behavior: `/ask` returned
  `503 {"detail":"Answer generation temporarily unavailable"}` after
  **27.71s**.
- Liveness: `200` throughout the check.
- Bounded behavior: the app-level deadline and retry policy prevented an
  unbounded request. The mock was restored at `07:25:01Z`; the circuit state was
  observed back at `0` (closed) after recovery.
- Not measured: the precise instant the circuit opened, and the exact number of
  retries/fallback attempts inside the deadline. Those are not claimed.
- Note: 27.71s is longer than the 8s per-attempt timeout because retries and
  the total-deadline envelope are included. It is still bounded, but it is not
  a good interactive latency target; the client should set its own deadline.

## Drill 4: Feed failure isolation

Evidence: [`evidence/feed-failure.txt`](evidence/feed-failure.txt)

- Start: `2026-10-20T08:04:07Z` (local Python, existing Postgres).
- Two local RSS endpoints: one good, one returning HTTP 500.
- Good feed: `success`, one entry, skipped because it already existed.
- Bad feed: `failed`, HTTP 500 after two retry attempts; duration ~3.09s.
- The good feed completed even though the bad feed failed. The aggregated run
  would be `partial`, not `failed`.
- No article/index corruption observed.

## Drill 5: SSE client disconnect

Evidence: [`evidence/sse-disconnect.txt`](evidence/sse-disconnect.txt)

- First run at `07:25:52Z` exposed a real defect: the client left, but
  `devsec_sse_disconnects_total` stayed `0`. The stream had started and sent
  1,039 bytes; the active gauge returned to `0`. See the incident review:
  [`incidents/2026-10-20-sse-disconnect-metric.md`](incidents/2026-10-20-sse-disconnect-metric.md).
- Fix: count an incomplete generator in `finally`, covering both
  `request.is_disconnected()` and Starlette's generator-close path.
- Re-run at `07:31:06Z`: stream bytes `926`, disconnect counter `1 → 2`,
  active gauge `0.0`, result **PASS**.
- Evidence includes the partial stream prefix showing `event: sources` and
  token events, not just a health check.

## Drill 6: API restart under traffic

Evidence: [`evidence/api-restart.txt`](evidence/api-restart.txt)

- Start: `2026-10-20T08:03:17Z`.
- Liveness was polled every 0.5s for 35s while the API container restarted.
- Samples: **64**; **33** returned 200; **31** were connection failures
  (`000`) while the process was down/starting. This is expected for a hard
  container restart without a load balancer.
- Final liveness: `200`; final readiness: `200`; final `/ask`: `200`.
- The final `/ask` proves retrieval and generation resumed, not just the health
  endpoints.
- The earlier run at `08:02:20Z` produced a `000` on the first final liveness
  probe even though readiness and `/ask` recovered. The script was corrected to
  retry the final probe; the passing run is the one recorded.
- Model startup is tens of seconds. Compose health checks use a 180s start
  period for this reason.

## Drill 7: Alert fire and resolve

Evidence: [`evidence/alert-fire-resolve.txt`](evidence/alert-fire-resolve.txt)

- Start: `2026-10-20T07:35:30Z`.
- Postgres stopped at `07:35:31Z` and held down past the alert's `for: 2m`.
- `DevsecPostgresDown` reached **firing** at `07:38:02Z` (150s).
- Alertmanager showed `DevsecPostgresDown active`.
- Postgres restarted at `07:38:02Z`; readiness returned at `07:38:08Z`.
- After one scrape/evaluation cycle plus 30s, `DevsecPostgresDown` was gone from
  Prometheus. **Resolution is verified.**
- `DevsecDbConnectionFailures` remained firing after recovery because its
  5-minute increase window still contained the outage. It is expected to clear
  when the window moves past the failures; that is not a recovery failure.
- The SLO burn-rate alerts also fired during this window because the drill
  produced real 503 responses. Planned drills consume error budget under the
  documented policy. This is not a false positive.
- `Watchdog` remained active, proving the Alertmanager route continued to work
  while the database alert was active.

## Drill 8: Interrupted ingestion and freshness

Evidence: [`evidence/ingestion-restart.txt`](evidence/ingestion-restart.txt)

- A refresh worker was replaced while run `10` was still marked `running`.
- The next worker start logged `stale_ingestion_runs_closed runs=1` and changed
  run `10` to `interrupted` with
  `worker restarted before completion`.
- Run `12` then completed as `partial`: one feed succeeded, Hacker News failed
  with HTTP 419, and `devsec_ingestion_last_success_timestamp_seconds` was
  refreshed. The freshness alert cleared.
- The worker now exposes ingestion metrics on internal port `9101`; Prometheus
  scrapes job `devsec-refresh`. Before this change, the API process exported an
  unset `0` gauge and the freshness alert would have been misleading.

## Drill 9: Backup and restore

A custom-format logical dump was taken from the live Postgres container, then
restored into a new scratch database:

```bash
./scripts/backup/pg_backup.sh
./scripts/backup/verify_restore.sh data/backups/<file>.dump
```

Measured: 16,082,564-byte dump; restore **13s** on the final run (7s on an
earlier run); row counts matched for `articles` (522), `article_chunks` (3043),
`parent_docs` (1017), `semantic_cache` (24), `chat_messages` (164), ingestion
runs/feed runs, and `schema_migrations`; pgvector present. See
[`evidence/backup-restore.txt`](evidence/backup-restore.txt).

## Drill 10: Two-replica API routing

A second API process and nginx round-robin proxy were started with
`docker-compose.scale.yml`. Twenty-one health requests were distributed 14/7
across both upstreams; REST and SSE through the proxy returned 200. Memory was
1.05 GiB + 1.68 GiB for the API replicas. Per-process rate limits, Groq key
state, and circuit breakers remain a documented limitation. See
[`evidence/multi-replica.txt`](evidence/multi-replica.txt).

## Drill 11: Manual Postgres standby promotion

A streaming standby was initialized with `pg_basebackup`, caught up to
`sent_lsn = replay_lsn = 0/B000060`, then promoted with `pg_promote()` while
the primary and API were stopped. A new API pointed at the promoted node
returned readiness 200 and a real `/ask` returned 200, 3 sources, 432 chars,
model `qwen/qwen3.8-27b`, in 2s. This validates manual promotion, not automatic
failover or fencing. See [`evidence/db-failover.txt`](evidence/db-failover.txt).

## Alerting defects found and corrected during drills

1. **SSE disconnect metric did not count generator-close disconnects.** Fixed
   and re-tested (see Drill 5 and the incident review).
2. **Ingestion metrics lived only in the worker process.** Prometheus now
   scrapes `refresh:9101`; stale/success alert expressions filter
   `job="devsec-refresh"`.
3. **Readiness metric name collision.** The refresh process exports
   `devsec_ready=0` because it has no HTTP readiness endpoint. The alert and
   dashboard now use `devsec_ready{job="devsec-api"}`.
4. **SLO burn alerts could page on no/low traffic.** The availability ratio used
   a zero denominator guard (`0/1e-9 = 0`), which looked like 0% availability.
   The ratio now divides directly and the burn alerts require at least 20
   eligible requests in the 1h window. `promtool` validates the rules; a full
   idle-period live test was not run.
5. **Drill scripts produced false results.** The SSE script compared the gauge
   `0.0` against `"0"` and did not require a disconnect increment. The alert
   script matched raw JSON with `grep DevsecPostgresDown.*firing`, which could
   match a different alert's `firing` on the same JSON line. Both now use exact
   state checks.

## Not executed

- Automatic Postgres failover, quorum, fencing, or split-brain recovery.
- Real Groq provider outage or rate-limit storm. The timeout drill uses a
  deterministic mock; one real-provider success is recorded separately.
- A multi-host replica failure or node loss.
- Long-running soak with production query cardinality.
- A full idle-period validation of the SLO burn guard after the threshold change.

These are listed in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md); none are
claimed as verified.

## Lessons

- Liveness and readiness must be separate. The DB-down drill is the clearest
  proof: the process stayed alive while correctly refusing traffic.
- A bounded failure is not necessarily a fast failure. Groq timeout took 27.71s
  because the total retry envelope, not one attempt, bounded the request.
- Observability bugs can hide recovery behavior. The SSE counter and the
  ingestion scrape gap were both found by drills, not by unit tests.
- Alert validation must require **firing**, not `pending`, and must check
  Alertmanager as well as Prometheus.
- Worker scaling is not free: the 2-worker API used 1.82 GiB and did not improve
  throughput on the fixed CPU budget. Memory-heavy model services must be run
  sequentially on this host.
- Per-process metrics are easy to misattribute. Use job filters and separate
  scrape targets for API and worker metrics.
