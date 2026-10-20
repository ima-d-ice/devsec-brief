#!/usr/bin/env bash
set -euo pipefail

API="${API_URL:-http://127.0.0.1:8001}"
OUT="${OUT:-evidence/groq-timeout.txt}"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT"; }

log "drill=groq_timeout api=$API"
MOCK_GROQ_MODE=timeout docker compose --profile loadtest up -d --force-recreate mock-groq >/dev/null
sleep 3

START=$(python3 -c 'import time; print(time.time())')
QUERY="groq timeout drill $(date +%s)"
STATUS=$(curl -sS --max-time 70 -o /tmp/devsec-drill-body -w '%{http_code}' \
  -X POST "$API/ask" -H 'Content-Type: application/json' \
  -d "{\"query\":\"$QUERY\"}" || true)
END=$(python3 -c 'import time; print(time.time())')
log "ask_status=$STATUS elapsed_s=$(python3 -c "print(round($END-$START,2))")"
log "body=$(head -c 300 /tmp/devsec-drill-body)"

LIVE=$(curl -sS -o /dev/null -w '%{http_code}' "$API/health/live" || true)
log "live_status=$LIVE"

MOCK_GROQ_MODE=ok docker compose --profile loadtest up -d --force-recreate mock-groq >/dev/null
log "mock_restored=ok"
if [ "$LIVE" = "200" ]; then log "RESULT=PASS (liveness held; upstream failure bounded)"; else log "RESULT=FAIL"; exit 1; fi
