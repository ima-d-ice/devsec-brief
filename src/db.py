import os
import re
import json
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://devsec:devsec@localhost:5432/devsec")


def configure_connection(conn):
    with conn.cursor() as cur:
        cur.execute("SET hnsw.ef_search = 40;")
        cur.execute("SET statement_timeout = '5s';")


pool = ConnectionPool(
    DATABASE_URL,
    min_size=2,
    max_size=10,
    timeout=30.0,
    kwargs={"autocommit": True},
    configure=configure_connection,
)


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def get_conn():
    return pool.connection()

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
                        coalesce(unaccent(title), '') || ' ' ||
                        coalesce(unaccent(coalesce(content, summary)), '')
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

def save_chat_message(session_id: str, role: str, content: str):
    """Persist a single chat turn in PostgreSQL."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s);",
                (session_id, role, content)
            )

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


def delete_chunks_for_article(article_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM article_chunks WHERE article_id = %s;", (article_id,))
            cur.execute("DELETE FROM parent_docs WHERE article_id = %s;", (article_id,))


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


def get_parent_text(article_id: int, parent_index: int, max_chars: int = 1500) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT parent_text FROM parent_docs WHERE article_id = %s AND parent_index = %s;",
                        (article_id, parent_index))
            row = cur.fetchone()
            if row and row[0]:
                return row[0][:max_chars]
    return None

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