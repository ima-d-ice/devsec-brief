#!/usr/bin/env bash
set -euo pipefail

PROM="${PROM_URL:-http://127.0.0.1:9090}"
OUT="${OUT:-docs/evidence/alerts.txt}"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT"; }

log "drill=alerting prometheus=$PROM"
curl -sS "$PROM/-/ready" | tee -a "$OUT" >/dev/null
log "prometheus_ready=yes"

curl -sS "$PROM/api/v1/rules" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("\n".join(sorted({g["name"] for g in d["data"]["groups"]})))' \
  | tee -a "$OUT"

curl -sS "$PROM/api/v1/alerts" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(a["labels"].get("alertname"), a["state"]) for a in d["data"]["alerts"]]' \
  | tee -a "$OUT"

if curl -sS "$PROM/api/v1/alerts" | grep -q Watchdog; then
  log "RESULT=PASS (Watchdog alert is visible; rule evaluation is running)"
else
  log "RESULT=WARN (Watchdog not visible yet; check rule evaluation)"
fi
