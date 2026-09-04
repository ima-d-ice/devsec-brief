from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.db import (
    get_conn,
    rows_to_dicts,
    content_hash_for,
    delete_chunks_for_article,
    save_parent_docs,
)
from src.paths import ONNX_EMBED_PATH

embed_model = SentenceTransformer(
    str(ONNX_EMBED_PATH),
    backend="onnx",
    model_kwargs={
        "file_name": "onnx/model_qint8_arm64.onnx",
        "provider": "CPUExecutionProvider"
    }
)
# Big-to-small: small children for vector search, big parents for LLM context
child_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=100)
parent_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

CHILD_INSERT_SQL = """
    INSERT INTO article_chunks (article_id, chunk_index, parent_index, chunk_text, title, url, source, category, published_at, embedding)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _chunk_article(article: dict) -> tuple[list[dict], list[dict]]:
    """Returns (parents, children) with parent_index linkage."""
    text = (article["title"] or "") + "\n\n" + (article["content"] or article["summary"] or "")
    parent_texts = parent_splitter.split_text(text) or [text]
    parents = [
        {
            "parent_index": pi,
            "parent_text": pt,
            "title": article["title"],
            "url": article["url"],
            "source": article["source"],
            "category": article["category"],
            "published_at": article["published_at"],
        }
        for pi, pt in enumerate(parent_texts)
    ]
    children = []
    for pi, pt in enumerate(parent_texts):
        for ci, chunk in enumerate(child_splitter.split_text(pt)):
            children.append({
                "article_id": article["id"],
                "chunk_index": len(children),
                "parent_index": pi,
                "chunk_text": chunk,
                "title": article["title"],
                "url": article["url"],
                "source": article["source"],
                "category": article["category"],
                "published_at": article["published_at"],
            })
    return parents, children


def sync_index(limit: int = None, force_reindex: bool = False, prune_deleted: bool = False):
    """Upsert-aware synchronizer: inserts new, re-embeds changed (by content hash)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if force_reindex:
                cur.execute("TRUNCATE article_chunks RESTART IDENTITY CASCADE;")
                try:
                    cur.execute("TRUNCATE parent_docs RESTART IDENTITY CASCADE;")
                except Exception:
                    pass
                indexed_hashes = {}
            else:
                cur.execute("""
                    SELECT a.id, a.content_hash, COUNT(c.id) AS n_chunks
                    FROM articles a LEFT JOIN article_chunks c ON c.article_id = a.id
                    GROUP BY a.id;
                """)
                indexed_hashes = {}
                for row in cur.fetchall():
                    aid = row[0]
                    indexed_hashes[aid] = {"hash": None, "n": row[2] or 0}
                try:
                    cur.execute("SELECT id, content_hash FROM articles;")
                    for aid, h in cur.fetchall():
                        if aid in indexed_hashes:
                            indexed_hashes[aid]["hash"] = h
                except Exception:
                    pass

            sql = "SELECT id, title, url, source, category, summary, content, published_at FROM articles ORDER BY id DESC"
            if limit:
                sql += f" LIMIT {limit}"

            cur.execute(sql)
            all_articles = rows_to_dicts(cur)

    to_index = []
    to_reindex = []
    for a in all_articles:
        info = indexed_hashes.get(a["id"])
        current_hash = content_hash_for(a.get("title"), a.get("content"), a.get("summary"))
        if info is None or info.get("n", 0) == 0:
            to_index.append(a)
        elif info.get("hash") and info["hash"] != current_hash:
            to_reindex.append(a)
        elif not info.get("hash"):
            # Legacy rows without hash: treat as indexed to avoid full re-embed
            continue

    print(f"Total: {len(all_articles)} | new: {len(to_index)} | changed: {len(to_reindex)}")
    if prune_deleted:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM article_chunks WHERE article_id NOT IN (SELECT id FROM articles);
                """)
                try:
                    cur.execute("DELETE FROM parent_docs WHERE article_id NOT IN (SELECT id FROM articles);")
                except Exception:
                    pass

    for a in to_reindex:
        delete_chunks_for_article(a["id"])
    targets = to_index + to_reindex
    if not targets:
        print("✅ Index is already up to date.")
        return

    all_parents: list[tuple[int, list[dict]]] = []
    all_chunks = []
    all_texts = []
    for article in targets:
        parents, children = _chunk_article(article)
        all_parents.append((article["id"], parents))
        for ch in children:
            all_texts.append(ch["chunk_text"])
            all_chunks.append(ch)

    if not all_texts:
        print("No chunks produced.")
        return

    print(f"Encoding {len(all_texts)} child chunks from {len(targets)} articles...")
    embeddings = embed_model.encode(all_texts, show_progress_bar=True, batch_size=32)

    insert_data = [
        (
            chunk["article_id"],
            chunk["chunk_index"],
            chunk["parent_index"],
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
            cur.executemany(CHILD_INSERT_SQL, insert_data)
    for article_id, parents in all_parents:
        save_parent_docs(article_id, parents)

    print(f"✅ Sync complete: {len(insert_data)} child chunks, {sum(len(p) for _, p in all_parents)} parents.")


if __name__ == "__main__":
    sync_index()
