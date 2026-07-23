import time
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.db import get_conn

from pathlib import Path

ONNX_EMBED_PATH = Path(__file__).resolve().parents[1] / "data" / "onnx_st" / "bge-m3-onnx"

embed_model = SentenceTransformer(
    str(ONNX_EMBED_PATH), 
    backend="onnx",
    model_kwargs={
        "file_name": "onnx/model_qint8_arm64.onnx",
        "provider": "CPUExecutionProvider"
    }
)
text_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=100)

def sync_index(limit=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE article_chunks RESTART IDENTITY CASCADE;")
            conn.commit()

            sql = "SELECT id, title, url, source, category, summary, content, published_at FROM articles ORDER BY id DESC"
            if limit:
                sql += f" LIMIT {limit}"
            
            cur.execute(sql)
            rows = cur.fetchall()
            col_names = [desc[0] for desc in cur.description]
            articles = [dict(zip(col_names, row)) for row in rows]

    print(f"Loaded {len(articles)} articles")

    all_chunks = []
    all_texts_for_embedding = []

    for article in articles:
        text_to_chunk = (article["title"] or "") + "\n\n" + (article["content"] or article["summary"] or "")
        splits = text_splitter.split_text(text_to_chunk)
        
        for i, chunk in enumerate(splits):
            all_texts_for_embedding.append(chunk)
            all_chunks.append({
                "article_id": article["id"],
                "chunk_index": i,
                "chunk_text": chunk,
                "title": article["title"],
                "url": article["url"],
                "source": article["source"],
                "category": article["category"],
                "published_at": article["published_at"],
            })

    if not all_texts_for_embedding:
        print("No documents to encode.")
        return

    print(f"Encoding {len(all_texts_for_embedding)} documents")
    embeddings = embed_model.encode(all_texts_for_embedding, show_progress_bar=True, batch_size=32)

    print("Upserting...")
    
    insert_sql = """
        INSERT INTO article_chunks (article_id, chunk_index, chunk_text, title, url, source, category, published_at, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    insert_data = [
        (
            chunk["article_id"],
            chunk["chunk_index"],
            chunk["chunk_text"],
            chunk["title"],
            chunk["url"],
            chunk["source"],
            chunk["category"],
            chunk["published_at"],
            embeddings[i].tolist()
        )
        for i, chunk in enumerate(all_chunks)
    ]
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(insert_sql, insert_data)
            conn.commit()

    print("✅ Index sync complete.")

if __name__ == "__main__":
    sync_index()
