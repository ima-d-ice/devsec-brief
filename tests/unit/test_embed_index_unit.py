"""Unit tests for embed_index sync logic — mocks DB and embeddings."""
import pytest
from unittest.mock import MagicMock

def test_sync_index_no_docs(monkeypatch):
    import src.embed_index as ei
    # Mock get_conn to return empty articles
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_cur.description = [["id"], ["title"], ["url"], ["source"], ["category"], ["summary"], ["content"], ["published_at"]]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn
    monkeypatch.setattr(ei, "get_conn", lambda: mock_conn)
    # Ensure embed_model exists (patched by conftest)
    # Should not encode
    ei.sync_index()
    # No embeddings called, but should not error

def test_sync_index_truncates_and_inserts(monkeypatch):
    import src.embed_index as ei
    import numpy as np
    # Mock DB rows
    articles = [
        (1, "T1", "http://1", "Hacker News", "webdev", "sum1", "content1", "2026-09-01"),
        (2, "T2", "http://2", "CISA", "cybersec", "sum2", "content2", "2026-09-02"),
    ]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = articles
    mock_cur.description = [["id"], ["title"], ["url"], ["source"], ["category"], ["summary"], ["content"], ["published_at"]]
    # For executemany check
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn
    monkeypatch.setattr(ei, "get_conn", lambda: mock_conn)

    # Mock embeddings: encode returns 2D array (chunks x 1024)
    fake_emb = np.random.rand(4, 1024)
    mock_embed = MagicMock()
    mock_embed.encode.return_value = fake_emb
    monkeypatch.setattr(ei, "embed_model", mock_embed)

    # Mock splitter to return 2 chunks per article
    mock_splitter = MagicMock()
    mock_splitter.split_text.side_effect = lambda txt: [txt[:200], txt[200:400]]
    monkeypatch.setattr(ei, "text_splitter", mock_splitter)

    ei.sync_index()

    # Should have called TRUNCATE
    assert any("TRUNCATE" in str(c.args[0]) for c in mock_cur.execute.call_args_list)
    # Should have called encode with 4 texts
    assert mock_embed.encode.call_args[0][0] is not None
    assert len(mock_embed.encode.call_args[0][0]) == 4
    # Should have called executemany with 4 inserts
    # Find executemany calls
    # executemany is on a new connection context after encoding; we reused same mock_conn so check
    assert mock_cur.executemany.called
    inserted = mock_cur.executemany.call_args[0][1]
    assert len(inserted) == 4
    # Each insert has 9 fields last is embedding list 1024
    assert len(inserted[0]) == 9
    assert len(inserted[0][-1]) == 1024

def test_sync_index_limit_param(monkeypatch):
    import src.embed_index as ei
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_cur.description = [["id"], ["title"], ["url"], ["source"], ["category"], ["summary"], ["content"], ["published_at"]]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn
    monkeypatch.setattr(ei, "get_conn", lambda: mock_conn)

    ei.sync_index(limit=5)
    # Check that LIMIT param is used safely (not f-string injection)
    sql_calls = [c.args[0] for c in mock_cur.execute.call_args_list if "SELECT" in str(c.args[0])]
    assert any("LIMIT %(limit)s" in s for s in sql_calls)
    # Ensure param dict contains limit 5
    # Find the call with limit
    for c in mock_cur.execute.call_args_list:
        if "SELECT" in str(c.args[0]):
            # second arg is params dict or None
            if len(c.args) > 1 and c.args[1] and isinstance(c.args[1], dict):
                assert c.args[1].get("limit") == 5

def test_sync_index_requires_model(monkeypatch):
    import src.embed_index as ei
    monkeypatch.setattr(ei, "embed_model", None)
    mock_conn = MagicMock()
    monkeypatch.setattr(ei, "get_conn", lambda: mock_conn)
    with pytest.raises(RuntimeError, match="Embedding model not loaded"):
        ei.sync_index()
