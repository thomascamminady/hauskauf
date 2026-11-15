"""immowelt.de – server-rendered search pages.

Only the first ~32 results of a search URL are rendered on the server, and ``?page=`` is ignored. To cover
more, the crawler follows the portal's own facet links on the city page: neighbourhoods ("Top Stadtteile")
and room counts ("…nach Anzahl der Zimmer"). Each of those again shows its first ~32 results.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from hausfeed.core import (
    Kind,
    Offer,
    Page,
    clean_location,
    in_area,
    is_new_build,
    parse_area,
    parse_price,
    parse_rooms,
    squash,
)

BASE = "https://www.immowelt.de"
PLACES = {
    "bonn": "nordrhein-westfalen/bonn-53111/ad08de2178",
    "wachtberg": "nordrhein-westfalen/wachtberg-53343/ad08de2275",
}
KINDS: dict[str, Kind] = {"wohnung": "flat", "haus": "house"}


def _kind_from_url(url: str) -> Kind:
    m = re.search(r"/suche/kaufen/(wohnung|haus)/", url)
    return KINDS[m.group(1)] if m else "flat"


def _seo_links(html: str) -> list[str]:
    m = re.search(r'window\["__UFRN_FETCHER__"\]=JSON\.parse\((".*?")\);?</script>', html, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(json.loads(m.group(1)))
        boxes = data["data"]["mfe_seom_resolver_serp_iwt"]["linkboxData"]["seoLinkBoxes"]
    except (KeyError, ValueError, TypeError):
        return []
    urls: list[str] = []
    for box in boxes:
        title = str(box.get("title", ""))
        if "Stadtteile" in title or "Zimmer" in title:
            urls += [str(link["url"]) for link in box.get("links", []) if link.get("url")]
    return urls


class Immowelt:
    name = "immowelt"
    label = "Immowelt"

    def seeds(self) -> list[str]:
        return [f"{BASE}/suche/kaufen/{k}/{p}" for k in KINDS for p in PLACES.values()]

    def parse(self, html: str, url: str) -> Page:
        tree = LexborHTMLParser(html)
        kind = _kind_from_url(url)
        page = Page()
        for card in tree.css('[data-testid="serp-core-classified-card-testid"]'):
            link = card.css_first('[data-testid="card-mfe-covering-link-testid"]')
            href = link.attributes.get("href") if link else None
            if not href:
                continue
            m = re.search(r"/expose/([\w-]+)", href)
            if not m:
                continue
            addr = card.css_first('[data-testid="cardmfe-description-box-address"]')
            zip_code, district = clean_location(addr.text(strip=True) if addr else "")
            if not in_area(zip_code):
                continue
            box = card.css_first('[data-testid="cardmfe-description-box-text-test-id"]')
            box_text = box.text(separator=" | ", strip=True) if box else ""
            price_el = card.css_first('[data-testid="cardmfe-price-testid"]')
            price = parse_price(price_el.text(separator=" ", strip=True).split("|")[0]) if price_el else None
            facts = next((p for p in box_text.split(" | ") if "m²" in p and "€" not in p), "")
            plot_m = re.search(r"([\d.,]+)\s*m²\s*Grundstück", facts.replace("\xa0", " "))
            energy = card.css_first('[data-testid="card-mfe-energy-performance-class"]')
            type_label = next((p for p in box_text.split(" | ") if "zum Kauf" in p), "")
            image = None
            for img in card.css("img"):
                src = img.attributes.get("src") or ""
                if "mms.immowelt.de" in src and "w=" in src:
                    image = re.sub(r"\?.*$", "?w=480&h=360", src)
                    break
            page.offers.append(
                Offer(
                    source=self.name,
                    source_id=m.group(1),
                    url=urljoin(BASE, href),
                    kind=kind,
                    # Only the type label: the description excerpt can name streets or agents.
                    title=squash(type_label.replace(" zum Kauf", "") or ("Haus" if kind == "house" else "Wohnung")),
                    price=price,
                    size_m2=parse_area(facts.split("·")[1]) if facts.count("·") >= 1 else parse_area(facts),
                    rooms=parse_rooms(facts),
                    zip=zip_code,
                    district=district,
                    plot_m2=float(plot_m.group(1).replace(".", "").replace(",", ".")) if plot_m else None,
                    energy_class=energy.text(strip=True) or None if energy else None,
                    image=image,
                    seller=None,
                    new_build=is_new_build(card.text(separator=" ", strip=True)),
                )
            )
        # Facet links only from top-level city pages (keeps the crawl bounded).
        if url.rstrip("/") in self.seeds():
            page.follow = [u for u in _seo_links(html) if _kind_from_url(u) == kind]
        return page
