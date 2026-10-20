#!/usr/bin/env bash
set -euo pipefail

# End-to-end backup/restore validation: dump, restore into a scratch database,
# compare row counts and the pgvector extension, then leave the scratch DB in
# place for inspection.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

TARGET_DB="${RESTORE_DB:-devsec_restore_check}"
DUMP_FILE="${1:-}"
START="$(date +%s)"

if [ -z "$DUMP_FILE" ]; then
  echo "step=backup"
  DUMP_FILE="$(BACKUP_DIR=data/backups ./scripts/backup/pg_backup.sh | awk -F= '/^backup_file=/{print $2}')"
fi

echo "dump_file=${DUMP_FILE}"
echo "step=restore"
./scripts/backup/pg_restore.sh "$TARGET_DB" "$DUMP_FILE"

TABLES=(articles article_chunks parent_docs semantic_cache chat_messages ingestion_runs ingestion_feed_runs schema_migrations)
COUNT_SQL=""
for table in "${TABLES[@]}"; do
  if [ -n "$COUNT_SQL" ]; then COUNT_SQL+=" UNION ALL "; fi
  COUNT_SQL+="SELECT '${table}='||count(*) FROM ${table}"
done

source_counts="$(docker compose exec -T postgres sh -c \
  "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc \"${COUNT_SQL}\"")"
restored_counts="$(docker compose exec -T postgres sh -c \
  "psql -U \"\$POSTGRES_USER\" -d \"${TARGET_DB}\" -Atc \"${COUNT_SQL}\"")"
vector_ext="$(docker compose exec -T postgres sh -c \
  "psql -U \"\$POSTGRES_USER\" -d \"${TARGET_DB}\" -Atc \"SELECT extname FROM pg_extension WHERE extname='vector'\"")"

echo "source_counts:"
printf '%s\n' "$source_counts"
echo "restored_counts:"
printf '%s\n' "$restored_counts"
echo "restored_vector_extension=${vector_ext}"

if [ "$source_counts" != "$restored_counts" ]; then
  echo "RESULT=FAIL row_counts_differ" >&2
  exit 1
fi
if [ "$vector_ext" != "vector" ]; then
  echo "RESULT=FAIL pgvector_missing" >&2
  exit 1
fi

END="$(date +%s)"
echo "restore_elapsed_s=$((END - START))"
echo "target_database=${TARGET_DB}"
echo "RESULT=PASS"
