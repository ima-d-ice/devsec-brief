"""DB integration tests — need live Postgres (skipped otherwise).

Run: python -m pytest tests/ -q -m integration
CI runs unit only; this file is excluded there (no DB in CI).
"""
import time
import uuid

import pytest

from src.db import (
    get_conn,
    upsert_article,
    search_keyword,
    save_semantic_cache,
    check_exact_cache,
)

pytestmark = pytest.mark.integration

TOKEN = f"zzq{uuid.uuid4().hex[:10]}"
URL = f"https://example.test/{TOKEN}"
QUERY = f"{TOKEN} integration probe"


def _db_up():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def require_db():
    if not _db_up():
        pytest.skip("no live Postgres")


@pytest.fixture()
def cleanup():
    yield
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM articles WHERE url = %s;", (URL,))
            cur.execute("DELETE FROM semantic_cache WHERE query_norm LIKE %s;", (f"%{TOKEN}%",))


def test_upsert_lifecycle(cleanup):
    aid, state = upsert_article(
        title=f"{TOKEN} title", url=URL, source="test", category="cybersec",
        summary=f"{TOKEN} summary", content=f"{TOKEN} content", published_at="",
    )
    assert state == "inserted" and aid

    _, state2 = upsert_article(
        title=f"{TOKEN} title", url=URL, source="test", category="cybersec",
        summary=f"{TOKEN} summary", content=f"{TOKEN} content", published_at="",
    )
    assert state2 == "unchanged"

    _, state3 = upsert_article(
        title=f"{TOKEN} title", url=URL, source="test", category="cybersec",
        summary=f"{TOKEN} changed", content=f"{TOKEN} content", published_at="",
    )
    assert state3 == "updated"


def test_keyword_search_finds_article(cleanup):
    upsert_article(
        title=f"{TOKEN} title", url=URL, source="test", category="cybersec",
        summary=f"{TOKEN} summary", content=f"{TOKEN} content", published_at="",
    )
    time.sleep(0.2)
    hits = search_keyword(TOKEN, limit=5)
    assert any(h["metadata"]["url"] == URL for h in hits)


def test_exact_cache_roundtrip(cleanup):
    qemb = [0.0] * 1024
    save_semantic_cache(QUERY, qemb, "A" * 60, [], "test-model", topic="cybersec")
    hit = check_exact_cache(QUERY, topic="cybersec")
    assert hit is not None
    assert hit["answer"] == "A" * 60
    assert hit["exact"] is True
