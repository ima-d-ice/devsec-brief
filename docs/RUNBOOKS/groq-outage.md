# Runbook: Groq outage / rate limiting

Alerts: `DevsecGroqRateLimited`, `DevsecGroqCircuitOpen`.

## Symptoms
- `/ask` returns 503 with `Answer generation temporarily unavailable`.
- `devsec_groq_circuit_state` is `2` (open) or `1` (half-open).
- `devsec_groq_requests_total{outcome="rate_limit"}` rises.
- Logs show `groq_rate_limited`, `groq_retry`, or `stream_open_unavailable`.

## Triage
1. Inspect `/metrics`:
   - `sum by (outcome) (rate(devsec_groq_requests_total[5m]))`
   - `devsec_groq_circuit_state`
2. Check key health and remaining quota in the Groq console.
3. Check whether the failure is 429, timeout, 5xx or auth.
4. Confirm the API is still live: `/health/live` should be 200.

## Action
- Rate limit: allow per-key cooldowns and model fallback to work; reduce load
  or add capacity. Do not hammer the same key.
- Auth error: rotate the affected key and restart the API.
- Timeout/5xx: keep the circuit closed only if a healthy fallback exists;
  otherwise expect bounded 503s. The circuit will half-open automatically.
- Real outage: communicate degraded generation, keep retrieval/cached answers
  serving, and consider enabling a maintenance banner at the edge.

## Verification
- Circuit returns to `0`.
- A single `/ask` succeeds.
- No key value appears in logs or the incident report.
