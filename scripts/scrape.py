# /// script
# requires-python = ">=3.12"
# dependencies = ["fire", "httpx", "selectolax>=0.3.27"]
# ///
"""Pull current offers from the listing portals into data/feed.json.

Usage:
    uv run scripts/scrape.py                       # all sources, then rebuild the pages yourself
    uv run scripts/scrape.py --sources=immowelt --max_requests=5 --dry_run
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import fire
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hausfeed import sources as portals
from hausfeed import store
from hausfeed.fetch import HEADERS, crawl, http_getter

ROOT = Path(__file__).resolve().parent.parent


def main(
    sources: str | tuple[str, ...] = "",
    max_requests: int = 150,
    delay: float = 2.0,
    dry_run: bool = False,
    feed: str = "data/feed.json",
) -> None:
    """Crawl each source politely, merge into the feed and print a summary.

    Args:
        sources: comma-separated source names (default: all).
        max_requests: page cap per source.
        delay: mean seconds between requests.
        dry_run: don't write the feed.
        feed: feed file relative to the repo root.
    """
    joined = ",".join(sources) if isinstance(sources, tuple) else sources  # fire turns "a,b" into a tuple
    names = [n for n in joined.split(",") if n] or None
    config: dict[str, Any] = json.loads((ROOT / "data" / "feed_config.json").read_text(encoding="utf-8"))
    today = date.today().isoformat()
    results = []
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        get = http_getter(client, delay)
        for src in portals.by_name(names):
            res = crawl(src, get, max_requests=max_requests)
            print(f"{src.name}: {len(res.offers)} offers from {res.requests} pages, {len(res.errors)} errors")
            for e in res.errors[:3]:
                print("   ", e)
            results.append(res)
    path = ROOT / feed
    data = store.load(path)
    stats = store.merge(data, results, today, config)
    active = sum(1 for r in data["offers"].values() if r.get("active"))
    print(f"merged: {stats} · {active} active offers")
    if not dry_run:
        store.save(data, path)
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    fire.Fire(main)
