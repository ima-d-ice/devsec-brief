#!/usr/bin/env bash
set -euo pipefail

API="${API_URL:-http://127.0.0.1:8000}"
OUT="${OUT:-docs/evidence/db-slow.txt}"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT"; }

log "drill=db_slow holding ACCESS EXCLUSIVE lock on article_chunks for 15s"
docker compose exec -T postgres psql -U devsec -d devsec -v ON_ERROR_STOP=1 \
  -c "BEGIN; LOCK TABLE article_chunks IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(15); COMMIT;" \
  >/dev/null 2>&1 &
LOCK_PID=$!

sleep 1
START=$(python3 -c 'import time; print(time.time())')
QUERY="db slow drill $(date +%s)"
STATUS=$(curl -sS -o /tmp/devsec-drill-body -w '%{http_code}' \
  -X POST "$API/ask" -H 'Content-Type: application/json' \
  -d "{\"query\":\"$QUERY\"}" || true)
END=$(python3 -c 'import time; print(time.time())')
log "ask_status=$STATUS elapsed_s=$(python3 -c "print(round($END-$START,2))")"
log "body=$(head -c 300 /tmp/devsec-drill-body)"

wait "$LOCK_PID" || true
sleep 2
RECOVERED=$(curl -sS -o /dev/null -w '%{http_code}' "$API/health/ready" || true)
log "recovered_ready_status=$RECOVERED"
if [ "$RECOVERED" = "200" ]; then log "RESULT=PASS"; else log "RESULT=FAIL"; exit 1; fi
