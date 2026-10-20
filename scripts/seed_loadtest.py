import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import time

from src.db import close_pool, upsert_article
from src.embed_index import sync_index

ARTICLES = [
    ("CVE-2024-3094: XZ Utils backdoor analysis", "A critical supply-chain backdoor was inserted into XZ Utils releases 5.6.0 and 5.6.1. The malicious build-to-host.m4 script modifies liblzma to intercept SSH authentication. Operators should downgrade to 5.4.6, rotate SSH keys, and search build logs for the affected tarballs."),
    ("CVE-2023-44487 HTTP/2 Rapid Reset", "A denial-of-service technique abuses HTTP/2 stream cancellation to exhaust server resources. Mitigations include patching reverse proxies, limiting concurrent streams, and enabling rate limiting at the edge."),
    ("Log4Shell remediation checklist", "CVE-2021-44228 allows JNDI lookup injection in Log4j 2. Remove JndiLookup, upgrade to 2.17.1 or later, and scan container images for nested vulnerable jars."),
    ("Kubernetes RBAC privilege escalation", "Over-permissive RoleBindings and cluster-admin bindings are common escalation paths. Audit who can create pods, escalate roles, or read secrets, and enforce least privilege."),
    ("Software supply chain security with SBOMs", "Generate SBOMs for every image, sign provenance with Sigstore, verify at admission, and continuously rescan deployed artifacts for new CVEs."),
    ("PostgreSQL connection pool exhaustion", "Pool exhaustion causes request queueing and 503s. Instrument checked-out connections, set bounded acquisition timeouts, and investigate slow queries before increasing pool size."),
    ("OWASP Top 10: broken access control", "Broken access control remains the top web risk. Enforce authorization server-side, deny by default, and test object-level access with automated cases."),
    ("TLS certificate rotation runbook", "Automate certificate issuance and rotation, alert before expiry, and test renewal in staging. Avoid manual rotation during incident response."),
    ("Detecting secrets in CI pipelines", "Run secret scanning on every push, block commits with high-entropy tokens, and rotate any exposed credential immediately. Do not rely on reviewers alone."),
    ("Incident response: database failover", "When the primary database is unavailable, verify the failure scope, fail over to a replica, validate read/write health, and communicate impact with a timestamped timeline."),
    ("Observability: RED and USE metrics", "Track request rate, errors, and duration for services; utilization, saturation, and errors for resources. Pair metrics with structured logs and traces."),
    ("SLO error budget policy", "Define SLIs from user-facing behavior, set a target, and agree on a policy for what happens when the error budget is exhausted. Freeze risky changes and prioritize reliability work."),
    ("Docker image hardening", "Use minimal base images, run as non-root, drop Linux capabilities, pin digests, and scan images in CI. Avoid embedding secrets in layers."),
    ("Nginx SSE proxy configuration", "Disable response buffering, set long read timeouts, and send periodic heartbeats so intermediaries do not close idle streams. Use HTTP/1.1 to the upstream."),
    ("Rate limiting design", "Choose a key (IP, API key, user), a token bucket or sliding window, and a clear 429 contract with Retry-After. In multi-replica systems, keep limiter state shared."),
    ("Circuit breaker tradeoffs", "A circuit breaker protects a failing dependency by failing fast. Tune failure thresholds and recovery windows, and expose state as a metric so operators can see open circuits."),
    ("Semantic cache invalidation", "Cache answers with source snapshots, a TTL, and a similarity threshold. Never cache low-quality or ungrounded answers, and invalidate when indexed content changes."),
    ("RAG retrieval evaluation", "Measure retrieval recall, answer faithfulness, and citation coverage on a fixed question set. Track changes when chunking, embeddings, or rerankers change."),
    ("Prompt injection defense", "Treat retrieved content as untrusted, isolate instructions from evidence, and reject suspicious control patterns. Never let retrieved text authorize tool use."),
    ("Backup and restore verification", "A backup is not a backup until a restore succeeds. Schedule restores, verify row counts and application queries, and record the recovery time."),
    ("Graceful shutdown for streaming APIs", "Stop accepting new connections, let in-flight requests finish within a deadline, close upstream streams, and release database pools before the orchestrator kills the process."),
    ("CVE triage with EPSS and KEV", "Prioritize vulnerabilities using exploit likelihood and known exploitation, not just CVSS. Patch internet-facing KEV entries first and document accepted risk."),
    ("Zero trust for internal APIs", "Authenticate and authorize service-to-service calls, use short-lived credentials, encrypt traffic, and avoid implicit trust based on network location."),
    ("Load testing SSE streams", "Measure time to first token, tokens per second, disconnect rate, and active connections. Use realistic think time and verify server resource limits."),
]


def main() -> int:
    started = time.perf_counter()
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    for index, (title, content) in enumerate(ARTICLES):
        _article_id, state = upsert_article(
            title=title,
            url=f"https://loadtest.local/articles/{index}",
            source="loadtest",
            category="cybersec" if index % 2 == 0 else "webdev",
            summary=content[:200],
            content=content,
            published_at="2026-10-01T00:00:00Z",
        )
        counts[state] = counts.get(state, 0) + 1
    try:
        index_result = sync_index()
        print(json.dumps({"articles": counts, "index": index_result, "seconds": round(time.perf_counter() - started, 2)}))
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
