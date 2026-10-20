# Baseline

Date: 2026-10-20
Branch: `sre/hardening` (from `upgrade/devsec-evaluation-and-quality`)
Repository: `/Users/imad/Desktop/devsec-brief`

## Environment

- Local Python: 3.14.6 (project targets Python 3.12; tests ran on 3.14)
- Docker Engine: 29.6.1
- Postgres: `pgvector/pgvector:pg16` via Compose
- No real Groq call was made during baseline tests
- Test venv: temporary, `--system-site-packages`, plus
  `prometheus-client`, `httpx`, `pyyaml`, `pytest-cov`, `ruff`

## Baseline suite

Command:

```bash
DATABASE_URL=postgresql://devsec:devsec@localhost:5432/devsec \
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/ -q -p no:cacheprovider
```

Result before hardening:

```text
14 passed, 2 warnings in 0.85s
```

Warnings:
- Unknown `integration` marker (registered later in `pytest.ini`)
- `psycopg_pool` default `open` deprecation

## Verified at baseline

- 6 sanitizer tests passed.
- 5 API validation tests passed.
- 3 Postgres integration tests passed.
- Schema initialization succeeded.
- A real lifecycle defect was confirmed: the import-time pool emitted
  `PythonFinalizationError: cannot join thread at interpreter shutdown`.

## Not verified at baseline

- No real Groq provider call.
- No Docker image build with the new runtime.
- No Compose monitoring stack.
- No load or failure testing.
- Frontend not exercised.

## Current suite

After the hardening changes, the full suite is **33 passed** (unit +
integration against local Postgres). See `TODO.md`.

## Current verification (2026-10-20)

The baseline gaps above have since been closed locally:

- Real `/ask` and `/ask/stream` returned 200 through the real Groq path.
- The non-root Docker image built and ran in Compose.
- Prometheus, Alertmanager, Grafana, and the Postgres exporter are running.
- k6 smoke/REST/SSE runs completed with zero failed requests; numbers are in
  `docs/LOAD_TEST_REPORT.md` and `docs/evidence/`.
- Failure drills passed for DB down/slow, Groq timeout, feed isolation, SSE
  disconnect, API restart, and `DevsecPostgresDown` fire/resolve.
- Both Grafana dashboards are provisioned and query the live Prometheus target.

Still not verified: backup/restore, multi-replica behavior, real-Groq capacity,
and a fresh-clone deployment on a clean host.
