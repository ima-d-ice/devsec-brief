import random
import time
import asyncio
import aiohttp
import feedparser
from bs4 import BeautifulSoup
from src.db import save_article_if_new

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
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]


FEEDS = [
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

    {
        "name": "NCSC (NL Cyber Security)",
        "url": "https://advisories.ncsc.nl/rss/advisories",
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

async def fetch_single_feed_async(session: aiohttp.ClientSession, feed: dict) -> int:
    print(f"\n=== Fetching: {feed['name']} ===")
    print(f"URL: {feed['url']}")

    max_retries = 3
    content_data = None
    status_code = None

    for attempt in range(1, max_retries + 1):
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        try:
            async with session.get(feed["url"], headers=headers, timeout=10) as resp:
                status_code = resp.status
                if status_code == 200:
                    content_data = await resp.read()
                    print(f"Success on attempt {attempt}.")
                    break
                elif status_code in [400, 403, 404, 410]:
                    print(f"Permanent error {status_code}. Not retrying.")
                    return 0
                else:
                    print(f"Attempt {attempt} failed (Status {status_code}).")

        except Exception as e:
            print(f"Attempt {attempt} failed: Network error ({e})")

        if attempt < max_retries:
            sleep_time = 2 ** attempt
            print(f"Retrying in {sleep_time} seconds...")
            await asyncio.sleep(sleep_time)

    if not content_data or status_code != 200:
        print(f" Giving up on {feed['name']} after {max_retries} attempts.")
        return 0
    
    parsed = feedparser.parse(content_data)
    print(f"Entries found: {len(parsed.entries)}")

    new_inserted = 0
    duplicates_skipped = 0
    for entry in parsed.entries:
        published = getattr(entry, "published", getattr(entry, "updated", ""))

        content = ""
        if getattr(entry, "content", None):
            try:
                content = entry.content[0].value
            except (IndexError, AttributeError, TypeError) as e:
                content = str(entry.content)
        elif getattr(entry, "summary", None):
            content = entry.summary

        data = {
            "title": strip_html(getattr(entry, "title", "(no title)")),
            "url": getattr(entry, "link", ""),
            "source": feed["name"],
            "category": feed["category"],
            "summary": strip_html(getattr(entry, "summary", "") or ""),
            "content": strip_html(content or ""),
            "published_at": published or "",
        }
        if data["url"]:  
            is_new = await asyncio.to_thread(save_article_if_new, **data)
            if is_new:
                new_inserted += 1
            else:
                duplicates_skipped += 1
        
    print(f"Inserted {new_inserted} articles for {feed['name']}")   
    print(f"Skipped {duplicates_skipped} duplicate articles for {feed['name']}")
    return new_inserted

async def fetch_all_feeds_async() -> int:
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_single_feed_async(session, feed) for feed in FEEDS]
        results = await asyncio.gather(*tasks)
        return sum(results)

def fetch_all_feeds() -> None:
    total = asyncio.run(fetch_all_feeds_async())
    print(f"\nFetch complete. Inserted {total} articles total.")
