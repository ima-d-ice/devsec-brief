"""Integration tests for DB — require postgres via testcontainers; skipped if docker unavailable."""
import pytest
import os

pytestmark = pytest.mark.integration

def _docker_available():
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False

# Skip all if docker not available (CI without docker service)
if not _docker_available():
    pytest.skip("Docker not available for integration tests", allow_module_level=True)

from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="module")
def pg_container():
    with PostgresContainer("pgvector/pgvector:pg16", username="devsec", password="devsec", dbname="devsec") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        # Wait for health
        os.environ["DATABASE_URL"] = url
        # Reinit pool with test URL
        import src.db as db_mod
        # Recreate pool
        from psycopg_pool import ConnectionPool
        # Close old pool if exists
        try:
            db_mod.pool.close()
        except Exception:
            pass
        def configure(conn):
            with conn.cursor() as cur:
                cur.execute("SET hnsw.ef_search = 40;")
                cur.execute("SET statement_timeout = '5s';")
        db_mod.pool = ConnectionPool(url, min_size=1, max_size=5, timeout=10, kwargs={"autocommit": True}, configure=configure)
        db_mod.DATABASE_URL = url
        # Init schema
        db_mod.init_db()
        yield url
        try:
            db_mod.pool.close()
        except Exception:
            pass
        # Restore original env
        os.environ.pop("DATABASE_URL", None)

@pytest.fixture
def db(pg_container):
    import src.db as db_mod
    # Clean tables before each test
    with db_mod.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE article_chunks, articles RESTART IDENTITY CASCADE;")
            conn.commit()
    yield db_mod

def test_init_db_creates_tables(db):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.articles');")
            assert cur.fetchone()[0] == "articles"
            cur.execute("SELECT to_regclass('public.article_chunks');")
            assert cur.fetchone()[0] == "article_chunks"
            cur.execute("SELECT extname FROM pg_extension WHERE extname='vector';")
            rows = cur.fetchall()
            assert any(r[0]=="vector" for r in rows)

def test_save_and_keyword_search(db):
    # Insert article
    assert db.save_article_if_new(title="CVE-2024-1234 exploit", url="http://a1", source="CISA Cybersecurity Advisories", category="cybersec", summary="exploit", content="Linux kernel vuln CVE-2024-1234", published_at="2026-09-01") is True
    # Duplicate should return False
    assert db.save_article_if_new(title="dup", url="http://a1", source="X", category="cybersec", summary="", content="", published_at="") is False
    # Insert another
    db.save_article_if_new(title="Web dev update React 19", url="http://a2", source="MDN Blog", category="webdev", summary="", content="React 19 release", published_at="2026-09-02")

    # Keyword search CVE exact
    res = db.search_keyword("CVE-2024-1234", limit=5)
    assert len(res) >= 1
    assert any("CVE-2024-1234" in r["document"] for r in res)

    # Keyword search webdev topic filter
    res_topic = db.search_keyword("React", limit=5, topic="cybersec")
    # Should be empty because React is webdev, filtered by cybersec
    assert len(res_topic) == 0
    res_topic2 = db.search_keyword("React", limit=5, topic="webdev")
    assert len(res_topic2) == 1

def test_semantic_search_requires_chunks(db):
    # Without chunks, semantic search returns empty
    res = db.search_semantic([[0.1]*1024], k=5, topic=None)
    assert res["documents"][0] == []
    # Insert chunk directly
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # need article id
            cur.execute("SELECT id FROM articles WHERE url='http://a1'")
            aid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO article_chunks (article_id, chunk_index, chunk_text, title, url, source, category, published_at, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (aid, 0, "chunk CVE vuln", "CVE-2024-1234 exploit", "http://a1", "CISA Cybersecurity Advisories", "cybersec", "2026-09-01", [0.11]*1024)
            )
            conn.commit()
    res2 = db.search_semantic([[0.11]*1024], k=2, topic=None)
    assert len(res2["documents"][0]) >= 1
    assert "chunk CVE" in res2["documents"][0][0]
