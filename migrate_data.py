import os
import sqlite3
import json
from pathlib import Path
from src.db import get_conn, init_db

SQLITE_PATH = Path(__file__).resolve().parent / "data" / "articles.db"
CHROMA_PATH = Path(__file__).resolve().parent / "data" / "chroma"

def migrate_articles():
    print(f"Migrating articles from {SQLITE_PATH} to Postgres...")
    
    if not SQLITE_PATH.exists():
        print("No sqlite db found, skipping articles migration.")
        return 0
        
    old_conn = sqlite3.connect(SQLITE_PATH)
    old_conn.row_factory = sqlite3.Row
    old_rows = old_conn.execute("SELECT * FROM articles").fetchall()
    
    migrated_count = 0
    with get_conn() as pg_conn:
        with pg_conn.cursor() as cur:
            for row in old_rows:
                cur.execute("""
                    INSERT INTO articles (id, title, url, source, category, summary, content, published_at)
                    VALUES (%(id)s, %(title)s, %(url)s, %(source)s, %(category)s, %(summary)s, %(content)s, %(published_at)s)
                    ON CONFLICT (url) DO NOTHING
                    RETURNING id;
                """, dict(row))
                if cur.fetchone():
                    migrated_count += 1
        pg_conn.commit()
    print(f"Migrated {migrated_count} articles to Postgres.")
    return len(old_rows)

def migrate_chunks():
    print(f"Migrating chunks from {CHROMA_PATH} to Postgres...")
    
    if not CHROMA_PATH.exists():
        print("No chroma db found, skipping chunks migration.")
        return 0
        
    try:
        import chromadb
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection = chroma_client.get_collection(name="news_articles")
    except Exception as e:
        print(f"Could not load chroma collection: {e}")
        return 0
        
    data = collection.get(include=["embeddings", "metadatas", "documents"])
    ids = data.get("ids", [])
    embeddings = data.get("embeddings", [])
    metadatas = data.get("metadatas", [])
    documents = data.get("documents", [])
    
    if not ids:
        print("Chroma collection empty.")
        return 0
        
    insert_data = []
    
    with get_conn() as pg_conn:
        with pg_conn.cursor() as cur:
            for i in range(len(ids)):
                chunk_id_str = ids[i]
                article_id_str = chunk_id_str.split('-')[0]
                chunk_index = int(chunk_id_str.split('-')[1])
                
                cur.execute("SELECT id FROM articles WHERE id = %s", (article_id_str,))
                if not cur.fetchone():
                    print(f"Skipping chunk {chunk_id_str}, article {article_id_str} not in Postgres.")
                    continue
                    
                meta = metadatas[i] or {}
                insert_data.append((
                    article_id_str,
                    chunk_index,
                    documents[i],
                    meta.get("title"),
                    meta.get("url"),
                    meta.get("source"),
                    meta.get("category"),
                    meta.get("published_at"),
                    list(embeddings[i])
                ))
            
            insert_sql = """
                INSERT INTO article_chunks (article_id, chunk_index, chunk_text, title, url, source, category, published_at, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cur.executemany(insert_sql, insert_data)
            pg_conn.commit()
    
    with get_conn() as pg_conn:
        pg_conn.autocommit = True
        with pg_conn.cursor() as cur:
            cur.execute("VACUUM ANALYZE article_chunks;")
            
    print(f"Migrated {len(insert_data)} chunks to Postgres and ran VACUUM ANALYZE.")
    return len(insert_data)

if __name__ == "__main__":
    init_db()
    migrate_articles()
    migrate_chunks()
    print("Migration complete!")
