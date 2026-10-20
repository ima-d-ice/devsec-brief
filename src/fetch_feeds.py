import asyncio
import json
import os
import random
import time
from typing import Any

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from src import obs
from src.db import upsert_article
from src.logger import get_logger
from src.sanitize import sanitize_content

log = get_logger("fetch_feeds")

REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 1.0


def strip_html(html_text: str) -> str:
    if not html_text:
        return ""
    try:
        return BeautifulSoup(html_text, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        return str(html_text)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


FEEDS = [
    {"name": "Hacker News", "url": "https://news.ycombinator.com/rss", "category": "webdev"},
    {"name": "MDN Blog", "url": "https://developer.mozilla.org/en-US/blog/rss.xml", "category": "webdev"},
    {"name": "web.dev", "url": "https://web.dev/feed.xml", "category": "webdev"},
    {"name": "NCSC (NL Cyber Security)", "url": "https://advisories.ncsc.nl/rss/advisories", "category": "cybersec"},
    {"name": "CISA Cybersecurity Advisories", "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml", "category": "cybersec"},
    {"name": "The Hacker News", "url": "https://feeds.feedburner.com/TheHackersNews", "category": "cybersec"},
]


def configured_feeds() -> list[dict]:
    """Allow tests and failure drills to point at a controlled RSS server."""
    raw = os.getenv("FEEDS_OVERRIDE_JSON")
    if not raw:
        return FEEDS
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict) and item.get("url")]
    except json.JSONDecodeError:
        log.warning("feeds_override_invalid")
    return FEEDS


def _failed(feed: dict, error: str, started: float) -> dict:
    return {
        "feed": feed.get("name", "unknown"),
        "status": "failed",
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "failed_entries": 0,
        "error": error[:500],
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def fetch_single_feed_async(session: aiohttp.ClientSession, feed: dict) -> dict:
    """Fetch one feed. Never raises for expected network/parse failures."""
    started = time.perf_counter()
    content_data: bytes | None = None
    last_error: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            # Some public feeds (notably CISA) reject requests that do not
            # advertise an RSS-capable Accept header.
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with session.get(
                feed["url"],
                headers=headers,
                timeout=aiohttp.ClientTimeout(
                    total=REQUEST_TIMEOUT_SECONDS, connect=5
                ),
            ) as resp:
                if resp.status == 200:
                    content_data = await resp.read()
                    break
                if resp.status in (400, 403, 404, 410):
                    obs.INGESTION_FEED_FAILURES.labels(feed=feed["name"]).inc()
                    return _failed(feed, f"permanent HTTP {resp.status}", started)
                last_error = f"HTTP {resp.status}"
        except asyncio.TimeoutError:
            last_error = "timeout"
        except aiohttp.ClientError as exc:
            last_error = type(exc).__name__

        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            log.warning(
                "feed_retry",
                extra={"fields": {"feed": feed["name"], "attempt": attempt, "delay_s": round(delay, 2)}},
            )
            await asyncio.sleep(delay)

    if not content_data:
        obs.INGESTION_FEED_FAILURES.labels(feed=feed["name"]).inc()
        return _failed(feed, last_error or "no content", started)

    parsed = feedparser.parse(content_data)
    if parsed.bozo and not parsed.entries:
        obs.INGESTION_FEED_FAILURES.labels(feed=feed["name"]).inc()
        return _failed(feed, "invalid RSS/Atom document", started)

    inserted = updated = skipped = failed_entries = 0
    for entry in parsed.entries:
        published = getattr(entry, "published", getattr(entry, "updated", ""))
        content = ""
        if getattr(entry, "content", None):
            try:
                content = entry.content[0].value
            except (IndexError, AttributeError, TypeError):
                content = str(entry.content)
        elif getattr(entry, "summary", None):
            content = entry.summary

        data = {
            "title": sanitize_content(strip_html(getattr(entry, "title", "(no title)"))),
            "url": (getattr(entry, "link", "") or "").strip(),
            "source": feed["name"],
            "category": feed["category"],
            "summary": sanitize_content(strip_html(getattr(entry, "summary", "") or "")),
            "content": sanitize_content(strip_html(content or "")),
            "published_at": published or "",
        }
        if not data["url"]:
            skipped += 1
            continue
        try:
            _article_id, state = await asyncio.to_thread(upsert_article, **data)
            if state == "inserted":
                inserted += 1
            elif state == "updated":
                updated += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001 - one bad article must not kill a feed
            failed_entries += 1
            log.warning(
                "article_persist_failed",
                extra={"fields": {"feed": feed["name"], "error": type(exc).__name__}},
            )

    status = "success" if failed_entries == 0 else "partial"
    if inserted:
        obs.INGESTION_ARTICLES.labels(result="inserted").inc(inserted)
    if updated:
        obs.INGESTION_ARTICLES.labels(result="updated").inc(updated)
    if skipped:
        obs.INGESTION_ARTICLES.labels(result="skipped").inc(skipped)
    if failed_entries:
        obs.INGESTION_ARTICLES.labels(result="failed").inc(failed_entries)

    log.info(
        "feed_fetched",
        extra={
            "fields": {
                "feed": feed["name"],
                "status": status,
                "entries": len(parsed.entries),
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "failed": failed_entries,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        },
    )
    return {
        "feed": feed["name"],
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "failed_entries": failed_entries,
        "error": None,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def fetch_all_feeds_async() -> list[dict]:
    """Fetch every feed concurrently; one failure never aborts the others."""
    feeds = configured_feeds()
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS + 10, connect=5)
    connector = aiohttp.TCPConnector(limit=10, ssl=True)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        results = await asyncio.gather(
            *(fetch_single_feed_async(session, feed) for feed in feeds),
            return_exceptions=True,
        )

    normalized: list[dict] = []
    for feed, result in zip(feeds, results):
        if isinstance(result, BaseException):
            obs.INGESTION_FEED_FAILURES.labels(feed=feed.get("name", "unknown")).inc()
            normalized.append(_failed(feed, type(result).__name__, time.perf_counter()))
        else:
            normalized.append(result)
    return normalized


def fetch_all_feeds() -> list[dict]:
    results = asyncio.run(fetch_all_feeds_async())
    log.info(
        "fetch_complete",
        extra={
            "fields": {
                "feeds": len(results),
                "inserted": sum(r.get("inserted", 0) for r in results),
                "updated": sum(r.get("updated", 0) for r in results),
                "failed": sum(1 for r in results if r.get("status") == "failed"),
            }
        },
    )
    return results
