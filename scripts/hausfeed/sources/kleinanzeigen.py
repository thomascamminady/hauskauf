"""kleinanzeigen.de – server-rendered result pages with ``/seite:N/`` pagination (25 ads per page)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from hausfeed.core import Kind, Offer, Page, clean_location, in_area, parse_area, parse_price, parse_rooms, squash

BASE = "https://www.kleinanzeigen.de"
# (slug, location id) – ids from /s-ort-empfehlungen.json
PLACES = {"bonn": 1038, "wachtberg": 1661}
CATEGORIES: dict[Kind, tuple[str, int]] = {"flat": ("wohnung-kaufen", 196), "house": ("haus-kaufen", 208)}
MAX_PAGES = 40


def search_url(kind: Kind, place: str, page: int = 1) -> str:
    slug, cat = CATEGORIES[kind]
    seite = f"seite:{page}/" if page > 1 else ""
    return f"{BASE}/s-{slug}/{place}/{seite}c{cat}l{PLACES[place]}"


def _page_of(url: str) -> int:
    m = re.search(r"/seite:(\d+)/", url)
    return int(m.group(1)) if m else 1


class Kleinanzeigen:
    name = "kleinanzeigen"
    label = "Kleinanzeigen"

    def seeds(self) -> list[str]:
        return [search_url(k, p) for k in CATEGORIES for p in PLACES]

    def parse(self, html: str, url: str) -> Page:
        tree = LexborHTMLParser(html)
        kind: Kind = "house" if "/s-haus-kaufen/" in url else "flat"
        page = Page()
        for art in tree.css("article[data-adid]"):
            ad_id = art.attributes.get("data-adid") or ""
            href = art.attributes.get("data-href") or ""
            if not ad_id or not href:
                continue
            for junk in art.css("svg, script, style"):
                junk.decompose()
            lines = [x.strip() for x in art.text(separator="\n", strip=True).split("\n") if x.strip()]
            loc = next((x for x in lines if re.match(r"^5\d{4}\b", x)), "")
            zip_code, district = clean_location(loc)
            if not in_area(zip_code):
                continue
            h = art.css_first("h2, h3")
            title = h.text(strip=True) if h else ""
            facts = next((x for x in lines if "m²" in x and ("Zi." in x or "Zimmer" in x)), "")
            price_i = next((i for i, x in enumerate(lines) if x.endswith(("€", "€ VB"))), None)
            price = parse_price(lines[price_i]) if price_i is not None else None
            # Commercial ads show the company name after the price; private ads end with the price.
            seller = None
            if price_i is not None:
                seller = "agent" if price_i + 1 < len(lines) else "private"
            img = art.css_first("img")
            page.offers.append(
                Offer(
                    source=self.name,
                    source_id=ad_id,
                    url=urljoin(BASE, href),
                    kind=kind,
                    title=squash(title),
                    price=price,
                    size_m2=parse_area(facts),
                    rooms=parse_rooms(facts),
                    zip=zip_code,
                    district=district,
                    image=img.attributes.get("src") if img else None,
                    seller=seller,
                )
            )
        n = _page_of(url)
        if tree.css("article[data-adid]") and n < MAX_PAGES:
            nxt = tree.css_first(f'a[href*="/seite:{n + 1}/"]')
            if nxt is not None:
                page.follow.append(urljoin(BASE, nxt.attributes.get("href") or ""))
        return page
