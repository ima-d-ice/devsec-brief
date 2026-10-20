import time

from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.db import content_hash_for, get_conn, rows_to_dicts
from src.logger import get_logger
from src.paths import ONNX_EMBED_PATH

log = get_logger("embed_index")

embed_model = SentenceTransformer(
    str(ONNX_EMBED_PATH),
    backend="onnx",
    model_kwargs={
        "file_name": "onnx/model_qint8_arm64.onnx",
        "provider": "CPUExecutionProvider",
    },
)

# Big-to-small: small children for vector search, big parents for LLM context.
child_splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=100)
parent_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)

CHILD_INSERT_SQL = """
    INSERT INTO article_chunks (article_id, chunk_index, parent_index, chunk_text, title, url, source, category, published_at, embedding)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
PARENT_INSERT_SQL = """
    INSERT INTO parent_docs (article_id, parent_index, parent_text, title, url, source, category, published_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (article_id, parent_index) DO UPDATE SET parent_text = EXCLUDED.parent_text
"""


def _chunk_article(article: dict) -> tuple[list[dict], list[dict]]:
    """Return (parents, children) with parent_index linkage."""
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
        for chunk in child_splitter.split_text(pt):
            children.append(
                {
                    "article_id": article["id"],
                    "chunk_index": len(children),
                    "parent_index": pi,
                    "chunk_text": chunk,
                    "title": article["title"],
                    "url": article["url"],
                    "source": article["source"],
                    "category": article["category"],
                    "published_at": article["published_at"],
                }
            )
    return parents, children


def sync_index(limit: int = None, force_reindex: bool = False, prune_deleted: bool = False) -> dict:
    """Upsert-aware synchronizer: inserts new, re-embeds changed by content hash.

    Each article is replaced in its own transaction. A crash mid-run leaves the
    previous version of that article intact instead of a partially indexed one.
    """
    started = time.perf_counter()
    with get_conn() as conn:
        with conn.cursor() as cur:
            if force_reindex:
                cur.execute("TRUNCATE article_chunks RESTART IDENTITY CASCADE;")
                cur.execute("TRUNCATE parent_docs RESTART IDENTITY CASCADE;")
                indexed = {}
            else:
                cur.execute(
                    """
                    SELECT a.id, a.content_hash, COUNT(c.id) AS n_chunks
                    FROM articles a
                    LEFT JOIN article_chunks c ON c.article_id = a.id
                    GROUP BY a.id, a.content_hash;
                    """
                )
                indexed = {
                    row[0]: {"hash": row[1], "n": row[2] or 0}
                    for row in cur.fetchall()
                }

            sql = "SELECT id, title, url, source, category, summary, content, published_at FROM articles ORDER BY id DESC"
            if limit:
                sql += f" LIMIT {int(limit)}"
            cur.execute(sql)
            all_articles = rows_to_dicts(cur)

    to_index: list[dict] = []
    to_reindex: list[dict] = []
    for article in all_articles:
        info = indexed.get(article["id"])
        current_hash = content_hash_for(
            article.get("title"), article.get("content"), article.get("summary")
        )
        if info is None or info.get("n", 0) == 0:
            to_index.append(article)
        elif info.get("hash") and info["hash"] != current_hash:
            to_reindex.append(article)
        elif not info.get("hash"):
            # Legacy rows without hash: treat as indexed to avoid a full re-embed.
            continue

    if prune_deleted:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM article_chunks WHERE article_id NOT IN (SELECT id FROM articles);"
                )
                cur.execute(
                    "DELETE FROM parent_docs WHERE article_id NOT IN (SELECT id FROM articles);"
                )

    targets = to_index + to_reindex
    log.info(
        "index_sync_planned",
        extra={
            "fields": {
                "total": len(all_articles),
                "new": len(to_index),
                "changed": len(to_reindex),
            }
        },
    )
    if not targets:
        return {
            "total_articles": len(all_articles),
            "new_articles": 0,
            "changed_articles": 0,
            "indexed_articles": 0,
            "failed_articles": 0,
            "chunks": 0,
            "parents": 0,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    chunks_by_article: dict[int, list[dict]] = {}
    parents_by_article: dict[int, list[dict]] = {}
    all_texts: list[str] = []
    all_chunks: list[dict] = []
    for article in targets:
        parents, children = _chunk_article(article)
        parents_by_article[article["id"]] = parents
        chunks_by_article[article["id"]] = children
        for child in children:
            all_texts.append(child["chunk_text"])
            all_chunks.append(child)

    if not all_texts:
        return {
            "total_articles": len(all_articles),
            "new_articles": len(to_index),
            "changed_articles": len(to_reindex),
            "indexed_articles": 0,
            "failed_articles": len(targets),
            "chunks": 0,
            "parents": 0,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    log.info("index_encoding", extra={"fields": {"chunks": len(all_texts), "articles": len(targets)}})
    embeddings = embed_model.encode(all_texts, show_progress_bar=False, batch_size=32)
    embedding_by_chunk = {id(chunk): embeddings[i].tolist() for i, chunk in enumerate(all_chunks)}

    indexed_articles = 0
    failed_articles = 0
    with get_conn() as conn:
        for article in targets:
            article_id = article["id"]
            children = chunks_by_article.get(article_id, [])
            parents = parents_by_article.get(article_id, [])
            child_rows = [
                (
                    child["article_id"],
                    child["chunk_index"],
                    child["parent_index"],
                    child["chunk_text"],
                    child["title"],
                    child["url"],
                    child["source"],
                    child["category"],
                    child["published_at"],
                    embedding_by_chunk[id(child)],
                )
                for child in children
            ]
            parent_rows = [
                (
                    article_id,
                    parent["parent_index"],
                    parent["parent_text"],
                    parent["title"],
                    parent["url"],
                    parent["source"],
                    parent["category"],
                    parent["published_at"],
                )
                for parent in parents
            ]
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM article_chunks WHERE article_id = %s;", (article_id,))
                        cur.execute("DELETE FROM parent_docs WHERE article_id = %s;", (article_id,))
                        if child_rows:
                            cur.executemany(CHILD_INSERT_SQL, child_rows)
                        if parent_rows:
                            cur.executemany(PARENT_INSERT_SQL, parent_rows)
                indexed_articles += 1
            except Exception:
                failed_articles += 1
                log.exception("article_index_failed", extra={"fields": {"article_id": article_id}})

    result = {
        "total_articles": len(all_articles),
        "new_articles": len(to_index),
        "changed_articles": len(to_reindex),
        "indexed_articles": indexed_articles,
        "failed_articles": failed_articles,
        "chunks": len(all_chunks),
        "parents": sum(len(v) for v in parents_by_article.values()),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    log.info("index_sync_complete", extra={"fields": result})
    return result


if __name__ == "__main__":
    from src.db import close_pool

    try:
        sync_index()
    finally:
        close_pool()
