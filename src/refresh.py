"""Scheduled RSS ingestion worker.

A run is one fetch + index cycle. It is protected by a Postgres advisory lock so
multiple containers (or a restarted container) cannot run concurrently. Every
run is recorded, including failures, so freshness and success can be alerted on.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from src import obs
from src.db import (
    close_pool,
    finish_ingestion_run,
    get_conn,
    interrupt_stale_ingestion_runs,
    latest_content_created_at,
    latest_successful_ingestion,
    record_ingestion_feed,
    start_ingestion_run,
)
from src.embed_index import sync_index
from src.fetch_feeds import configured_feeds, fetch_all_feeds
from src.logger import get_logger
from src.settings import settings

log = get_logger("refresh")
LOCK_KEY = 1_515_870_810
_stop = threading.Event()


def _handle_signal(signum, _frame) -> None:
    log.info("refresh_shutdown_requested", extra={"fields": {"signal": signum}})
    _stop.set()


def _refresh_freshness() -> None:
    try:
        latest = latest_successful_ingestion()
        if latest and latest.get("finished_at"):
            obs.INGESTION_LAST_SUCCESS.set(latest["finished_at"].timestamp())
        newest = latest_content_created_at()
        if newest:
            if newest.tzinfo is None:
                newest = newest.replace(tzinfo=timezone.utc)
            obs.INGESTION_CONTENT_AGE.set(
                max(0.0, (datetime.now(timezone.utc) - newest).total_seconds())
            )
    except Exception as exc:  # noqa: BLE001 - metrics must not break ingestion
        log.warning("freshness_metrics_failed", extra={"fields": {"error": type(exc).__name__}})


def run_once() -> int:
    """Run one ingestion cycle. Returns a process exit code."""
    started = time.perf_counter()
    run_id: int | None = None
    results: list[dict] = []
    index_result: dict = {}
    status = "failed"

    try:
        with get_conn() as lock_conn:
            with lock_conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s);", (LOCK_KEY,))
                acquired = bool(cur.fetchone()[0])
            if not acquired:
                log.warning("refresh_skipped_lock_held")
                return 0

            try:
                interrupted = interrupt_stale_ingestion_runs()
                if interrupted:
                    log.warning(
                        "stale_ingestion_runs_closed",
                        extra={"fields": {"runs": interrupted}},
                    )
                run_id = start_ingestion_run(len(configured_feeds()))
                log.info("refresh_run_started", extra={"fields": {"run_id": run_id}})

                results = fetch_all_feeds()
                if _stop.is_set():
                    status = "interrupted"
                else:
                    index_result = sync_index() or {}
                    status = "success" if all(
                        r.get("status") == "success" for r in results
                    ) else ("partial" if any(r.get("status") != "failed" for r in results) else "failed")
            finally:
                with lock_conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s);", (LOCK_KEY,))

        inserted = sum(r.get("inserted", 0) for r in results)
        updated = sum(r.get("updated", 0) for r in results)
        skipped = sum(r.get("skipped", 0) for r in results)
        failed_feeds = sum(1 for r in results if r.get("status") == "failed")
        errors = [f"{r['feed']}: {r.get('error')}" for r in results if r.get("error")]
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        if run_id is not None:
            for result in results:
                record_ingestion_feed(
                    run_id,
                    result.get("feed", "unknown"),
                    result.get("status", "unknown"),
                    inserted=result.get("inserted", 0),
                    updated=result.get("updated", 0),
                    skipped=result.get("skipped", 0),
                    duration_ms=result.get("duration_ms"),
                    error_message=result.get("error"),
                )
            finish_ingestion_run(
                run_id,
                status,
                inserted=inserted,
                updated=updated,
                skipped=skipped,
                feeds_failed=failed_feeds,
                duration_ms=duration_ms,
                error_summary="; ".join(errors) if errors else None,
            )

        obs.INGESTION_RUNS.labels(result=status).inc()
        obs.INGESTION_DURATION.observe(max(0.0, time.perf_counter() - started))
        _refresh_freshness()

        log.info(
            "refresh_run_finished",
            extra={
                "fields": {
                    "run_id": run_id,
                    "status": status,
                    "inserted": inserted,
                    "updated": updated,
                    "skipped": skipped,
                    "failed_feeds": failed_feeds,
                    "indexed": index_result.get("indexed_articles", 0),
                    "duration_ms": duration_ms,
                }
            },
        )
        return 0 if status in {"success", "partial"} else 1
    except Exception as exc:  # noqa: BLE001 - record then surface failure
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        log.exception("refresh_run_failed")
        obs.INGESTION_RUNS.labels(result="failed").inc()
        obs.INGESTION_DURATION.observe(max(0.0, time.perf_counter() - started))
        if run_id is not None:
            try:
                finish_ingestion_run(
                    run_id,
                    "failed",
                    duration_ms=duration_ms,
                    error_summary=type(exc).__name__,
                )
            except Exception:
                log.exception("refresh_run_record_failed")
        return 1


def main_loop(interval_hours: float | None = None) -> int:
    interval = (interval_hours or settings.refresh_interval_hours) * 3600
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        from prometheus_client import start_http_server

        metrics_port = int(os.getenv("REFRESH_METRICS_PORT", "9101"))
        start_http_server(metrics_port)
        log.info("refresh_metrics_server_started", extra={"fields": {"port": metrics_port}})
    except Exception as exc:  # noqa: BLE001 - metrics must not stop ingestion
        log.warning("refresh_metrics_server_failed", extra={"fields": {"error": type(exc).__name__}})
    # Publish the last known freshness immediately after a restart instead of
    # leaving the scrape target empty until the first cycle completes.
    _refresh_freshness()
    while not _stop.is_set():
        run_once()
        if _stop.wait(timeout=interval):
            break
    log.info("refresh_loop_stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DevSec-Brief ingestion worker")
    parser.add_argument("--loop", action="store_true", help="run forever on the configured interval")
    parser.add_argument("--interval-hours", type=float, default=None)
    args = parser.parse_args()
    try:
        if args.loop:
            return main_loop(args.interval_hours)
        signal.signal(signal.SIGTERM, _handle_signal)
        return run_once()
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
