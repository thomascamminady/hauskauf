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
from hausfeed.fetch import HEADERS, CrawlResult, crawl, http_getter

ROOT = Path(__file__).resolve().parent.parent


def main(
    sources: str | tuple[str, ...] = "",
    max_requests: int = 150,
    delay: float = 2.0,
    budget: float = 600.0,
    dry_run: bool = False,
    feed: str = "data/feed.json",
) -> None:
    """Crawl each source politely, merge into the feed after every source and print a summary.

    Built to always finish: each portal has its own time budget, a failing or stalling portal is recorded and
    skipped, and the feed is saved after every portal (atomically), so a run killed later keeps what it had.

    Args:
        sources: comma-separated source names (default: all).
        max_requests: page cap per source.
        delay: mean seconds between requests.
        budget: seconds per source before its crawl stops (an incomplete crawl never marks offers gone).
        dry_run: don't write the feed.
        feed: feed file relative to the repo root.
    """
    joined = ",".join(sources) if isinstance(sources, tuple) else sources  # fire turns "a,b" into a tuple
    names = [n for n in joined.split(",") if n] or None
    config: dict[str, Any] = json.loads((ROOT / "data" / "feed_config.json").read_text(encoding="utf-8"))
    today = date.today().isoformat()
    path = ROOT / feed
    data = store.load(path)
    problems: list[str] = []
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=httpx.Timeout(30, connect=10)) as client:
        get = http_getter(client, delay)
        for src in portals.by_name(names):
            try:
                res = crawl(src, get, max_requests=max_requests, budget_s=budget)
            except Exception as e:  # noqa: BLE001 – crawl() shouldn't raise, but never let one portal stop the run
                res = CrawlResult(source=src.name, complete=False, errors=[f"seed crash: {type(e).__name__} {e}"])
            state = "ok" if res.ok else "INCOMPLETE (nothing marked gone)"
            print(f"{src.name}: {len(res.offers)} offers from {res.requests} pages, {len(res.errors)} errors – {state}")
            for e in res.errors[:3]:
                print("   ", e)
            if not res.ok or not res.offers:
                problems.append(f"{src.name}: {len(res.offers)} offers, {res.errors[:1]}")
            stats = store.merge(data, [res], today, config)
            print(f"   merged: {stats}")
            if not dry_run:
                store.save(data, path)
    active = sum(1 for r in data["offers"].values() if r.get("active"))
    print(f"{active} active offers" + ("" if dry_run else f" · wrote {path.relative_to(ROOT)}"))
    for p in problems:
        print(f"::warning::{p}")  # shows up as an annotation on GitHub Actions


if __name__ == "__main__":
    fire.Fire(main)
