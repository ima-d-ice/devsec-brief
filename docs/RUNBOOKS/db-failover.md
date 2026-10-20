# Database standby and manual failover runbook

The base Compose stack is **single-primary**. This overlay is a drill and a
manual recovery option, not automatic high availability:

```text
postgres (primary) -- streaming -- postgres-standby (read-only)
```

There is no failover controller, virtual IP, or automatic client redirect.
Promotion is an operator action and clients must be pointed at the new primary.

## Start the standby

```bash
./scripts/replication/setup-primary.sh
docker compose -f docker-compose.yml -f docker-compose.replication.yml \
  --profile replication up -d postgres-standby
```

Wait for `basebackup_done` and a healthy container, then confirm streaming:

```bash
docker compose exec -T postgres psql -U devsec -d devsec \
  -c "SELECT client_addr, state, sent_lsn, replay_lsn FROM pg_stat_replication;"
docker compose -f docker-compose.yml -f docker-compose.replication.yml \
  exec -T postgres-standby psql -U devsec -d devsec \
  -c "SELECT pg_is_in_recovery();"
```

Expected: one streaming row, `pg_is_in_recovery() = t`.

The setup adds a `trust` rule for `replication replicator` on the private Docker
network. Do not expose this overlay to an untrusted network.

## Promotion drill

1. Stop writers: `docker compose stop api refresh`.
2. Confirm the standby has replayed the latest LSN.
3. Promote:
   ```bash
   docker exec devsec_postgres_standby \
     pg_ctl promote -D /var/lib/postgresql/data
   ```
4. Wait for `pg_is_in_recovery() = f`.
5. Start a test API with `DATABASE_URL` pointing at `postgres-standby:5432`.
6. Verify `/health/ready`, `/ask`, and an ingestion run can write.
7. Record the promotion time and any lost transactions (RPO).

A raw promotion can lose transactions that had not reached the standby. For a
real recovery, capture the last replay LSN and the failed primary's WAL before
declaring the recovery point.

## Cleanup

After a drill, stop and remove the standby, restore the original API, and
restart the primary. Do not run the old primary and promoted standby as
independent writers: that is split-brain. If the old primary is reused, rebuild
it from a fresh base backup and reattach it as a standby.

## What this does not solve

- No automatic promotion or client failover.
- No quorum, fencing, or split-brain protection.
- No cross-host placement; both containers share one Docker host.
- No WAL archiving or point-in-time recovery. Use the dump/restore runbook for
  an off-host logical backup.
