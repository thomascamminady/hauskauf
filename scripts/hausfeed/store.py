"""data/feed.json: every offer ever seen, with first/last seen dates, price history and active flag."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hausfeed.core import Offer
from hausfeed.fetch import CrawlResult

FeedDict = dict[str, Any]
KEEP_GONE_DAYS = 60
MAX_RUNS = 60


def load(path: Path) -> FeedDict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"updated": None, "runs": [], "offers": {}}


def save(feed: FeedDict, path: Path) -> None:
    feed["offers"] = dict(sorted(feed["offers"].items()))
    path.write_text(json.dumps(feed, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def keep(offer: Offer, config: dict[str, Any]) -> bool:
    """Apply the coarse filters from data/feed_config.json (the page filters further)."""
    if offer.size_m2 is not None and offer.size_m2 < config.get("min_size_m2", 0):
        return False
    if offer.price is not None and offer.price > config.get("max_price", 10**9):
        return False
    if offer.price is not None and offer.price < config.get("min_price", 0):
        return False
    pattern = config.get("exclude_title_regex")
    return not (pattern and re.search(pattern, offer.title, re.IGNORECASE))


def _days_between(a: str, b: str) -> int:
    from datetime import date

    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def merge(feed: FeedDict, results: list[CrawlResult], today: str, config: dict[str, Any]) -> dict[str, int]:
    """Fold one run into ``feed`` in place. Returns counts for the run log."""
    offers: dict[str, FeedDict] = feed["offers"]
    stats = {"new": 0, "price_changed": 0, "gone": 0, "seen": 0}
    for res in results:
        seen_now: set[str] = set()
        for o in res.offers:
            if not keep(o, config):
                continue
            seen_now.add(o.key)
            stats["seen"] += 1
            facts = o.to_dict()
            old = offers.get(o.key)
            if old is None:
                offers[o.key] = {
                    **facts,
                    "first_seen": today,
                    "last_seen": today,
                    "active": True,
                    "price_history": [[today, o.price]] if o.price else [],
                }
                stats["new"] += 1
                continue
            if o.price and old.get("price") and o.price != old["price"]:
                old.setdefault("price_history", []).append([today, o.price])
                stats["price_changed"] += 1
            # Keep facts a page sometimes omits.
            for k, v in facts.items():
                if v is not None or k not in old:
                    old[k] = v
            old["last_seen"] = today
            if not old.get("active", True):
                old["reappeared"] = today
            old["active"] = True
        if res.ok:
            for key, rec in offers.items():
                if rec["source"] == res.source and rec.get("active") and key not in seen_now:
                    rec["active"] = False
                    rec["gone"] = today
                    stats["gone"] += 1
        feed["runs"].append(
            {
                "date": today,
                "source": res.source,
                "ok": res.ok,
                "requests": res.requests,
                "offers": len(seen_now),
                "errors": res.errors[:5],
            }
        )
    for key in [
        k
        for k, r in offers.items()
        if not r.get("active") and _days_between(r.get("gone", today), today) > KEEP_GONE_DAYS
    ]:
        del offers[key]
    feed["runs"] = feed["runs"][-MAX_RUNS:]
    feed["updated"] = today
    link_duplicates(offers)
    return stats


def _sig(r: FeedDict) -> tuple[str, str, int] | None:
    if not (r.get("zip") and r.get("size_m2") and r.get("price")):
        return None
    return (r["kind"], r["zip"], round(r["size_m2"]))


def link_duplicates(offers: dict[str, FeedDict]) -> None:
    """Mark the same home on several portals: same kind, zip, rounded m² and price within 3 %."""
    groups: dict[tuple[str, str, int], list[str]] = {}
    for key, r in offers.items():
        r.pop("same_as", None)
        sig = _sig(r)
        if sig and r.get("active"):
            groups.setdefault(sig, []).append(key)
    for keys in groups.values():
        if len(keys) < 2:
            continue
        for k in keys:
            mates = [
                m
                for m in keys
                if m != k
                and offers[m]["source"] != offers[k]["source"]
                and abs(offers[m]["price"] - offers[k]["price"]) <= 0.03 * offers[k]["price"]
            ]
            if mates:
                offers[k]["same_as"] = sorted(mates)
