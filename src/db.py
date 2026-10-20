import functools
import json
import re
import threading
import time
from contextlib import contextmanager
from typing import Iterable

from psycopg_pool import ConnectionPool, PoolTimeout

from src.obs import (
    DB_CONNECTION_FAILURES,
    DB_POOL_IN_USE,
    DB_POOL_WAIT,
    DB_QUERY_DURATION,
)
from src.settings import settings

DATABASE_URL = settings.database_url

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def configure_connection(conn):
    with conn.cursor() as cur:
        cur.execute("SET hnsw.ef_search = 40;")
        cur.execute("SET statement_timeout = '5s';")


def timed_db(operation: str):
    """Record application-observed query latency without unbounded labels."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                DB_QUERY_DURATION.labels(operation=operation).observe(
                    max(0.0, time.perf_counter() - started)
                )

        return wrapper

    return decorator


def get_pool() -> ConnectionPool:
    """Return the process-wide pool without connecting at import time."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    DATABASE_URL,
                    min_size=0,
                    max_size=10,
                    timeout=5.0,
                    kwargs={"autocommit": True},
                    configure=configure_connection,
                    open=False,
                )
    return _pool


def open_pool(wait: bool = True, timeout: float = 10.0) -> ConnectionPool:
    pool = get_pool()
    if pool.closed:
        pool.open(wait=wait, timeout=timeout)
    return pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def get_conn(timeout: float | None = None):
    """Acquire a pooled connection and expose acquisition/usage metrics."""
    pool = get_pool()
    if pool.closed:
        open_pool(timeout=5.0)
    started = time.perf_counter()
    try:
        with pool.connection(timeout=timeout) as conn:
            DB_POOL_WAIT.observe(max(0.0, time.perf_counter() - started))
            DB_POOL_IN_USE.inc()
            try:
                yield conn
            finally:
                DB_POOL_IN_USE.dec()
    except PoolTimeout:
        DB_CONNECTION_FAILURES.inc()
        raise


