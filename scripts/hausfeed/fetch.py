"""HTTP side of the feed: a polite breadth-first crawl of one source."""

from __future__ import annotations

import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from hausfeed.core import Offer, Source

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9,en;q=0.8", "Accept": "text/html"}

Getter = Callable[[str], str]


@dataclass(slots=True)
class CrawlResult:
    source: str
    offers: list[Offer] = field(default_factory=list)
    requests: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """A run counts as complete only if every seed page loaded; otherwise nothing is marked gone."""
        return self.requests > 0 and not any(e.startswith("seed") for e in self.errors)


def http_getter(client: httpx.Client, delay: float) -> Getter:
    def get(url: str) -> str:
        time.sleep(delay * (0.75 + random.random() / 2))
        r = client.get(url)
        r.raise_for_status()
        return r.text

    return get


def crawl(source: Source, get: Getter, max_requests: int = 150) -> CrawlResult:
    res = CrawlResult(source=source.name)
    seeds = source.seeds()
    queue: deque[str] = deque(seeds)
    seen: set[str] = set(seeds)
    found: dict[str, Offer] = {}
    while queue and res.requests < max_requests:
        url = queue.popleft()
        res.requests += 1
        try:
            html = get(url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404 and url not in seeds:
                continue  # paged past the last result page
            res.errors.append(f"{'seed' if url in seeds else 'page'} {url}: HTTP {e.response.status_code}")
            continue
        except Exception as e:  # noqa: BLE001 – any failure is recorded, the crawl continues
            res.errors.append(f"{'seed' if url in seeds else 'page'} {url}: {type(e).__name__} {str(e)[:120]}")
            continue
        page = source.parse(html, url)
        for o in page.offers:
            found.setdefault(o.key, o)
        for nxt in page.follow:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    res.offers = list(found.values())
    return res
