# Security posture

## Implemented

- Container runs as UID/GID `10001` (non-root), drops all Linux capabilities
  and sets `no-new-privileges` for application services.
- Multi-stage image; build toolchain is not present in the runtime stage.
- `API_KEY` optional gate on `/ask` and `/ask/stream` using constant-time
  comparison.
- Per-client token-bucket rate limiting, disabled by default
  (`RATE_LIMIT_PER_MINUTE=0`).
- CORS allow-list from `CORS_ORIGINS`.
- Query length cap (2000 chars), injection-pattern rejection, `k` clamp 1–20.
- Prompt delimiters and untrusted-context treatment in the RAG prompt.
- Structured logs avoid request bodies, keys and query text.
- Secrets are supplied via `.env`/environment; `.env` is gitignored and
  `.dockerignore` excludes it from the image build context.
- The optional replication overlay does not define a password fallback; the
  standby initializes from a base backup over the private Docker network. Set
  credentials explicitly if adapting it for authenticated replication.
- No schema DDL at API boot; only the migration job can change the schema.
- Postgres is published on `127.0.0.1` only by default.
- CI includes Gitleaks and Trivy filesystem scanning.
- Gitleaks has a narrow allowlist for the placeholder-only `.env.example`;
  CI asserts that sensitive keys in that file remain empty.
- Trivy findings for `transformers` (CVE-2026-4372, CVE-2026-5241,
  CVE-2026-9856) are documented in `.trivyignore`: only local, trusted ONNX
  artifacts are loaded, `trust_remote_code` is not enabled, and the fixed
  transformers 5.x line conflicts with the pinned `optimum-onnx` requirement.
  Revisit when the ONNX export stack supports transformers 5.
- CD includes a Trivy critical-CVE gate before promotion.

## Not implemented / residual risk

| Risk | Status | Mitigation required |
|---|---|---|
| No TLS in Compose | open | Terminate TLS at a reverse proxy/load balancer |
| No user identity / RBAC | open | Add an identity provider and per-user authorization |
| API key is a shared secret | optional | Rotate keys; use a real auth gateway for public exposure |
| Rate limiter is in-process | open | Move to Redis/Postgres for multi-replica |
| Groq key state is in-process | open | Shared limiter store before scaling API replicas |
| No audit trail of who asked what | open | Add privacy-reviewed audit logging if required |
| Prompt injection is mitigated, not solved | open | Keep retrieved text untrusted; no tool execution from context |
| Postgres single primary | open | Managed HA/failover; logical restore is tested, automatic failover is not |
| No WAF / request-size limit | open | Edge proxy limits and bot protection |
| Frontend dependencies not covered by this review | open | Separate frontend security review |
| Image runs with a writable root filesystem | open | Add `read_only: true` after testing ONNX/tmp behavior |

## Secret handling

- Never commit `.env` or real keys.
- Use a secret manager for production; Compose env files are a lab mechanism.
- Rotate any key that appears in logs, screenshots, CI output or shell history.
- `GROQ_API_KEY` and numbered keys are read once at process start; rotation
  requires a restart.

## Reporting

Do not include secrets, full request bodies or user data in incident reports.
Use request IDs and metric snapshots.