def check_db(timeout: float | None = None) -> bool:
    """Cheap readiness probe. Never used on the liveness path."""
    try:
        with get_conn(timeout=timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return True
    except Exception:
        return False


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def rows_to_dicts(cur) -> list[dict]:
    """Convert cursor results to a list of dicts using column names."""
    col_names = [desc[0] for desc in cur.description] if cur.description else []
    return [dict(zip(col_names, row)) for row in cur.fetchall()]

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")

            # unaccent() is STABLE, but GENERATED columns require IMMUTABLE
            # functions. This wrapper makes fresh installs work; behavior identical.
            cur.execute("""
            CREATE OR REPLACE FUNCTION immutable_unaccent(text)
            RETURNS text AS $$
                SELECT unaccent($1);
            $$ LANGUAGE sql IMMUTABLE;
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id           BIGSERIAL PRIMARY KEY,
                title        TEXT,
                url          TEXT UNIQUE,
                source       TEXT,
                category     TEXT,
                summary      TEXT,
                content      TEXT,
                published_at TEXT,
                content_hash TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW(),
                search_vector tsvector GENERATED ALWAYS AS (
                    to_tsvector('english',
                        coalesce(immutable_unaccent(title), '') || ' ' ||
                        coalesce(immutable_unaccent(coalesce(content, summary)), '')
                    )
                ) STORED
            );
            """)
            cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS content_hash TEXT;")
            cur.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_search_vector ON articles USING GIN (search_vector);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_category      ON articles (category);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_url_trgm      ON articles USING GIN (url gin_trgm_ops);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_source        ON articles (source);")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS article_chunks (
                id            BIGSERIAL PRIMARY KEY,
                article_id    BIGINT REFERENCES articles(id) ON DELETE CASCADE,
                chunk_index   INTEGER NOT NULL,
                parent_index  INTEGER NOT NULL DEFAULT 0,
                chunk_text    TEXT NOT NULL,
                title         TEXT,
                url           TEXT,
                source        TEXT,
                category      TEXT,
                published_at  TEXT,
                embedding     vector(1024) NOT NULL,
                created_at    TIMESTAMPTZ DEFAULT NOW()
            );
            """)
            cur.execute("ALTER TABLE article_chunks ADD COLUMN IF NOT EXISTS parent_index INTEGER NOT NULL DEFAULT 0;")

            # Parent docs (big) for big-to-small retrieval: children embed, parents feed LLM
            cur.execute("""
            CREATE TABLE IF NOT EXISTS parent_docs (
                id            BIGSERIAL PRIMARY KEY,
                article_id    BIGINT REFERENCES articles(id) ON DELETE CASCADE,
                parent_index  INTEGER NOT NULL,
                parent_text   TEXT NOT NULL,
                title         TEXT,
                url           TEXT,
                source        TEXT,
                category      TEXT,
                published_at  TEXT,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (article_id, parent_index)
            );
            """)

            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_hnsw_cosine
                ON article_chunks USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_category ON article_chunks (category);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_url      ON article_chunks (url);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_text_trgm ON article_chunks USING GIN (chunk_text gin_trgm_ops);")

            # Persistent chat history across sessions
            cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id          BIGSERIAL PRIMARY KEY,
                session_id  UUID NOT NULL,
                role        VARCHAR(20) NOT NULL,
                content     TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id, created_at);")

            # Semantic Query Cache with HNSW index
            cur.execute("""
            CREATE TABLE IF NOT EXISTS semantic_cache (
                id              BIGSERIAL PRIMARY KEY,
                query_text      TEXT NOT NULL,
                query_norm      TEXT,
                query_embedding vector(1024) NOT NULL,
                answer          TEXT NOT NULL,
                sources         JSONB NOT NULL,
                model_used      TEXT NOT NULL,
                topic           TEXT,
                quality         TEXT NOT NULL DEFAULT 'ok',
                embedding_model TEXT NOT NULL DEFAULT 'bge-m3',
                hit_count       INT DEFAULT 1,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW(),
                expires_at      TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days'
            );
            """)
            cur.execute("ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS query_norm TEXT;")
            cur.execute("ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS topic TEXT;")
            cur.execute("ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS quality TEXT NOT NULL DEFAULT 'ok';")
            cur.execute("ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT 'bge-m3';")
            cur.execute("ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days';")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_semantic_cache_norm ON semantic_cache (query_norm);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_semantic_cache_topic ON semantic_cache (topic);")
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_semantic_cache_embedding
                ON semantic_cache USING hnsw (query_embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_semantic_cache_expiry ON semantic_cache (expires_at);")

            # Ingestion observability: distinguish "scheduler is alive" from
            # "ingestion actually succeeded and content is fresh".
            cur.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                id                BIGSERIAL PRIMARY KEY,
                started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at       TIMESTAMPTZ,
                status            TEXT NOT NULL DEFAULT 'running',
                articles_inserted INTEGER NOT NULL DEFAULT 0,
                articles_updated  INTEGER NOT NULL DEFAULT 0,
                articles_skipped  INTEGER NOT NULL DEFAULT 0,
                feeds_total       INTEGER NOT NULL DEFAULT 0,
                feeds_failed      INTEGER NOT NULL DEFAULT 0,
                duration_ms       DOUBLE PRECISION,
                error_summary     TEXT
            );
            """)
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started
                ON ingestion_runs (started_at DESC);
            """)
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status
                ON ingestion_runs (status, started_at DESC);
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_feed_runs (
                id            BIGSERIAL PRIMARY KEY,
                run_id        BIGINT REFERENCES ingestion_runs(id) ON DELETE CASCADE,
                feed          TEXT NOT NULL,
                status        TEXT NOT NULL,
                inserted      INTEGER NOT NULL DEFAULT 0,
                updated       INTEGER NOT NULL DEFAULT 0,
                skipped       INTEGER NOT NULL DEFAULT 0,
                duration_ms   DOUBLE PRECISION,
                error_message TEXT,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ingestion_feed_runs_run
                ON ingestion_feed_runs (run_id);
            """)


@timed_db("interrupt_stale_ingestion_runs")
def interrupt_stale_ingestion_runs(older_than_minutes: int = 30) -> int:
    """Close runs abandoned by a killed worker.

    A hard crash cannot execute the normal finish path. On the next process
    start, mark old ``running`` rows as interrupted so monitoring does not
    mistake them for an active ingestion cycle.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_runs
                SET status = 'interrupted',
                    finished_at = COALESCE(finished_at, NOW()),
                    error_summary = COALESCE(error_summary, 'worker restarted before completion')
                WHERE status = 'running'
                  AND started_at < NOW() - make_interval(mins => %s);
                """,
                (older_than_minutes,),
            )
            return cur.rowcount


@timed_db("start_ingestion_run")
def start_ingestion_run(feeds_total: int = 0) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_runs (feeds_total) VALUES (%s) RETURNING id;",
                (feeds_total,),
            )
            return int(cur.fetchone()[0])


