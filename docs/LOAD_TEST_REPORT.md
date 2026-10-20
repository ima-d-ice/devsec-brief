# Load test report

**Status: measured on 2026-10-20. These are single-host, mock-upstream numbers,
not a real-Groq capacity benchmark and not an SLO-compliance claim.**

Every number below comes from the raw k6 output in `docs/evidence/` and the
service metrics captured immediately after each run. No number is estimated.

## Goal

Measure the service under controlled upstream latency for:

- REST `/ask` with the semantic cache bypassed (cold retrieval + generation)
- REST `/ask` with the production cache path enabled
- SSE `/ask/stream`
- error rate and resource pressure

The mock Groq service returns deterministic answers and streaming tokens. This
isolates the service's own CPU, database, and connection behavior from Groq
network variance and quota limits.

## Environment

| Item | Value |
|---|---|
| Date | 2026-10-20, approximately 07:38–07:54 UTC |
| Host | Apple Silicon (`arm64`), macOS, Docker Desktop |
| Docker resources | 8 vCPU, 4,108,632,064 bytes RAM (~3.83 GiB) |
| Compose limits | API 6 CPU / 3 GiB; refresh 4 CPU / 3 GiB; Postgres 2 CPU / 1 GiB |
| API workers | 1 (default), ONNX intra-op threads = 4 |
| Upstream | `mock-groq`, `MOCK_GROQ_MODE=ok` |
| Dataset at test time | 54 articles / 1,126 chunks / 280 parents |
| Dataset composition | 24 deterministic load articles seeded by `scripts/seed_loadtest.py`, plus existing ingested articles |
| Retrieval | bge-m3 INT8 ONNX embedding + mMARCO INT8 ONNX cross-encoder rerank, CPU |
| k6 | `grafana/k6:0.54.0` |
| App image | `devsec-brief:local`. The load runs used the image built before the final SSE-disconnect metric fix; that run's image ID was not recorded. The final rebuilt image is `sha256:ac107920ad3bfc0362494a19d7a90cb3c9eb0bac9329439c20df100bc3d34cc9`. |

The 24 seeded articles are synthetic. They are useful for deterministic
retrieval, not for judging content quality or production query distribution.

## Commands

```bash
# Cache-off cold path (api-mock CACHE_ENABLED=false)
docker compose --profile loadtest up -d postgres migrate mock-groq seed api-mock
docker compose --profile loadtest run --rm k6 run /scripts/smoke.js
docker compose --profile loadtest run --rm -e DURATION=60s k6 run /scripts/rest.js
docker compose --profile loadtest run --rm -e VUS=5 -e DURATION=60s k6 run /scripts/sse.js

# Worker-scaling comparison (2 workers, 2 ONNX threads each)
LOADTEST_WORKERS=2 ONNX_INTRA_OP_THREADS=2 \
  docker compose --profile loadtest up -d --force-recreate api-mock

# Production cache path (1 worker, ONNX threads=4, CACHE_ENABLED=true)
LOADTEST_CACHE_ENABLED=true docker compose --profile loadtest up -d --force-recreate api-mock
docker compose --profile loadtest run --rm -e DURATION=60s k6 run /scripts/rest.js
```

The REST scenario ramps from 0 to 5 VUs over 10s, holds 10 VUs for 60s, then
ramps down over 10s. The reported `http_reqs` therefore include the ramp
periods. The SSE scenario holds 5 VUs for 60s.

## Results

### Smoke

Raw output: [`evidence/k6-smoke.txt`](evidence/k6-smoke.txt)

| Metric | Value |
|---|---:|
| HTTP requests | 12 |
| Iterations | 3 |
| Checks | 21 / 21 passed |
| Failed request rate | 0.00% |
| Overall p95 | 10.48s |
| `/ask` p95 (n=6) | 17.53s |
| `/ask/stream` p95 (n=6) | 3.14s |
| SSE sources/done checks | passed |

The smoke run intentionally includes cold retrieval. The `/ask` p95 is high
because the first requests pay the full ONNX load/retrieval cost; all responses
were still 2xx.

### REST ramp, cache bypassed (worst case)

Raw output: [`evidence/k6-rest-60s.txt`](evidence/k6-rest-60s.txt)

| Metric | Value |
|---|---:|
| Max VUs | 10 |
| Hold duration | 60s (plus 10s up / 10s down) |
| Requests | 76 |
| Throughput | 0.939 req/s |
| Failed requests | 0 |
| Checks | 152 / 152 passed |
| Average latency | 5.91s |
| Median latency | 3.85s |
| p90 | 13.83s |
| p95 | 15.67s |
| Max | 24.29s |

### REST ramp, 2 workers / 2 ONNX threads

Raw output: [`evidence/k6-rest-60s-2workers.txt`](evidence/k6-rest-60s-2workers.txt)

| Metric | Value |
|---|---:|
| Max VUs | 10 |
| Requests | 76 |
| Throughput | 0.929 req/s |
| Failed requests | 0 |
| p95 | 14.93s |
| Max | 16.45s |
| API memory | 1.82 GiB / 3 GiB |

