#!/usr/bin/env bash
set -euo pipefail

API="${API_URL:-http://127.0.0.1:8000}"
OUT="${OUT:-evidence/api-restart.txt}"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT"; }

log "drill=api_restart api=$API"
: > /tmp/devsec-restart-codes
(
  end=$((SECONDS + 35))
  while [ $SECONDS -lt $end ]; do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "$API/health/live" 2>/dev/null || true)
    [ -n "$code" ] || code=000
    printf '%s\n' "$code" >> /tmp/devsec-restart-codes
    sleep 0.5
  done
) &
LOOP_PID=$!
sleep 5

log "restarting api"
docker compose restart api >/dev/null
wait "$LOOP_PID" || true

TOTAL=$(wc -l </tmp/devsec-restart-codes | tr -d ' ')
OK=$(grep -c '^200$' /tmp/devsec-restart-codes || true)
BAD=$(grep -vc '^200$' /tmp/devsec-restart-codes || true)
log "samples=$TOTAL ok=$OK non_200=$BAD"
awk '{count[$1]++} END {for (c in count) print "status_" c "=" count[c]}' /tmp/devsec-restart-codes | tee -a "$OUT"

FINAL="000"
for _ in $(seq 1 10); do
  FINAL=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "$API/health/live" 2>/dev/null || true)
  [ "$FINAL" = "200" ] && break
  sleep 1
done
log "final_live_status=$FINAL"

READY="000"
for _ in $(seq 1 60); do
  READY=$(curl -sS -o /dev/null -w '%{http_code}' "$API/health/ready" 2>/dev/null || true)
  [ "$READY" = "200" ] && break
  sleep 1
done
log "final_ready_status=$READY"

ASK=$(curl -sS -o /tmp/devsec-restart-ask.json -w '%{http_code}' --max-time 60 \
  -X POST "$API/ask" -H 'Content-Type: application/json' \
  -d '{"query":"What is the XZ Utils backdoor and how is it remediated?","topic":"cybersec"}' \
  2>/dev/null || true)
log "final_ask_status=$ASK"
if [ "$FINAL" = "200" ] && [ "$READY" = "200" ] && [ "$ASK" = "200" ]; then
  log "RESULT=PASS (API restarted; liveness, readiness, and retrieval all recovered)"
else
  log "RESULT=FAIL (API did not fully recover)"
  exit 1
fi