@timed_db("finish_ingestion_run")
def finish_ingestion_run(
    run_id: int,
    status: str,
    *,
    inserted: int = 0,
    updated: int = 0,
    skipped: int = 0,
    feeds_failed: int = 0,
    duration_ms: float | None = None,
    error_summary: str | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_runs
                SET finished_at = NOW(), status = %s, articles_inserted = %s,
                    articles_updated = %s, articles_skipped = %s,
                    feeds_failed = %s, duration_ms = %s, error_summary = %s
                WHERE id = %s;
                """,
                (
                    status,
                    inserted,
                    updated,
                    skipped,
                    feeds_failed,
                    duration_ms,
                    (error_summary or "")[:1000] or None,
                    run_id,
                ),
            )


@timed_db("record_ingestion_feed")
def record_ingestion_feed(
    run_id: int,
    feed: str,
    status: str,
    *,
    inserted: int = 0,
    updated: int = 0,
    skipped: int = 0,
    duration_ms: float | None = None,
    error_message: str | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_feed_runs
                    (run_id, feed, status, inserted, updated, skipped, duration_ms, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    run_id,
                    feed,
                    status,
                    inserted,
                    updated,
                    skipped,
                    duration_ms,
                    (error_message or "")[:1000] or None,
                ),
            )


def latest_successful_ingestion() -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, finished_at, articles_inserted, articles_updated,
                       articles_skipped, duration_ms
                FROM ingestion_runs
                WHERE status IN ('success', 'partial')
                ORDER BY finished_at DESC NULLS LAST
                LIMIT 1;
                """
            )
            rows = rows_to_dicts(cur)
            return rows[0] if rows else None


def latest_content_created_at():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(created_at) FROM articles;")
            row = cur.fetchone()
            return row[0] if row else None


@timed_db("save_chat_message")
def save_chat_message(session_id: str, role: str, content: str):
    """Persist a single chat turn in PostgreSQL."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s);",
                (session_id, role, content)
            )

@timed_db("get_chat_history")
def get_chat_history(session_id: str, limit: int = 6) -> list[dict]:
    """Fetch the most recent turns for session in chronological order."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT role, content FROM (
                    SELECT role, content, created_at FROM chat_messages
                    WHERE session_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                ) sub ORDER BY created_at ASC;
            """, (session_id, limit))
            return rows_to_dicts(cur)

@timed_db("check_exact_cache")
def check_exact_cache(query_text: str, topic: str | None = None) -> dict | None:
    """Zero-embed exact match on normalized query text (fast path, 0 LLM tokens)."""
    qnorm = normalize_query(query_text)
    with get_conn() as conn:
        with conn.cursor() as cur:
            if topic:
                cur.execute("""
                    SELECT id, answer, sources, model_used
                    FROM semantic_cache
                    WHERE query_norm = %s AND topic IS NOT DISTINCT FROM %s
                      AND quality = 'ok' AND expires_at > NOW()
                    ORDER BY updated_at DESC LIMIT 1;
                """, (qnorm, topic))
            else:
                cur.execute("""
                    SELECT id, answer, sources, model_used
                    FROM semantic_cache
                    WHERE query_norm = %s
                      AND quality = 'ok' AND expires_at > NOW()
                    ORDER BY updated_at DESC LIMIT 1;
                """, (qnorm,))
            rows = rows_to_dicts(cur)
            if rows:
                match = rows[0]
                cur.execute("UPDATE semantic_cache SET hit_count = hit_count + 1, updated_at = NOW() WHERE id = %s;", (match["id"],))
                return {
                    "answer": match["answer"],
                    "sources": match["sources"],
                    "model_used": match["model_used"],
                    "distance": 0.0,
                    "exact": True,
                }
    return None


@timed_db("check_semantic_cache")
def check_semantic_cache(query_emb: list[float], max_distance: float = 0.08, topic: str | None = None) -> dict | None:
    """Checks semantic cache for near-duplicate queries (<0.08 cosine distance = >0.92 similarity)."""
    emb_str = '[' + ','.join(str(x) for x in query_emb) + ']'
    with get_conn() as conn:
        with conn.cursor() as cur:
            if topic:
                cur.execute("""
                    SELECT id, answer, sources, model_used, (query_embedding <=> %s::vector(1024)) AS distance
                    FROM semantic_cache
                    WHERE (query_embedding <=> %s::vector(1024)) < %s
                      AND topic IS NOT DISTINCT FROM %s
                      AND quality = 'ok' AND expires_at > NOW()
                    ORDER BY distance ASC
                    LIMIT 1;
                """, (emb_str, emb_str, max_distance, topic))
            else:
                cur.execute("""
                    SELECT id, answer, sources, model_used, (query_embedding <=> %s::vector(1024)) AS distance
                    FROM semantic_cache
                    WHERE (query_embedding <=> %s::vector(1024)) < %s
                      AND quality = 'ok' AND expires_at > NOW()
                    ORDER BY distance ASC
                    LIMIT 1;
                """, (emb_str, emb_str, max_distance))
            rows = rows_to_dicts(cur)
            if rows:
                match = rows[0]
                cur.execute("UPDATE semantic_cache SET hit_count = hit_count + 1, updated_at = NOW() WHERE id = %s;", (match["id"],))
                return {
                    "answer": match["answer"],
                    "sources": match["sources"],
                    "model_used": match["model_used"],
                    "distance": match["distance"],
                    "exact": False,
                }
    return None


@timed_db("save_semantic_cache")
def save_semantic_cache(query_text: str, query_emb: list[float], answer: str, sources: list[dict], model_used: str, topic: str | None = None, quality: str = "ok", ttl_days: int = 30):
    """Save an answered query to the semantic cache (skips low-quality/empty answers)."""
    if not answer or len(answer.strip()) < 50:
        return
    if "not enough info" in answer.lower() and quality == "ok":
        quality = "empty"
        ttl_days = 1  # short TTL for negative cache
    emb_str = '[' + ','.join(str(x) for x in query_emb) + ']'
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO semantic_cache (query_text, query_norm, query_embedding, answer, sources, model_used, topic, quality, expires_at)
                VALUES (%s, %s, %s::vector(1024), %s, %s::jsonb, %s, %s, %s, NOW() + (%s || ' days')::interval);
            """, (query_text, normalize_query(query_text), emb_str, answer, json.dumps(sources), model_used, topic, quality, str(ttl_days)))
            # Cap table: keep hottest 20k rows
            cur.execute("""
                DELETE FROM semantic_cache WHERE id IN (
                    SELECT id FROM semantic_cache ORDER BY hit_count DESC, updated_at DESC OFFSET 20000
                );
            """)

