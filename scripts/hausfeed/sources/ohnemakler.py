"""ohne-makler.net – private sales only; ``?page=N`` pagination."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from hausfeed.core import Kind, Offer, Page, clean_location, in_area, parse_area, parse_price, squash

BASE = "https://www.ohne-makler.net"
PLACES = ["bonn", "wachtberg"]
SLUGS: dict[Kind, str] = {"flat": "wohnung-kaufen", "house": "haus-kaufen"}
MAX_PAGES = 15


def _page_of(url: str) -> int:
    m = re.search(r"[?&]page=(\d+)", url)
    return int(m.group(1)) if m else 1


def _card(link: LexborNode) -> LexborNode:
    node = link
    for _ in range(8):
        parent = node.parent
        if parent is None or len(parent.text(strip=True)) > 700:
            break
        ids = {a.attributes.get("href") for a in parent.css('a[href^="/immobilie/"]')}
        if len({h for h in ids if h and re.fullmatch(r"/immobilie/\d+/", h)}) > 1:
            break
        node = parent
    return node


class OhneMakler:
    name = "ohnemakler"
    label = "ohne-makler"

    def seeds(self) -> list[str]:
        return [f"{BASE}/immobilien/{SLUGS[k]}/nordrhein-westfalen/{p}/" for k in SLUGS for p in PLACES]

    def parse(self, html: str, url: str) -> Page:
        tree = LexborHTMLParser(html)
        kind: Kind = "house" if "/haus-kaufen/" in url else "flat"
        page = Page()
        seen: set[str] = set()
        cards = 0
        for a in tree.css('a[href^="/immobilie/"]'):
            href = a.attributes.get("href") or ""
            m = re.fullmatch(r"/immobilie/(\d+)/", href)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            cards += 1
            card = _card(a)
            imgs = [i.attributes.get("src") or i.attributes.get("data-src") or "" for i in card.css("img")]
            for junk in card.css("svg, script, style"):
                junk.decompose()
            lines = [x.strip() for x in card.text(separator="\n", strip=True).split("\n") if x.strip()]
            price_line = next((x for x in lines if x.endswith("€") and "Monatsrate" not in x), "")
            loc_i = next((i for i, x in enumerate(lines) if re.match(r"^5\d{4}\b", x)), None)
            if loc_i is None:
                continue
            loc = lines[loc_i]
            if loc_i + 1 < len(lines) and lines[loc_i + 1].startswith("("):  # "53179 Bonn" + "(Lannesdorf)"
                loc += " " + lines[loc_i + 1]
            zip_code, district = clean_location(loc)
            if not in_area(zip_code):
                continue
            title = lines[loc_i - 1] if loc_i > 0 else ""
            after = lines[loc_i + 1 :]
            rooms_txt = next((x for x in after if re.fullmatch(r"\d+(,\d)?", x)), None)
            area_txt = next((x for x in after if x.endswith("m²")), "")
            energy = next((x for x in after if re.fullmatch(r"A\+?|[B-H]", x)), None)
            page.offers.append(
                Offer(
                    source=self.name,
                    source_id=m.group(1),
                    url=urljoin(BASE, href),
                    kind=kind,
                    title=squash(title),
                    price=parse_price(price_line),
                    size_m2=parse_area(area_txt),
                    rooms=float(rooms_txt.replace(",", ".")) if rooms_txt else None,
                    zip=zip_code,
                    district=district,
                    energy_class=energy,
                    image=next((i for i in imgs if "media.ohne-makler.net" in i), None),
                    seller="private",
                )
            )
        n = _page_of(url)
        if cards and n < MAX_PAGES:
            base = re.sub(r"[?&]page=\d+", "", url)
            page.follow.append(f"{base}?page={n + 1}")
        return page
