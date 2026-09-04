
from src.db import init_db
from src.fetch_feeds import fetch_all_feeds
from src.embed_index import sync_index
from src.logger import get_logger

log = get_logger("refresh")


def main():
    init_db()

    log.info("refresh step=fetch")
    fetch_all_feeds()

    log.info("refresh step=index")
    sync_index()

    log.info("refresh complete")


if __name__ == "__main__":
    main()