Doubling the worker count did **not** improve throughput (0.939 → 0.929 req/s,
within run-to-run noise) and only marginally changed p95. The extra process
almost doubled memory. This is consistent with CPU-bound ONNX inference: two
workers × two intra-op threads is still four inference threads on the same
CPU budget.

### REST ramp, production cache path

Raw output: [`evidence/k6-rest-60s-cache.txt`](evidence/k6-rest-60s-cache.txt)

| Metric | Value |
|---|---:|
| Max VUs | 10 |
| Requests | 408 |
| Throughput | 5.079 req/s |
| Failed requests | 0 |
| Checks | 816 / 816 passed |
| Average latency | 216.67ms |
| Median latency | 9.82ms |
| p90 | 16.72ms |
| p95 | 44.45ms |
| Max | 15.58s |

Cache counters immediately after the run:

| Result | Count |
|---|---:|
| exact hit | 396 |
| semantic hit | 1 |
| miss | 11 |
| total lookups | 408 |

That is a 97.3% hit rate on the fixed ten-query load set. The 11 misses are the
cold-path requests; the max latency is the cold-request tail. This run shows the
benefit of the cache, not the cost of an arbitrary production query mix.

### SSE, 5 VUs

Raw output: [`evidence/k6-sse-60s.txt`](evidence/k6-sse-60s.txt)

| Metric | Value |
|---|---:|
| VUs | 5 |
| Duration | 60s |
| Streams | 62 |
| Throughput | 1.005 streams/s |
| Failed requests | 0 |
| Checks | 186 / 186 passed |
| Average stream duration | 4.43s |
| Median | 3.19s |
| p90 | 9.04s |
| p95 | 13.81s |
| Max | 18.04s |
| Active streams after test | 0 |

All streams contained `event: sources` and `event: done`.

## Bottleneck analysis

Stage counters were read from the API process after the cold runs. Across the
144 cold retrieval requests (smoke + REST + SSE):

| Stage | Average per cold request |
|---|---:|
| Query embedding | ~1.4s |
| Parallel DB search | small fraction of total |
| RRF merge | small fraction of total |
| Cross-encoder rerank | ~3.0s |
| Parent lookup / assembly | small fraction of total |
| Total retrieval | ~4.6s |

The dominant cost is CPU ONNX inference: embedding plus reranking account for
roughly 4.4s of the ~4.6s retrieval path. Database search is not the bottleneck;
the Postgres pool and exporter metrics stayed low during the runs.

At 0.939 req/s × 4.62s retrieval, the process is consuming roughly four CPU
cores' worth of inference work. The service was configured with four ONNX
intra-op threads, so the inference pipeline is saturated. The 2-worker run
confirms this: adding a second process does not add CPU capacity.

## Optimization and re-run

**Optimization: keep the semantic cache enabled on the production API.** It was
already the production default, and the load-test profile explicitly bypasses it
to expose the worst case. The re-run above measures the difference:

- 408 vs 76 requests in the same scenario (**5.4× throughput**)
- p95 44.45ms vs 15.67s (**~352× lower**)
- 97.3% cache hit rate on the fixed query set
- zero failed requests in both modes

This is a real, measured improvement for repeated or popular queries. It does
not make cold retrieval faster. The cold path remains CPU-bound at about
0.94 req/s on this host.

Do **not** respond to cold-path saturation by only increasing Uvicorn workers.
The 2-worker experiment did not improve throughput on the same CPU budget. If
cold capacity must increase, the options are:

1. add CPU capacity and scale API replicas across it;
2. reduce the reranker candidate count or context truncation **only after**
   re-running retrieval quality evaluation;
3. use a faster/quantized reranker, again with quality evaluation.

None of those retrieval-quality changes were made in this milestone.

## Limitations

- The upstream is a deterministic mock, not Groq. Real Groq latency, rate
  limits, key cooldowns, and model fallback are not represented.
- The dataset is small and synthetic; query mix and cache cardinality are not a
  production sample.
- Cache-on results depend on repeated queries. They are not a general
  throughput claim.
- Single-host Compose, one Postgres primary, one API process by default. There
  is no multi-replica or multi-node result.
- k6 does not measure answer quality. Retrieval logic was not changed, so no new
  RAG eval was run; the committed 139-question artifact remains the quality
  baseline.
- The cold-path p95 is far above the 6s latency SLO target. This is a measured
  capacity limitation on this host, not an SLO pass.
- Results are valid only for the recorded image, dataset, and Docker resources.

## Related evidence

- [`docs/FAILURE_INJECTION.md`](FAILURE_INJECTION.md) — fault drills on the same stack
- [`docs/METRICS_AND_ALERTS.md`](METRICS_AND_ALERTS.md) — metric definitions and alert validation
- [`docs/SLOS.md`](SLOS.md) — SLO definitions and honest status
