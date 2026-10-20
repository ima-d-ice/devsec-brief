#!/usr/bin/env bash
set -euo pipefail

# Dump the running Compose Postgres database into a timestamped custom-format
# archive. The dump stays on the host so it survives container/volume removal.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BACKUP_DIR="${BACKUP_DIR:-data/backups}"
mkdir -p "$BACKUP_DIR"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL="${BACKUP_DIR}/devsec-${TS}.dump"
TMP="$(mktemp "${BACKUP_DIR}/.devsec-XXXXXX")"
trap 'rm -f "$TMP"' EXIT

echo "backing_up_database=devsec"
echo "backup_dir=${BACKUP_DIR}"

docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-acl' \
  >"$TMP"

if [ ! -s "$TMP" ]; then
  echo "backup_failed=empty_archive" >&2
  exit 1
fi

mv "$TMP" "$FINAL"
trap - EXIT

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$FINAL" >"${FINAL}.sha256"
else
  shasum -a 256 "$FINAL" >"${FINAL}.sha256"
fi

echo "backup_file=${FINAL}"
echo "backup_bytes=$(wc -c <"$FINAL" | tr -d ' ')"
echo "backup_sha256=$(cut -d' ' -f1 "${FINAL}.sha256")"
echo "RESULT=PASS"
