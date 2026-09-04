
import fcntl
from contextlib import contextmanager

from src.db import init_db
from src.fetch_feeds import fetch_all_feeds
from src.embed_index import sync_index
from src.logger import get_logger

log = get_logger("refresh")
LOCK_PATH = "/tmp/refresh.lock"


@contextmanager
def single_run():
    """File lock: skip run if a previous refresh is still going."""
    with open(LOCK_PATH, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log.warning("refresh skipped: previous run still active")
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def main():
    init_db()

    with single_run() as acquired:
        if not acquired:
            return
        log.info("refresh step=fetch")
        fetch_all_feeds()

        log.info("refresh step=index")
        sync_index()

        log.info("refresh complete")


if __name__ == "__main__":
    main()
