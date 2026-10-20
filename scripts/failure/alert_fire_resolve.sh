#!/usr/bin/env bash
set -euo pipefail

PROM="${PROM_URL:-http://127.0.0.1:9090}"
AM="${AM_URL:-http://127.0.0.1:9093}"
OUT="${OUT:-docs/evidence/alert-fire-resolve.txt}"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT"; }

alerts() {
  curl -sS "$PROM/api/v1/alerts" \
    | python3 -c 'import json,sys; [print(a["labels"].get("alertname"), a["state"]) for a in json.load(sys.stdin)["data"]["alerts"]]' \
    | tee -a "$OUT"
}

alert_state() {
  curl -sS "$PROM/api/v1/alerts" \
    | python3 -c 'import json,sys; name=sys.argv[1]; print(next((a["state"] for a in json.load(sys.stdin)["data"]["alerts"] if a["labels"].get("alertname") == name), ""))' "$1"
}

log "drill=alert_fire_resolve prometheus=$PROM alertmanager=$AM"
docker compose stop postgres >/dev/null
log "postgres_stopped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# DevsecPostgresDown has for: 2m. Keep the dependency down past that window
# and require an actual firing state; pending is not evidence of paging.
for i in $(seq 1 24); do
  sleep 10
  if [ "$(alert_state DevsecPostgresDown)" = "firing" ]; then
    log "alert_firing_after=$((i * 10))s"
    break
  fi
done

if [ "$(alert_state DevsecPostgresDown)" != "firing" ]; then
  log "RESULT=FAIL (DevsecPostgresDown never reached firing while postgres was down)"
  docker compose start postgres >/dev/null || true
  exit 1
fi

log "--- firing evidence ---"
alerts
curl -sS "$AM/api/v2/alerts" \
  | python3 -c 'import json,sys; [print(a["labels"].get("alertname"), a["status"]["state"]) for a in json.load(sys.stdin)]' \
  | tee -a "$OUT"

docker compose start postgres >/dev/null
for _ in $(seq 1 60); do
  if docker inspect -f '{{.State.Health.Status}}' devsec_postgres 2>/dev/null | grep -q healthy; then break; fi
  sleep 1
done
for _ in $(seq 1 60); do
  if [ "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health/ready || true)" = "200" ]; then break; fi
  sleep 1
done
log "recovered_ready_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Allow one scrape + evaluation cycle for the alert to resolve.
sleep 30
log "--- recovery evidence ---"
alerts
curl -sS "$AM/api/v2/alerts" \
  | python3 -c 'import json,sys; [print(a["labels"].get("alertname"), a["status"]["state"]) for a in json.load(sys.stdin)]' \
  | tee -a "$OUT"

if [ -n "$(alert_state DevsecPostgresDown)" ]; then
  log "RESULT=FAIL (DevsecPostgresDown still present after recovery)"
  exit 1
fi
log "RESULT=PASS (DevsecPostgresDown fired and resolved; readiness recovered)"
