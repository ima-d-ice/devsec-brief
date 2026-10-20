#!/usr/bin/env bash
set -euo pipefail

PGDATA="${PGDATA:-/var/lib/postgresql/data}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "basebackup_start"
  until pg_isready -h postgres -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"; do
    sleep 1
  done
  pg_basebackup -h postgres -U replicator -D "$PGDATA" -Fp -Xs -P -R
  touch "$PGDATA/standby.signal"
  chown -R postgres:postgres "$PGDATA"
  echo "basebackup_done"
fi

exec docker-entrypoint.sh postgres
