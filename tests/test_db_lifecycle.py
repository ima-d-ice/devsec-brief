"""Database pool lifecycle and ingestion-run persistence (integration)."""

import pytest

from src.db import (
    check_db,
    close_pool,
    finish_ingestion_run,
    get_conn,
    get_pool,
    interrupt_stale_ingestion_runs,
    latest_successful_ingestion,
    open_pool,
    record_ingestion_feed,
    start_ingestion_run,
)

pytestmark = pytest.mark.integration


def test_pool_is_lazy_and_closes_cleanly():
    close_pool()
    pool = get_pool()
    assert pool.closed is True

    open_pool(wait=True, timeout=10)
    assert pool.closed is False
    assert check_db(timeout=2) is True

    close_pool()
    assert pool.closed is True


def test_ingestion_run_roundtrip():
    run_id = start_ingestion_run(feeds_total=2)
    record_ingestion_feed(run_id, "test-feed", "success", inserted=1)
    finish_ingestion_run(
        run_id,
        "success",
        inserted=1,
        feeds_failed=0,
        duration_ms=12.5,
    )
    latest = latest_successful_ingestion()
    assert latest is not None
    assert latest["articles_inserted"] == 1

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ingestion_runs WHERE id = %s;", (run_id,))


def test_stale_running_run_is_marked_interrupted():
    run_id = start_ingestion_run(feeds_total=1)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_runs SET started_at = NOW() - INTERVAL '2 hours' WHERE id = %s;",
                (run_id,),
            )

    assert interrupt_stale_ingestion_runs(older_than_minutes=30) >= 1

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, finished_at, error_summary FROM ingestion_runs WHERE id = %s;",
                (run_id,),
            )
            status, finished_at, error_summary = cur.fetchone()
            assert status == "interrupted"
            assert finished_at is not None
            assert "restarted" in error_summary
            cur.execute("DELETE FROM ingestion_runs WHERE id = %s;", (run_id,))
