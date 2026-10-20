# Load testing

All load tests run against `api-mock`, which points at the deterministic
`mock-groq` service. They never consume real Groq quota.

## Start the load-test stack

```bash
docker compose --profile loadtest up -d postgres migrate mock-groq seed api-mock
docker compose --profile loadtest ps
```

`seed` inserts 24 synthetic security articles and indexes them. Wait for it to
finish (exit 0) before running k6.

## Smoke

```bash
docker compose --profile loadtest run --rm k6 run /scripts/smoke.js
```

## REST ramp

```bash
docker compose --profile loadtest run --rm -e DURATION=60s k6 run /scripts/rest.js
```

## SSE

```bash
docker compose --profile loadtest run --rm -e VUS=5 -e DURATION=60s k6 run /scripts/sse.js
```

## Soak

```bash
docker compose --profile loadtest run --rm -e VUS=5 -e DURATION=10m k6 run /scripts/soak.js
```

## Cache and worker comparisons

The default `api-mock` profile bypasses the semantic cache so the test exercises
retrieval and generation. To measure the production cache path:

```bash
LOADTEST_CACHE_ENABLED=true docker compose --profile loadtest up -d --force-recreate api-mock
docker compose --profile loadtest run --rm -e DURATION=60s k6 run /scripts/rest.js
```

To compare worker counts, keep the total ONNX thread budget roughly constant:

```bash
LOADTEST_WORKERS=2 ONNX_INTRA_OP_THREADS=2 \
  docker compose --profile loadtest up -d --force-recreate api-mock
```

On the recorded 8-vCPU / 3.83 GiB host, two workers used 1.82 GiB and did not
improve throughput. See [`../docs/LOAD_TEST_REPORT.md`](../docs/LOAD_TEST_REPORT.md)
for the measured results and caveats. Stop `api-mock` before starting the real
API or seed job; concurrent model processes can OOM the Docker VM.

## Failure modes

Change `MOCK_GROQ_MODE` and restart `mock-groq`:

```bash
MOCK_GROQ_MODE=timeout docker compose --profile loadtest up -d --force-recreate mock-groq
MOCK_GROQ_MODE=429     docker compose --profile loadtest up -d --force-recreate mock-groq
MOCK_GROQ_MODE=500     docker compose --profile loadtest up -d --force-recreate mock-groq
MOCK_GROQ_MODE=flaky   docker compose --profile loadtest up -d --force-recreate mock-groq
```

Return to normal with `MOCK_GROQ_MODE=ok`.

## Notes

- `k6` uses the `BASE_URL` environment variable, defaulting to
  `http://api-mock:8000` in Compose.
- If `API_KEY` is set, k6 sends `X-API-Key`.
- Keep the load-test profile isolated from the real API service. It shares the
  database intentionally so results include realistic retrieval work.
- A load test is not a benchmark unless the dataset, model, hardware and
  duration are recorded. Record all four with the results.
