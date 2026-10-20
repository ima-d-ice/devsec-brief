# Runbook: API down

Alert: `DevsecApiDown`, `DevsecNoMetrics`.

## Symptoms
- Prometheus target `devsec-api` is `DOWN`.
- `curl /health/live` fails or times out.
- Requests to `/ask` fail at the edge.

## Triage
1. `docker compose ps api`
2. `docker compose logs --tail=200 api`
3. `docker inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}}' devsec_api`
4. Check host resources: `docker stats --no-stream`.

## Common causes
- OOM kill from multiple uvicorn workers loading ONNX models.
- Port conflict on 8000.
- Entrypoint/import error after a deploy.
- Postgres outage causing readiness failure (liveness may still be up).

## Action
- If OOM: reduce `UVICORN_WORKERS`, raise memory limit, restart.
- If config/import error: roll back to the previous image tag; do not edit a
  running container.
- If the process is up but readiness is false: follow
  [database-down.md](database-down.md).
- Restart: `docker compose restart api`.
- Verify: `/health/live` 200, `/health/ready` 200, then one `/ask`.

## Escalation
If two restarts fail or the image cannot start, roll back and preserve logs.
Record request IDs, exit code, OOM flag and timestamps.
