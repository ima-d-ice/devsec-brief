"""Minimal, transaction-safe schema migration runner.

The legacy schema is the baseline (``init_db`` is idempotent and uses
``IF NOT EXISTS``). Subsequent changes live as ordered SQL files in
``migrations/`` and are applied exactly once, recorded in ``schema_migrations``.

Why not Alembic here? The project already had an idempotent baseline and no
migration history. This runner keeps the dependency surface small while giving
the compose stack a deterministic pre-start migration step. It is deliberately
simple enough to audit and test.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.db import close_pool, get_conn, init_db
from src.logger import get_logger

log = get_logger("migrate")
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
BASELINE_VERSION = "001_initial"


def _ensure_version_table() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version    TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )


def _applied_versions() -> set[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations;")
            return {row[0] for row in cur.fetchall()}


def _record(version: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING;",
                (version,),
            )


def _apply_sql_file(path: Path) -> None:
    sql = path.read_text()
    with get_conn() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(sql)


def migrate() -> int:
    """Apply the baseline and any pending SQL migrations. Idempotent."""
    log.info("migration_started")
    try:
        init_db()
        _ensure_version_table()
        applied = _applied_versions()

        if BASELINE_VERSION not in applied:
            _record(BASELINE_VERSION)
            applied.add(BASELINE_VERSION)
            log.info("migration_applied", extra={"fields": {"version": BASELINE_VERSION}})

        if MIGRATIONS_DIR.exists():
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = path.stem
                if version in applied:
                    continue
                try:
                    _apply_sql_file(path)
                    _record(version)
                    applied.add(version)
                    log.info("migration_applied", extra={"fields": {"version": version}})
                except Exception:
                    log.exception("migration_failed", extra={"fields": {"version": version}})
                    return 1

        log.info("migration_complete", extra={"fields": {"applied": len(applied)}})
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(migrate())
