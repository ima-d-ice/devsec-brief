#!/usr/bin/env bash
set -euo pipefail

# Restore a custom-format dump into a NEW database. This script never restores
# over the live application database.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TARGET_DB="${1:-}"
DUMP_FILE="${2:-}"

if [ -z "$TARGET_DB" ] || [ -z "$DUMP_FILE" ]; then
  echo "usage: $0 <target_db> <dump_file>" >&2
  exit 2
fi

if ! [[ "$TARGET_DB" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "invalid target database name: $TARGET_DB" >&2
  exit 2
fi

if [ ! -s "$DUMP_FILE" ]; then
  echo "dump file missing or empty: $DUMP_FILE" >&2
  exit 2
fi

echo "restoring_dump=${DUMP_FILE}"
echo "target_database=${TARGET_DB}"

docker compose exec -T postgres sh -c \
  "psql -U \"\$POSTGRES_USER\" -d postgres -v ON_ERROR_STOP=1 \
     -c 'DROP DATABASE IF EXISTS \"${TARGET_DB}\" WITH (FORCE);' \
     -c 'CREATE DATABASE \"${TARGET_DB}\";'"

docker compose exec -T postgres sh -c \
  "pg_restore -U \"\$POSTGRES_USER\" -d \"${TARGET_DB}\" \
     --clean --if-exists --no-owner --no-acl" <"$DUMP_FILE"

echo "restore_target=${TARGET_DB}"
echo "RESULT=PASS"
