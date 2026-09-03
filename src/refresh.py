
from src.db import init_db
from src.fetch_feeds import fetch_all_feeds
from src.embed_index import sync_index
from src.logger import get_logger

logger = get_logger(__name__)


def main():
    logger.info("refresh_init_db")
    init_db()

    logger.info("refresh_fetch_feeds")
    fetch_all_feeds()

    logger.info("refresh_sync_index")
    sync_index()

    logger.info("refresh_complete")


if __name__ == "__main__":
    main()
