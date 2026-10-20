"""Ingestion isolation tests: one failed feed never cancels the rest."""

import asyncio

import src.fetch_feeds as feeds


def test_configured_feeds_override(monkeypatch):
    monkeypatch.setenv(
        "FEEDS_OVERRIDE_JSON",
        '[{"name": "Local", "url": "http://localhost:9/rss", "category": "test"}]',
    )
    configured = feeds.configured_feeds()
    assert configured[0]["name"] == "Local"


def test_feed_failure_is_isolated(monkeypatch):
    two_feeds = [
        {"name": "good", "url": "http://good.test/rss", "category": "test"},
        {"name": "bad", "url": "http://bad.test/rss", "category": "test"},
    ]
    monkeypatch.setattr(feeds, "configured_feeds", lambda: two_feeds)

    async def fake_fetch(session, feed):
        if feed["name"] == "bad":
            raise RuntimeError("boom")
        return {
            "feed": "good",
            "status": "success",
            "inserted": 2,
            "updated": 0,
            "skipped": 0,
            "failed_entries": 0,
            "error": None,
            "duration_ms": 1.0,
        }

    monkeypatch.setattr(feeds, "fetch_single_feed_async", fake_fetch)
    results = asyncio.run(feeds.fetch_all_feeds_async())
    assert len(results) == 2
    assert results[0]["status"] == "success"
    assert results[1]["status"] == "failed"
    assert results[1]["inserted"] == 0
