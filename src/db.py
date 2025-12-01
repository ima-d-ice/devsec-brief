# src/db.py

import sqlite3
from pathlib import Path

# DB path inside /data/
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "articles.db"

# Create DB if not exists
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
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
    conn.commit()
    conn.close()
    print("DB initialized at:", DB_PATH)

def save_article_if_new(**kwargs):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO articles (title, url, source, category, summary, content, published_at)
            VALUES (:title, :url, :source, :category, :summary, :content, :published_at)
        """, kwargs)
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # ignore duplicates (same URL)
    finally:
        conn.close()
