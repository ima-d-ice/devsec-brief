# src/refresh.py

from src.db import init_db
from src.fetch_feeds import fetch_all_feeds
from src.embed_index import sync_index


def main():
    # Make sure DB exists
    init_db()

    print("=== Step 1: Fetching feeds ===")
    fetch_all_feeds()

    print("\n=== Step 2: Syncing embeddings + Chroma index ===")
    # For small data you can just re-sync all
    sync_index()

    print("\n✅ Refresh complete.")


if __name__ == "__main__":
    main()
