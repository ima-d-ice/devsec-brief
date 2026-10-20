#!/usr/bin/env python3
"""Feed-isolation drill: one 500 RSS feed must not cancel the healthy feed."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

GOOD_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>good</title>
<item><title>Drill article</title>
<link>https://loadtest.local/failure-drill/good-article</link>
<description>A healthy feed item for the isolation drill.</description>
</item></channel></rss>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/good.xml":
            body = GOOD_RSS.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(500)
            self.end_headers()

    def log_message(self, *_args):
        pass


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["FEEDS_OVERRIDE_JSON"] = json.dumps(
        [
            {"name": "drill-good", "url": "http://127.0.0.1:8765/good.xml", "category": "test"},
            {"name": "drill-bad", "url": "http://127.0.0.1:8765/bad.xml", "category": "test"},
        ]
    )
    from src.db import close_pool
    from src.fetch_feeds import fetch_all_feeds_async

    try:
        results = asyncio.run(fetch_all_feeds_async())
    finally:
        server.shutdown()
        close_pool()

    print(json.dumps(results, indent=2))
    failed = [r for r in results if r.get("status") == "failed"]
    good = [r for r in results if r.get("status") == "success"]
    if len(failed) == 1 and len(good) == 1:
        print("RESULT=PASS (one feed failed; healthy feed completed)")
        return 0
    print("RESULT=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