def content_hash_for(title: str | None, content: str | None, summary: str | None) -> str:
    import hashlib
    base = f"{title or ''}\n{content or ''}\n{summary or ''}"
    return hashlib.md5(base.encode("utf-8", errors="ignore")).hexdigest()


def save_article_if_new(**kwargs) -> bool:
    """Legacy compat: insert-only. Prefer upsert_article."""
    _, changed = upsert_article(**kwargs)
    return changed == "inserted"


@timed_db("upsert_article")
def upsert_article(**kwargs) -> tuple[int | None, str]:
    """Insert or update article by URL. Returns (id, changed=inserted|updated|unchanged)."""
    import hashlib
    kwargs = dict(kwargs)
    kwargs["content_hash"] = content_hash_for(kwargs.get("title"), kwargs.get("content"), kwargs.get("summary"))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, content_hash FROM articles WHERE url = %(url)s;", {"url": kwargs.get("url")})
            row = cur.fetchone()
            if row is None:
                cur.execute("""
                    INSERT INTO articles (title, url, source, category, summary, content, published_at, content_hash, updated_at)
                    VALUES (%(title)s, %(url)s, %(source)s, %(category)s, %(summary)s, %(content)s, %(published_at)s, %(content_hash)s, NOW())
                    RETURNING id;
                """, kwargs)
                new_id = cur.fetchone()[0]
                return new_id, "inserted"
            existing_id, existing_hash = row[0], row[1]
            if existing_hash == kwargs["content_hash"]:
                return existing_id, "unchanged"
            cur.execute("""
                UPDATE articles SET title=%(title)s, source=%(source)s, category=%(category)s,
                    summary=%(summary)s, content=%(content)s, published_at=%(published_at)s,
                    content_hash=%(content_hash)s, updated_at=NOW()
                WHERE id=%(id)s;
            """, {**kwargs, "id": existing_id})
            return existing_id, "updated"


