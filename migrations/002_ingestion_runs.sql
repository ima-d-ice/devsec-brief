-- Explicit forward migration for deployments created before ingestion run
-- tracking existed. Statements are idempotent so the baseline (init_db) can
-- safely create the same objects first.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id                BIGSERIAL PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at       TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'running',
    articles_inserted INTEGER NOT NULL DEFAULT 0,
    articles_updated  INTEGER NOT NULL DEFAULT 0,
    articles_skipped  INTEGER NOT NULL DEFAULT 0,
    feeds_total       INTEGER NOT NULL DEFAULT 0,
    feeds_failed      INTEGER NOT NULL DEFAULT 0,
    duration_ms       DOUBLE PRECISION,
    error_summary     TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started
    ON ingestion_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status
    ON ingestion_runs (status, started_at DESC);

CREATE TABLE IF NOT EXISTS ingestion_feed_runs (
    id            BIGSERIAL PRIMARY KEY,
    run_id        BIGINT REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    feed          TEXT NOT NULL,
    status        TEXT NOT NULL,
    inserted      INTEGER NOT NULL DEFAULT 0,
    updated       INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL DEFAULT 0,
    duration_ms   DOUBLE PRECISION,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_feed_runs_run
    ON ingestion_feed_runs (run_id);
