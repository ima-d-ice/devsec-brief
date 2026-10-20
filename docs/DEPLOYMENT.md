# Deployment and rollback

## Prerequisites

- Docker Engine + Compose v2.24+ (for optional `env_file` support)
- 8 GB RAM recommended for the API + Postgres + monitoring stack
- A Groq API key (or use the `loadtest` profile with `mock-groq`)
- No GPU required

## First deployment

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, Groq keys, optional API_KEY, Grafana password
docker compose up -d --build
```

The startup gate is:

```text
postgres healthy -> migrate exits 0 -> api + refresh start
```

`migrate` is idempotent. The API entrypoint no longer creates tables.

## Verify

```bash
curl -s http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready
curl -s http://127.0.0.1:8000/metrics | head
docker compose ps
```

Expected:

- `/health/live` returns 200 once the process is up.
- `/health/ready` returns 200 only when Postgres **and** models are ready.
- `docker compose ps` shows `postgres`, `api`, `refresh`, `prometheus`,
  `grafana`, `alertmanager`, `postgres-exporter` healthy/running.
- Prometheus target `devsec-api` is `UP`.

Grafana: `http://127.0.0.1:3001` (credentials from `.env`).
Prometheus: `http://127.0.0.1:9090`.
Alertmanager: `http://127.0.0.1:9093`.

## Migrations

```bash
docker compose run --rm migrate
# or
docker compose exec api python -m src.migrate
```

Rules:

- Never edit an applied migration file; add a new ordered SQL file.
- Back up Postgres before a schema-changing release.
- The runner records versions in `schema_migrations`.
- The baseline is `init_db()` because the pre-migration project had an
  idempotent schema block and no migration history. This is documented in
  `src/migrate.py`.

## Rollback

Application rollback:

1. Pin the previous image digest/tag in the deployment override.
2. `docker compose up -d api refresh` with the previous image.
3. Verify `/health/ready` and a smoke `/ask`.

Database rollback is **forward-only** by default: restore the pre-deploy backup
into a new database and repoint `DATABASE_URL`. Do not run destructive down
migrations against production data.

## Backup and restore

Use the scripts so the archive is timestamped, checksummed, and always restored
into a new database:

```bash
./scripts/backup/pg_backup.sh
./scripts/backup/verify_restore.sh data/backups/<file>.dump
```

See [`docs/RUNBOOKS/backup-restore.md`](RUNBOOKS/backup-restore.md). The restore
drill was executed: a 16,077,010-byte dump restored in 7 seconds, all application
table counts matched, and pgvector was present. This is logical backup/restore,
not continuous WAL archiving or PITR.

## Scaling and availability limits

- Default `UVICORN_WORKERS=1`; ONNX models are loaded per worker.
- Optional two-replica drill:
  `docker compose -f docker-compose.yml -f docker-compose.scale.yml --profile scale up -d api2 nginx`.
  Nginx round-robins on `:8080`; Postgres-backed cache/chat state is shared,
  but rate limits and Groq circuit state remain per process.
- Base service names are fixed, so arbitrary `docker compose --scale` is not
  supported; the overlay adds a second named API service.
- Postgres is a single primary. The optional replication overlay supports a
  manual standby promotion; there is no automatic failover, VIP, or fencing.
  See [`docs/RUNBOOKS/db-failover.md`](RUNBOOKS/db-failover.md).
- The refresh worker uses a Postgres advisory lock, so duplicate refresh
  containers are safe but do not increase throughput.
- TLS, WAF, request-size limits and authentication at the edge are deployment
  responsibilities. The optional `API_KEY` is not a substitute for a full
  identity layer.

## Resource limits

Compose sets explicit memory/CPU limits. If the API is OOM-killed, inspect
`docker compose logs api` and reduce `UVICORN_WORKERS` before raising limits;
each worker loads its own ONNX sessions.

## Rollout checklist

- [ ] `docker compose config -q`
- [ ] `docker compose up -d --build`
- [ ] `migrate` exit 0
- [ ] `/health/ready` 200
- [ ] Prometheus target UP
- [ ] Grafana panels populated
- [ ] `Watchdog` alert visible
- [ ] k6 smoke passes
- [ ] rollback image/backup recorded