@timed_db("delete_chunks_for_article")
def delete_chunks_for_article(article_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM article_chunks WHERE article_id = %s;", (article_id,))
            cur.execute("DELETE FROM parent_docs WHERE article_id = %s;", (article_id,))


@timed_db("save_parent_docs")
def save_parent_docs(article_id: int, parents: list[dict]):
    if not parents:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO parent_docs (article_id, parent_index, parent_text, title, url, source, category, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (article_id, parent_index) DO UPDATE SET parent_text = EXCLUDED.parent_text;
            """, [
                (article_id, p["parent_index"], p["parent_text"], p.get("title"), p.get("url"),
                 p.get("source"), p.get("category"), p.get("published_at"))
                for p in parents
            ])


@timed_db("get_parent_text")
def get_parent_text(article_id: int, parent_index: int, max_chars: int = 1500) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT parent_text FROM parent_docs WHERE article_id = %s AND parent_index = %s;",
                        (article_id, parent_index))
            row = cur.fetchone()
            if row and row[0]:
                return row[0][:max_chars]
    return None


@timed_db("get_parent_texts")
def get_parent_texts(
    items: Iterable[tuple[int, int]], max_chars: int = 1500
) -> dict[tuple[int, int], str]:
    """Fetch many parent documents in one query (avoids N+1 lookups).

    ``items`` is an iterable of ``(article_id, parent_index)`` pairs.
    """
    pairs = list(dict.fromkeys(items))
    if not pairs:
        return {}
    article_ids = [int(item[0]) for item in pairs]
    parent_indexes = [int(item[1]) for item in pairs]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT article_id, parent_index, left(parent_text, %s)
                FROM parent_docs
                WHERE (article_id, parent_index) IN (
                    SELECT * FROM unnest(%s::bigint[], %s::int[])
                );
                """,
                (max_chars, article_ids, parent_indexes),
            )
            return {
                (int(row[0]), int(row[1])): row[2]
                for row in cur.fetchall()
                if row[2]
            }

@timed_db("search_keyword")
def search_keyword(query: str, limit: int = 20, topic: str | None = None) -> list[dict]:
    cve_pattern = re.compile(r'\bCVE-\d{4}-\d{4,}\b', re.IGNORECASE)
    cve_matches = cve_pattern.findall(query)
    
    remaining_query = cve_pattern.sub(' ', query)
    
    sanitized = re.sub(r'[^\w\s-]', ' ', remaining_query).lower()
    sanitized = sanitized.replace('-', ' ')
    
    stop_words = {'the', 'a', 'an', 'is', 'are', 'how', 'what', 'which', 'to', 'in', 'of', 'for', 'has', 'have', 'and', 'by', 'with'}
    words = [w for w in sanitized.split() if w not in stop_words and len(w) > 1]
    
    terms = []
    for cve in cve_matches:
        terms.append(f"'{cve}'")
    for word in words:
        terms.append(f"'{word}':*")
    
    if not terms:
        return []

    match_query = " & ".join(terms)
    
    sql = """
        SELECT id AS article_id, title, url, source, category, published_at, content, summary
        FROM articles
        WHERE search_vector @@ to_tsquery('english', %(match_query)s)
    """
    params = {"match_query": match_query}

    if topic:
        sql += " AND category = %(topic)s"
        params["topic"] = topic

    sql += " ORDER BY ts_rank(search_vector, to_tsquery('english', %(match_query)s)) DESC LIMIT %(limit)s"
    params["limit"] = limit

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            dict_rows = rows_to_dicts(cur)

    results = []
    for row in dict_rows:
        doc_text = (row["title"] or "") + "\n\n" + (row["content"] or row["summary"] or "")
        results.append({
            "document": doc_text.strip()[:1500],
            "metadata": {
                "title": row["title"],
                "url": row["url"],
                "source": row["source"],
                "category": row["category"],
                "published_at": row["published_at"],
                "article_id": row.get("article_id"),
                "parent_index": 0,
            }
        })
    return results

@timed_db("search_semantic")
def search_semantic(q_embs: list[list[float]], k: int, topic: str | None):
    sql = """
        WITH query_embs AS (
            SELECT unnest(%(q_embs)s::vector(1024)[]) AS q_emb
        )
        SELECT 
            MIN(a.embedding <=> q.q_emb) AS distance,
            a.article_id,
            a.parent_index,
            a.chunk_text,
            a.title,
            a.url,
            a.source,
            a.category,
            a.published_at
        FROM article_chunks a
        CROSS JOIN query_embs q
    """
    
    q_emb_strs = ['[' + ','.join(str(x) for x in emb) + ']' for emb in q_embs]
    
    params = {"q_embs": q_emb_strs}
    if topic:
        sql += " WHERE a.category = %(topic)s"
        params["topic"] = topic
        
    sql += """
        GROUP BY a.id, a.article_id, a.parent_index, a.chunk_text, a.title, a.url, a.source, a.category, a.published_at
        ORDER BY distance ASC
        LIMIT %(limit)s
    """
    params["limit"] = k
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            dict_rows = rows_to_dicts(cur)
            
    docs = []
    metas = []
    
    for row in dict_rows:
        docs.append(row["chunk_text"])
        metas.append({
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "category": row["category"],
            "published_at": row["published_at"],
            "article_id": row.get("article_id"),
            "parent_index": row.get("parent_index", 0),
        })
        
    return {
        "documents": [docs],
        "metadatas": [metas]
    }