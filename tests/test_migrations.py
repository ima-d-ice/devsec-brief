"""Migration runner is idempotent and records its baseline (integration)."""

import pytest

from src.db import get_conn
from src.migrate import BASELINE_VERSION, migrate

pytestmark = pytest.mark.integration


def test_migrate_is_idempotent():
    assert migrate() == 0
    assert migrate() == 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version FROM schema_migrations WHERE version = %s;",
                (BASELINE_VERSION,),
            )
            assert cur.fetchone() is not None
