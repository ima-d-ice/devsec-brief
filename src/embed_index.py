# src/embed_index.py

from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer
from src.db import get_conn

# Path where Chroma will store its data
CHROMA_PATH = Path(__file__).resolve().parents[1] / "data" / "chroma"

# Init Chroma client + collection
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
collection = client.get_or_create_collection(
    name="news_articles",
    metadata={"hnsw:space": "cosine"},
)

# SentenceTransformer model for embeddings (FREE, downloaded once)
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
embed_model = SentenceTransformer(EMBED_MODEL_NAME)


def load_articles(limit: int | None = None):
    """Load articles from SQLite into memory."""
    conn = get_conn()
    if limit:
        rows = conn.execute(
            "SELECT * FROM articles ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM articles ORDER BY id DESC",
        ).fetchall()
    conn.close()
    return rows


def sync_index(limit: int | None = None):
    rows = load_articles(limit=limit)
    print(f"Loaded {len(rows)} articles from DB.")

    ids: list[str] = []
    docs: list[str] = []
    metadatas: list[dict] = []

    for row in rows:
        article_id = str(row["id"])
        title = row["title"] or ""
        content = row["content"] or row["summary"] or ""

        text = (title + "\n\n" + content).strip()
        if not text:
            continue

        ids.append(article_id)
        docs.append(text)
        metadatas.append(
            {
                "title": title,
                "url": row["url"],
                "source": row["source"],
                "category": row["category"],
                "published_at": row["published_at"],
            }
        )

    if not ids:
        print("No non-empty documents to index.")
        return

    print(f"Encoding {len(docs)} documents with {EMBED_MODEL_NAME} ...")
    embeddings = embed_model.encode(docs, show_progress_bar=True).tolist()

    print("Upserting into Chroma...")
    collection.upsert(
        ids=ids,
        embeddings=embeddings,  # we provide embeddings directly
        documents=docs,
        metadatas=metadatas,
    )
    print("✅ Index sync complete.")


if __name__ == "__main__":
    sync_index()
