"""Prometheus metrics for the API, retrieval pipeline, database and ingestion.

Cardinality rules:
* route labels are FastAPI route templates, never raw URLs;
* status labels are 2xx/3xx/4xx/5xx classes, never individual codes;
* query text, article URLs, session IDs and exception messages are never labels.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

HTTP_REQUESTS = Counter(
    "devsec_http_requests_total",
    "HTTP requests completed by method, route template and status class.",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "devsec_http_request_duration_seconds",
    "End-to-end HTTP request duration.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
HTTP_IN_FLIGHT = Gauge(
    "devsec_http_requests_in_flight",
    "HTTP requests currently being handled.",
)

SSE_ACTIVE = Gauge(
    "devsec_sse_connections_active",
    "SSE streams currently open.",
)
SSE_DISCONNECTS = Counter(
    "devsec_sse_disconnects_total",
    "SSE streams closed because the client disconnected.",
)
SSE_DURATION = Histogram(
    "devsec_sse_stream_duration_seconds",
    "SSE stream lifetime.",
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)

RETRIEVAL_STAGE = Histogram(
    "devsec_retrieval_stage_duration_seconds",
    "Latency of each retrieval stage.",
    ["stage"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
RETRIEVAL_FAILURES = Counter(
    "devsec_retrieval_failures_total",
    "Retrieval stage failures.",
    ["stage", "reason"],
)
CACHE_LOOKUPS = Counter(
    "devsec_cache_lookups_total",
    "Semantic cache lookups by result.",
    ["result"],
)
RERANK_CANDIDATES = Histogram(
    "devsec_rerank_candidates",
    "Number of candidates sent to the cross-encoder.",
    buckets=(1, 5, 10, 15, 20, 30, 50),
)

DB_POOL_IN_USE = Gauge(
    "devsec_db_pool_in_use",
    "Database connections currently checked out of the application pool.",
)
DB_POOL_WAIT = Histogram(
    "devsec_db_pool_wait_seconds",
    "Time spent waiting to acquire a database connection.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
DB_QUERY_DURATION = Histogram(
    "devsec_db_query_duration_seconds",
    "Application-observed database query duration.",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
DB_CONNECTION_FAILURES = Counter(
    "devsec_db_connection_failures_total",
    "Failures to acquire a database connection.",
)

INGESTION_RUNS = Counter(
    "devsec_ingestion_runs_total",
    "Ingestion runs by result.",
    ["result"],
)
INGESTION_DURATION = Histogram(
    "devsec_ingestion_duration_seconds",
    "Ingestion run duration.",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
)
INGESTION_ARTICLES = Counter(
    "devsec_ingestion_articles_total",
    "Articles processed by ingestion outcome.",
    ["result"],
)
INGESTION_FEED_FAILURES = Counter(
    "devsec_ingestion_feed_failures_total",
    "Feed fetch failures by feed name.",
    ["feed"],
)
INGESTION_LAST_SUCCESS = Gauge(
    "devsec_ingestion_last_success_timestamp_seconds",
    "Timestamp of the last productive ingestion run (success or partial).",
)
INGESTION_CONTENT_AGE = Gauge(
    "devsec_ingestion_content_age_seconds",
    "Age of the newest successfully ingested article.",
)

GROQ_REQUESTS = Counter(
    "devsec_groq_requests_total",
    "Groq requests by model and outcome.",
    ["model", "outcome"],
)
GROQ_DURATION = Histogram(
    "devsec_groq_request_duration_seconds",
    "Groq request duration by model.",
    ["model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 45, 60),
)
GROQ_RATE_LIMITED = Counter(
    "devsec_groq_rate_limited_total",
    "Groq 429 responses by key index.",
    ["key"],
)
GROQ_FALLBACKS = Counter(
    "devsec_groq_fallbacks_total",
    "Requests that fell back to a secondary model.",
    ["model"],
)
GROQ_CIRCUIT_STATE = Gauge(
    "devsec_groq_circuit_state",
    "Groq circuit state: 0=closed, 1=half-open, 2=open.",
)
READY = Gauge(
    "devsec_ready",
    "Readiness state: 1 ready, 0 not ready.",
)


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"


def status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def observe_stage(stage: str, started_at: float, now: float) -> None:
    RETRIEVAL_STAGE.labels(stage=stage).observe(max(0.0, now - started_at))


def record_retrieval_failure(stage: str, reason: str) -> None:
    # Keep the reason to a small known set at call sites.
    RETRIEVAL_FAILURES.labels(stage=stage, reason=reason).inc()
