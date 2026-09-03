"""API integration tests — mocked RAG but real FastAPI stack; pg required for some tests."""
import pytest

pytestmark = pytest.mark.integration

def test_full_ask_flow_with_real_db_if_available():
    """If DB not available, still test via mocked RAG (unit-style but marked integration)."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from src.api import app

    mock_res = {
        "documents": [["Cybersecurity advisory about CVE-2024-1234"]],
        "metadatas": [[{"title":"Advisory","url":"http://cisa.gov/1","source":"CISA Cybersecurity Advisories","category":"cybersec","published_at":"2026-09-01"}]]
    }
    with patch("src.api.retrieve_super", return_value=mock_res), \
         patch("src.api.build_context", return_value="Advisory context"), \
         patch("src.rag.generate_answer_from_context", return_value="CVE-2024-1234 is a Linux kernel vuln."):
        with TestClient(app) as client:
            resp = client.post("/ask", json={"query": "What is CVE-2024-1234?", "k": 5})
            assert resp.status_code == 200
            assert "CVE-2024-1234" in resp.json()["answer"]
            assert len(resp.json()["sources"]) == 1

def test_stream_integration():
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from src.api import app
    mock_res = {"documents":[["doc"]],"metadatas":[[{"title":"T","url":"http://1","source":"s","category":"c","published_at":""}]]}
    with patch("src.api.retrieve_super", return_value=mock_res), \
         patch("src.api.build_context", return_value="ctx"), \
         patch("src.api.stream_answer_from_context", return_value=iter(["token1 ","token2"])):
        with TestClient(app) as client:
            resp = client.post("/ask/stream", json={"query":"test","k":5})
            assert resp.status_code == 200
            body = resp.text
            assert body.count("event: token") == 2
            assert "event: done" in body
