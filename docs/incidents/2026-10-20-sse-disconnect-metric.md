# Incident review: SSE disconnect metric undercount

**Date:** 2026-10-20
**Severity:** Low (observability only; no user-facing outage observed)
**Status:** Fixed and verified by a repeat drill
**Owner:** Service hardening work

## Summary

During the SSE client-disconnect drill, the API correctly stopped sending
tokens and returned the active-stream gauge to `0`, but
`devsec_sse_disconnects_total` did not increment. The disconnect path that
Starlette uses when the client closes the response generator was not covered by
the counter. This made the `DevsecSseDisconnects` alert blind to at least some
real disconnects.

No user data was lost and no request failed because of this defect. The impact
was observability: operators could under-detect disconnected streams and leak
risk.

## Timeline (UTC, from the drill evidence)

| Time | Event |
|---|---|
| 07:25:52 | First SSE disconnect drill starts; stream sends 1,039 bytes; active gauge returns to `0`; `disconnects_total=0`. Drill fails. |
| Between runs | `src/api.py` changed to count an incomplete generator in `finally`; the in-loop duplicate increment is removed. |
| 07:29:55 | Re-run after the code change: `disconnects_before=0`, `disconnects_total=1`, active `0`. The drill still reports FAIL because the shell compared the gauge string `0.0` to `"0"` and did not validate the counter delta. |
| 07:31:06 | Drill script corrected to parse numbers and require a counter increase plus a real stream event. Re-run: `disconnects_before=1`, `disconnects_total=2`, active `0.0`, stream 926 bytes. **PASS.** |

Evidence: [`../evidence/sse-disconnect.txt`](../evidence/sse-disconnect.txt)

## What happened

The stream generator had this shape:

```python
if await request.is_disconnected():
    disconnected = True
    obs.SSE_DISCONNECTS.inc()
    break
...
finally:
    stop.set()
    obs.SSE_ACTIVE.dec()
```

That works when the ASGI server lets the generator poll
`request.is_disconnected()`. It does not work when Starlette closes the async
generator directly: the loop may never reach the poll, so the counter is never
incremented. The active gauge still returned to `0` because `finally` always
ran.

The fix tracks whether the stream reached its final `done` event. If it did not,
`finally` increments the disconnect counter exactly once. This covers both the
poll-detected path and the generator-close path without double counting.

## Contributing factors

- The original test only checked the active gauge, which was already correct;
  it did not require the disconnect counter to move.
- The drill script compared `0.0` (Prometheus float text) to the shell string
  `"0"`, producing a false failure on a healthy recovery.
- The initial drill used a raw `grep` for an event prefix and did not assert
  that the counter increased.
- Unit tests exercise SSE shape and health contracts, but not real socket
  disconnection. This class of bug needed a live drill.

## What went well

- The drill exposed the gap before any production claim was made.
- The stream itself behaved correctly: it stopped and released the active
  gauge.
- The fix was small and localized to the event-stream lifecycle.
- Re-running the drill, rather than trusting the code change, caught the second
  (script-level) false result.

## What went poorly

- The first failure was initially interpreted as a stream-start problem; the
  partial body showed the stream had started, so the investigation moved to the
  counter.
- The script had two independent assertion bugs, which made the first two runs
  noisy.
- No automated regression test reproduces a real client socket close; the live
  drill remains the evidence.

## Action items

| Action | Owner | Status |
|---|---|---|
| Count incomplete SSE streams in `finally` | Service | Done |
| Require a real stream event and a disconnect-counter delta in the drill | SRE | Done |
| Parse Prometheus gauge values numerically in drill scripts | SRE | Done |
| Keep `DevsecSseDisconnects` alert (>10 in 10m) and dashboard panel | SRE | Done |
| Add a live SSE disconnect check to the release checklist | SRE | Done in this milestone's drill suite |
| Add an automated socket-level regression test if the test harness supports it | Service | Open |
