#!/usr/bin/env bash
set -euo pipefail

API="${API_URL:-http://127.0.0.1:8000}"
OUT="${OUT:-docs/evidence/db-down.txt}"
mkdir -p "$(dirname "$OUT")"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT"; }
code() { curl -sS -o /tmp/devsec-drill-body -w '%{http_code}' "$@" || true; }

: > "$OUT"
log "drill=db_down api=$API"

log "stopping postgres"
docker compose stop postgres >/dev/null
sleep 2

LIVE=$(code "$API/health/live")
READY=$(code "$API/health/ready")
QUERY="db down drill $(date +%s)"
ASK=$(code -X POST "$API/ask" -H 'Content-Type: application/json' -d "{\"query\":\"$QUERY\"}")
log "live_status=$LIVE ready_status=$READY ask_status=$ASK"
log "ask_body=$(head -c 300 /tmp/devsec-drill-body)"

log "starting postgres"
docker compose start postgres >/dev/null
for _ in $(seq 1 60); do
  if docker inspect -f '{{.State.Health.Status}}' devsec_postgres 2>/dev/null | grep -q healthy; then
    break
  fi
  sleep 1
done

for _ in $(seq 1 60); do
  RECOVERED=$(code "$API/health/ready")
  if [ "$RECOVERED" = "200" ]; then break; fi
  sleep 1
done
log "recovered_ready_status=$RECOVERED"

if [ "$LIVE" != "200" ] || [ "$RECOVERED" != "200" ]; then
  log "RESULT=FAIL"
  exit 1
fi
log "RESULT=PASS (liveness survived; readiness recovered)"
