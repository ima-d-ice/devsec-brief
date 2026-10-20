#!/usr/bin/env bash
set -euo pipefail

API="${API_URL:-http://127.0.0.1:8001}"
OUT="${OUT:-evidence/sse-disconnect.txt}"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT"; }

before=$(curl -sS "$API/metrics" | awk '/^devsec_sse_connections_active / {print $2; exit}')
before_disconnects=$(curl -sS "$API/metrics" | awk '/^devsec_sse_disconnects_total / {print $2; exit}')
log "drill=sse_disconnect api=$API active_before=${before:-unknown} disconnects_before=${before_disconnects:-unknown}"

# Slow the mock token stream so the client is still connected when it abandons.
MOCK_GROQ_STREAM_DELAY_MS=250 docker compose --profile loadtest up -d --force-recreate mock-groq >/dev/null
sleep 2

# Deliberately abandon the stream after 2 seconds.
QUERY="sse disconnect drill $(date +%s)"
set +e
curl -sS -N --max-time 2 -X POST "$API/ask/stream" \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"$QUERY\"}" >/tmp/devsec-sse-body 2>/dev/null
set -e

sleep 3
after=$(curl -sS "$API/metrics" | awk '/^devsec_sse_connections_active / {print $2; exit}')
disconnects=$(curl -sS "$API/metrics" | awk '/^devsec_sse_disconnects_total / {print $2; exit}')
log "active_after=${after:-unknown} disconnects_total=${disconnects:-unknown}"
log "stream_bytes=$(wc -c </tmp/devsec-sse-body | tr -d ' ')"

MOCK_GROQ_STREAM_DELAY_MS=5 docker compose --profile loadtest up -d --force-recreate mock-groq >/dev/null
log "mock_restored=ok"

if grep -q '^event:' /tmp/devsec-sse-body \
  && python3 -c "import sys; sys.exit(0 if float('${after:-1}') == 0 and float('${disconnects:-0}') > float('${before_disconnects:-0}') else 1)"; then
  log "RESULT=PASS (stream started, client left, disconnect counted, active gauge zero)"
else
  log "RESULT=FAIL (stream did not start, disconnect not counted, or active gauge did not return to zero)"
  exit 1
fi
