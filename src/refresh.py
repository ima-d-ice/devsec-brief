
from src.db import init_db
from src.fetch_feeds import fetch_all_feeds
from src.embed_index import sync_index


def main():
    init_db()

    print("=== Step 1: Fetching feeds ===")
    fetch_all_feeds()

    print("\n=== Step 2: Syncing embeddings + pgvector index ===")
    sync_index()

    print("\n✅ Refresh complete.")


if __name__ == "__main__":
    main()
