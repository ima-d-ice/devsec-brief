# Runbook: ingestion stale or failed

Alerts: `DevsecIngestionStale`, `DevsecIngestionFailed`,
`DevsecIngestionNoSuccessMetric`.

## Symptoms
- `time() - devsec_ingestion_last_success_timestamp_seconds > 8h`.
- `devsec_ingestion_runs_total{result="failed"}` increases.
- `devsec_ingestion_feed_failures_total` rises for one feed.
- Answers cite old articles.

## Triage
1. `docker compose ps refresh`
2. `docker compose logs --tail=300 refresh`
3. Query recent runs:
   ```sql
   SELECT id, started_at, finished_at, status, articles_inserted,
          feeds_failed, error_summary
   FROM ingestion_runs ORDER BY started_at DESC LIMIT 10;
   ```
4. Query feed failures:
   ```sql
   SELECT run_id, feed, status, error_message
   FROM ingestion_feed_runs ORDER BY id DESC LIMIT 20;
   ```
5. Confirm the advisory lock is not held by a dead session:
   ```sql
   SELECT * FROM pg_locks WHERE locktype = 'advisory';
   ```

## Action
- One feed failing: other feeds should continue; fix or remove the feed.
- Refresh container down: `docker compose restart refresh`.
- Stuck lock: investigate the holding session before terminating it.
- Manual one-shot: `docker compose run --rm refresh python -m src.refresh`.
- Verify the next run is `success` or `partial`, and freshness decreases.

## Verification
- `ingestion_runs` has a new successful row.
- `devsec_ingestion_last_success_timestamp_seconds` advances.
- A newly published test article is retrievable.
