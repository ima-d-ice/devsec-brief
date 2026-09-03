"""Pytest conftest — mocks heavy ONNX/DB/Groq to allow unit tests without infra."""
import os
from unittest.mock import MagicMock

# Ensure dummy Groq key for import
os.environ.setdefault("GROQ_API_KEY", "gsk_dummy_for_tests_1234567890")
os.environ.setdefault("LOG_JSON", "0")  # plain logs in tests for readability
os.environ.setdefault("DATABASE_URL", "postgresql://devsec:devsec@localhost:5432/devsec_test")

# Mock heavy libs BEFORE any src import that would trigger ONNX load
# 1) sentence_transformers mocks
mock_st = MagicMock()
mock_ce = MagicMock()
# Patch at sys.modules level so rag/embed_index get mocked class instead of real
# We do it after import by patching objects, but also ensure encode/predict work

# Import src modules after env setup; mock embed_model globally via fixtures
import pytest

@pytest.fixture(autouse=True)
def _mock_heavy_models(request, monkeypatch):
    """Auto-mock ONNX models for all tests unless explicitly overridden."""
    # Skip DB mock for integration tests - they manage their own container
    is_integration = request.node.get_closest_marker("integration") is not None
    # Patch embed_model and reranker_model in rag
    try:
        import src.rag as rag_mod
        # Create mock embed_model
        mock_embed = MagicMock()
        # encode returns 2D array of 1024-dim vectors (one per variant)
        def _fake_encode(texts, batch_size=None, **kw):
            import numpy as np
            n = len(texts) if isinstance(texts, list) else 1
            # Return np array shape (n, 1024)
            arr = np.random.rand(n, 1024).astype("float32")
            # Normalize to avoid zero
            return arr
        mock_embed.encode = _fake_encode
        monkeypatch.setattr(rag_mod, "embed_model", mock_embed, raising=False)

        mock_reranker = MagicMock()
        def _fake_predict(pairs, **kw):
            import numpy as np
            return np.array([0.9 - i*0.1 for i in range(len(pairs))])
        mock_reranker.predict = _fake_predict
        monkeypatch.setattr(rag_mod, "reranker_model", mock_reranker, raising=False)
    except Exception:
        pass

    try:
        import src.embed_index as ei_mod
        mock_ei_embed = MagicMock()
        mock_ei_embed.encode = _fake_encode  # reuse
        monkeypatch.setattr(ei_mod, "embed_model", mock_ei_embed, raising=False)
    except Exception:
        pass

    # Mock groq client
    try:
        import src.groq_client as gc_mod
        mock_groq = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "This is a mocked LLM answer for tests."
        mock_choice.delta.content = "token"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_groq.chat.completions.create.return_value = mock_resp
        monkeypatch.setattr(gc_mod, "groq_client", mock_groq, raising=False)
    except Exception:
        pass

    # Mock DB pool to avoid needing postgres for unit tests
    if not is_integration:
        try:
            import src.db as db_mod
            # Only mock if not marked integration (integration tests will override)
            mock_pool = MagicMock()
            # get_conn context manager mock
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_cur.description = []
            mock_cur.fetchall.return_value = []
            mock_cur.fetchone.return_value = None
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur
            mock_conn.cursor.return_value.__exit__.return_value = False
            mock_conn.__enter__.return_value = mock_conn
            mock_conn.__exit__.return_value = False
            mock_pool.connection.return_value = mock_conn
            # For unit tests, keep pool mocked; integration tests will use real testcontainers
            monkeypatch.setattr(db_mod, "pool", mock_pool, raising=False)
            monkeypatch.setattr(db_mod, "get_conn", lambda: mock_pool.connection(), raising=False)
        except Exception:
            pass

    yield


@pytest.fixture
def mock_groq_response():
    """Fixture to provide a mock Groq completion response."""
    mock_choice = MagicMock()
    mock_choice.message.content = "Mocked answer with citations."
    mock_choice.delta.content = " mocked token"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    return mock_resp


@pytest.fixture
def sample_articles():
    """Sample articles for entity extraction / RAG tests."""
    return [
        {"title": "CVE-2024-1234 in Linux Kernel", "summary": "LegacyHive vulnerability affects profsvc", "content": "Details about CVE-2024-1234"},
        {"title": "CISA Advisory AA24-123A", "summary": "Ransomware healthcare attack", "content": "CISA warns ..."},
    ]


@pytest.fixture
def client():
    """FastAPI TestClient with mocked dependencies."""
    from fastapi.testclient import TestClient
    from src.api import app
    with TestClient(app) as c:
        yield c
