# src/fetch_feeds.py

import feedparser
import requests
from src.db import save_article_if_new

FEEDS = [
    # 🌐 Web Dev / General Tech
    {
        "name": "Hacker News",
        "url": "https://news.ycombinator.com/rss",
        "category": "webdev",
    },
    {
        "name": "MDN Blog",
        "url": "https://developer.mozilla.org/en-US/blog/rss.xml",
        "category": "webdev",
    },
    {
        "name": "web.dev",
        "url": "https://web.dev/feed.xml",
        "category": "webdev",
    },

    # 🛡 Cybersecurity
    {
        "name": "NCSC (NL Cyber Security)",
        "url": "https://feeds.english.ncsc.nl/news.rss",
        "category": "cybersec",
    },
    {
        "name": "CISA Cybersecurity Advisories",
        "url": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
        "category": "cybersec",
    },
    {
        "name": "The Hacker News",
        "url": "https://feeds.feedburner.com/TheHackersNews",
        "category": "cybersec",
    },
]


HEADERS = {
    # Pretend to be a normal browser; some sites block default Python UA
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0"
}


def fetch_single_feed(feed):
    print(f"\n=== Fetching: {feed['name']} ===")
    print(f"URL: {feed['url']}")

    try:
        resp = requests.get(feed["url"], headers=HEADERS, timeout=10)
        print(f"HTTP status: {resp.status_code}, bytes: {len(resp.content)}")
    except Exception as e:
        print(f"Request error for {feed['name']}: {e}")
        return 0

    if resp.status_code != 200:
        print(f"Non-200 response for {feed['name']}, skipping.")
        return 0

    parsed = feedparser.parse(resp.content)
    print(f"Entries found by feedparser: {len(parsed.entries)}")

    inserted = 0
    for entry in parsed.entries:
        published = getattr(entry, "published", "") or getattr(entry, "updated", "")

        # Try to get content; fall back to summary or empty string
        content = ""
        if getattr(entry, "content", None):
            try:
                content = entry.content[0].value
            except Exception:
                content = str(entry.content)
        elif getattr(entry, "summary", None):
            content = entry.summary

        data = {
            "title": getattr(entry, "title", "(no title)"),
            "url": getattr(entry, "link", ""),
            "source": feed["name"],
            "category": feed["category"],
            "summary": getattr(entry, "summary", "") or "",
            "content": content or "",
            "published_at": published or "",
        }

        if data["url"]:  # only save if we actually have a URL
            save_article_if_new(**data)
            inserted += 1

    print(f"Inserted (attempted) {inserted} articles for {feed['name']}")
    return inserted


def fetch_all_feeds():
    total = 0
    for feed in FEEDS:
        total += fetch_single_feed(feed)
    print(f"\n✅ Fetch complete. Attempted to insert {total} articles total.")
