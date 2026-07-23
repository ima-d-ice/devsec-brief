import os
import re
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://devsec:devsec@localhost:5432/devsec")

pool = ConnectionPool(
    DATABASE_URL,
    min_size=2,
    max_size=10,
    timeout=30.0,
    kwargs={"autocommit": True},
)

def configure_connection(conn):
    with conn.cursor() as cur:
        cur.execute("SET hnsw.ef_search = 40;")
        cur.execute("SET statement_timeout = '5s';")

pool.configure = configure_connection

def get_conn():
    return pool.connection()

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
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                search_vector tsvector GENERATED ALWAYS AS (
                    to_tsvector('english',
                        coalesce(unaccent(title), '') || ' ' ||
                        coalesce(unaccent(coalesce(content, summary)), '')
                    )
                ) STORED
            );
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_search_vector ON articles USING GIN (search_vector);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_category      ON articles (category);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_url_trgm      ON articles USING GIN (url gin_trgm_ops);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_source        ON articles (source);")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS article_chunks (
                id            BIGSERIAL PRIMARY KEY,
                article_id    BIGINT REFERENCES articles(id) ON DELETE CASCADE,
                chunk_index   INTEGER NOT NULL,
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

            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_hnsw_cosine
                ON article_chunks USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_category ON article_chunks (category);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_url      ON article_chunks (url);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_text_trgm ON article_chunks USING GIN (chunk_text gin_trgm_ops);")

def save_article_if_new(**kwargs) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO articles (title, url, source, category, summary, content, published_at)
                VALUES (%(title)s, %(url)s, %(source)s, %(category)s, %(summary)s, %(content)s, %(published_at)s)
                ON CONFLICT (url) DO NOTHING
                RETURNING id;
            """, kwargs)
            result = cur.fetchone()
            conn.commit()
            return result is not None

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
        SELECT title, url, source, category, published_at, content, summary
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
            rows = cur.fetchall()
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            dict_rows = [dict(zip(col_names, row)) for row in rows]

    results = []
    for row in dict_rows:
        doc_text = (row["title"] or "") + "\n\n" + (row["content"] or row["summary"] or "")
        results.append({
            "document": doc_text.strip(),
            "metadata": {
                "title": row["title"],
                "url": row["url"],
                "source": row["source"],
                "category": row["category"],
                "published_at": row["published_at"],
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
            a.chunk_text,
            a.title,
            a.url,
            a.source,
            a.category,
            a.published_at
        FROM article_chunks a
        CROSS JOIN query_embs q
    """
    
    # Convert embeddings to pgvector string format so psycopg sends text[]
    # (double precision[][] cannot be cast to vector[] directly)
    q_emb_strs = ['[' + ','.join(str(x) for x in emb) + ']' for emb in q_embs]
    
    params = {"q_embs": q_emb_strs}
    if topic:
        sql += " WHERE a.category = %(topic)s"
        params["topic"] = topic
        
    sql += """
        GROUP BY a.id
        ORDER BY distance ASC
        LIMIT %(limit)s
    """
    params["limit"] = k
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            col_names = [desc[0] for desc in cur.description] if cur.description else []
            dict_rows = [dict(zip(col_names, row)) for row in rows]
            
    docs = []
    metas = []
    
    for row in dict_rows:
        docs.append(row["chunk_text"])
        metas.append({
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            "category": row["category"],
            "published_at": row["published_at"]
        })
        
    return {
        "documents": [docs],
        "metadatas": [metas]
    }