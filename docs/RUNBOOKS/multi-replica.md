# Two-replica API runbook

The base stack runs one API process. The optional scale overlay adds a second
API process and an nginx round-robin proxy:

```text
client -> nginx :8080 -> api   :8000
                      -> api2  :8000
```

Both replicas use the same Postgres database. Semantic cache, chat history, and
ingestion state are shared through Postgres. Rate limits, Groq key cooldowns, and
circuit breakers are **per process**, so they are not global limits.

## Start

```bash
docker compose -f docker-compose.yml -f docker-compose.scale.yml \
  --profile scale up -d api2 nginx
curl -s http://127.0.0.1:8080/health/ready
```

On a small Docker VM, stop monitoring/refresh while both model processes are
loading; two API replicas plus refresh can exceed the VM's memory.

## Verify distribution

```bash
for i in $(seq 1 20); do curl -s -o /dev/null http://127.0.0.1:8080/health/live; done
docker logs devsec_nginx 2>&1 | grep upstream=
```

Expected: requests alternate between two backend addresses.

## Stop

```bash
docker compose -f docker-compose.yml -f docker-compose.scale.yml \
  --profile scale stop api2 nginx
```

The base API keeps running. Do not add a second API replica without accounting
for per-process auth/rate-limit state and memory.
