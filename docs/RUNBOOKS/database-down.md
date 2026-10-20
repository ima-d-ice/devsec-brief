# Runbook: database down / pool exhausted

Alerts: `DevsecNotReady`, `DevsecDbPoolSaturated`,
`DevsecDbConnectionFailures`, `DevsecPostgresDown`.

## Symptoms
- `/health/ready` returns 503 with `"database": false`.
- `/ask` returns 503 with `Retry-After`.
- `devsec_db_pool_in_use` near 10 or `devsec_db_connection_failures_total`
  increasing.
- Postgres logs show connection or disk errors.

## Triage
1. `docker compose ps postgres`
2. `docker inspect -f '{{.State.Health.Status}}' devsec_postgres`
3. `docker compose logs --tail=200 postgres`
4. `docker compose exec postgres pg_isready -U devsec -d devsec`
5. Check disk: `docker system df`, host disk free space.
6. Check pool: query `/metrics` for `devsec_db_pool_in_use`,
   `devsec_db_pool_wait_seconds`, `devsec_db_query_duration_seconds`.

## Action
- Postgres stopped/crashed: `docker compose start postgres`; wait healthy;
  readiness should recover without restarting the API.
- Disk full: free space or expand volume; restart Postgres if it cannot write.
- Pool saturation: identify slow queries; do not blindly raise pool size.
  The API uses bounded acquisition and a 5s statement timeout by design.
- Data corruption: stop writes, restore the last verified backup into a new
  database, repoint `DATABASE_URL`, then verify.

## Verification
- `/health/ready` 200.
- `devsec_db_pool_in_use` returns to normal.
- One `/ask` succeeds and a retrieval-only request does not time out.

## Do not
- Do not delete the Postgres volume to "reset" production data.
- Do not run destructive schema changes during an outage.
