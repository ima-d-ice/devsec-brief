# Backup and restore runbook

The database is the only stateful application store. ONNX models and the
application image are reproducible from git/build context.

## What is covered

`pg_dump` custom-format archives include the schema, data, indexes, and the
`vector` extension declaration. The dump is written to `data/backups/` on the
host, so it survives `docker compose down` and named-volume removal.

This is a **manual/scheduled script**, not continuous WAL archiving. The
recovery point objective is the age of the newest successful dump.

## Take a backup

```bash
./scripts/backup/pg_backup.sh
```

Outputs:

```text
data/backups/devsec-<UTC timestamp>.dump
data/backups/devsec-<UTC timestamp>.dump.sha256
backup_bytes=<size>
RESULT=PASS
```

A backup is not complete until the dump is non-empty and its SHA-256 file is
present. Copy dumps off-host before relying on them for disaster recovery.

## Restore into a scratch database

Never restore over `devsec` during an incident. Restore to a new database first:

```bash
./scripts/backup/pg_restore.sh devsec_restore_check data/backups/<file>.dump
```

The script drops/recreates only the named scratch database.

## Validate a restore

```bash
./scripts/backup/verify_restore.sh data/backups/<file>.dump
```

This dumps if no file is supplied, restores into `devsec_restore_check`, compares
row counts for all application tables, checks that `pgvector` is present, and
reports restore elapsed time. It exits non-zero on a mismatch.

## Promote a restored database (manual recovery)

If the primary is lost and there is no standby:

1. Stop API and refresh so they cannot write to the failed database.
2. Start a replacement Postgres with an empty volume.
3. Restore the newest dump into the application database.
4. Point `DATABASE_URL` at the replacement and start `migrate`, then API/refresh.
5. Verify `/health/ready`, `/ask`, and ingestion freshness.

This is **restore-based recovery**, not automatic high availability. A
streaming standby with promotion is not part of the base Compose stack.

## Drill evidence

Run the drill and store the output under `docs/evidence/`:

```bash
./scripts/backup/verify_restore.sh | tee docs/evidence/backup-restore.txt
```

The measured RTO starts at restore time and ends when the restored database
passes count/extension validation. It does **not** include the time to provision
a host or copy a large dump off-site.
