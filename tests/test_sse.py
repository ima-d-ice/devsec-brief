"""SSE event-order contract: sources -> token -> metrics -> done."""

from fastapi.testclient import TestClient

import src.api as api
from src.api import app


def test_sse_cached_stream_event_order(monkeypatch):
    cached = {
        "answer": "A cached grounded answer.",
        "sources": [{"title": "Example", "url": "https://example.test/a"}],
        "model_used": "test-model",
        "cache_time_ms": 1.2,
        "exact": True,
    }
    monkeypatch.setattr(
        api, "check_cache_for_query", lambda query, topic=None: (cached, [])
    )
    with TestClient(app) as client:
        with client.stream(
            "POST", "/ask/stream", json={"query": "What is CVE-2024-3094?"}
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert body.index("event: sources") < body.index("event: token")
    assert body.index("event: token") < body.index("event: metrics")
    assert body.index("event: metrics") < body.index("event: done")
    assert "A cached grounded answer." in body


def test_sse_rejects_empty_query():
    with TestClient(app) as client:
        response = client.post("/ask/stream", json={"query": ""})
    assert response.status_code == 422
