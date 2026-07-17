# src/embed_index.py

from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer
from src.db import get_conn
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Path where Chroma will store its data
CHROMA_PATH = Path(__file__).resolve().parents[1] / "data" / "chroma"

# Init Chroma client + collection
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
collection = client.get_or_create_collection(
    name="news_articles",
    metadata={"hnsw:space": "cosine"},
)

# SentenceTransformer model for embeddings (FREE, downloaded once)
EMBED_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
embed_model = SentenceTransformer(EMBED_MODEL_NAME, trust_remote_code=True, device="mps")


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
    global collection
    try:
        client.delete_collection("news_articles")
    except Exception:
        pass
    collection = client.get_or_create_collection(
        name="news_articles",
        metadata={"hnsw:space": "cosine"},
    )
    print("Dropped and recreated 'news_articles' collection to clear old chunks.")

    rows = load_articles(limit=limit)
    print(f"Loaded {len(rows)} articles from DB.")

    ids: list[str] = []
    docs: list[str] = []
    metadatas: list[dict] = []

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=100,
    )

    for row in rows:
        article_id = str(row["id"])
        title = row["title"] or ""
        content = row["content"] or row["summary"] or ""

        text = (title + "\n\n" + content).strip()
        if not text:
            continue

        chunks = text_splitter.split_text(text)

        for i, chunk in enumerate(chunks):
            ids.append(f"{article_id}-{i}")
            docs.append(chunk)
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
