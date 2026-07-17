# src/db.py
import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "articles.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enforce foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    
    # 1. Create main table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            url TEXT UNIQUE,
            source TEXT,
            category TEXT,
            summary TEXT,
            content TEXT,
            published_at TEXT
        );
    """)

    # 2. Create FTS5 Virtual Table (content linked to articles table)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            title, content, content='articles', content_rowid='id'
        );
    """)

    # 3. Create triggers to keep FTS5 synced with main table
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
            INSERT INTO articles_fts(rowid, title, content)
            VALUES (new.id, new.title, COALESCE(new.content, new.summary, ''));
        END;
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
            INSERT INTO articles_fts(articles_fts, rowid, title, content)
            VALUES('delete', old.id, old.title, COALESCE(old.content, old.summary, ''));
        END;
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
            INSERT INTO articles_fts(articles_fts, rowid, title, content)
            VALUES('delete', old.id, old.title, COALESCE(old.content, old.summary, ''));
            INSERT INTO articles_fts(rowid, title, content)
            VALUES (new.id, new.title, COALESCE(new.content, new.summary, ''));
        END;
    """)

    # 4. Rebuild FTS index to ensure it is perfectly in sync with the articles table
    # This securely deletes the old index and rebuilds it directly from the articles table
    # in milliseconds. We do this on init because FTS external content tables don't automatically backfill.
    conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild');")

    conn.commit()
    conn.close()
    print("DB initialized at:", DB_PATH)

def save_article_if_new(**kwargs) -> bool:
    """Insert an article. Returns True if it was newly inserted, False if it was a duplicate (same URL)."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO articles (title, url, source, category, summary, content, published_at)
            VALUES (:title, :url, :source, :category, :summary, :content, :published_at)
        """, kwargs)
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # duplicate (same URL)
    finally:
        conn.close()

def search_keyword(query: str, limit: int = 20, topic: str | None = None) -> list[dict]:
    """
    Performs exact-match keyword search using SQLite FTS5.
    Returns a list of dicts formatted similarly to ChromaDB's output for easy merging.
    """
    # 1. Extract CVE-style identifiers (e.g., CVE-2026-42952) before any sanitization
    #    so they are preserved as exact quoted phrases for FTS5.
    cve_pattern = re.compile(r'\bCVE-\d{4}-\d{4,}\b', re.IGNORECASE)
    cve_matches = cve_pattern.findall(query)
    
    # Remove CVEs from the query so they don't get split on hyphens below
    remaining_query = cve_pattern.sub(' ', query)
    
    # 2. Sanitize remaining query: keep alphanumeric, spaces, hyphens
    sanitized = re.sub(r'[^\w\s-]', ' ', remaining_query).lower()
    sanitized = sanitized.replace('-', ' ')
    
    # Remove common stop words to only search the important keywords
    stop_words = {'the', 'a', 'an', 'is', 'are', 'how', 'what', 'which', 'to', 'in', 'of', 'for', 'has', 'have', 'and', 'by', 'with'}
    words = [w for w in sanitized.split() if w not in stop_words and len(w) > 1]
    
    # 3. Build FTS5 match query
    #    - CVEs are kept as exact quoted phrases (e.g., "CVE-2026-42952")
    #    - Remaining terms are joined with AND for precision; the reranker handles recall.
    terms = []
    for cve in cve_matches:
        terms.append(f'"{cve}"')
    for word in words:
        terms.append(f'"{word}"*')
    
    if not terms:
        return []

    match_query = " AND ".join(terms)
    
    conn = get_conn()
    
    sql = """
        SELECT a.id, a.title, a.url, a.source, a.category, a.published_at, a.content, a.summary
        FROM articles_fts
        JOIN articles a ON articles_fts.rowid = a.id
        WHERE articles_fts MATCH ?
    """
    params = [match_query]

    if topic:
        sql += " AND a.category = ?"
        params.append(topic)

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    # Format to match ChromaDB's return structure
    results = []
    for row in rows:
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