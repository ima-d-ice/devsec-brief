#!/usr/bin/env bash
set -euo pipefail

# Prepare the running primary for the local standby drill. This is intentionally
# a drill-only trust rule on the private Docker network; do not expose this
# Postgres port to an untrusted network.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.replication.yml)

"${COMPOSE[@]}" exec -T postgres sh -c '
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'"'"'SQL'"'"'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '"'"'replicator'"'"') THEN
    CREATE ROLE replicator WITH REPLICATION LOGIN;
  END IF;
END
$$;
SQL
  grep -q "host replication replicator 0.0.0.0/0 trust" "$PGDATA/pg_hba.conf" || \
    echo "host replication replicator 0.0.0.0/0 trust" >>"$PGDATA/pg_hba.conf"
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT pg_reload_conf();"
'

echo "primary_replication_configured=yes"
echo "RESULT=PASS"
