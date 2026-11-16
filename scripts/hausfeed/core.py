"""Shared types and helpers for the offer feed.

The feed separates IO from parsing:

* A ``Source`` turns a search into seed URLs and parses one fetched HTML page into a ``Page``
  (offers found + further URLs to follow). Parsing is pure and tested against fixtures.
* ``fetch.crawl`` does the HTTP work (polite delay, request cap) and calls ``Source.parse``.
* ``store.merge`` folds a run's offers into ``data/feed.json`` (first/last seen, price history, gone).

Offers carry listing facts only. Street addresses and contact names are never stored: the location
is reduced to postcode + district before an ``Offer`` is created.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

Kind = Literal["flat", "house"]
Seller = Literal["private", "agent"]


@dataclass(frozen=True, slots=True)
class Offer:
    """One listing as seen on one portal, normalised."""

    source: str
    source_id: str
    url: str
    kind: Kind
    title: str
    price: int | None
    size_m2: float | None
    rooms: float | None
    zip: str | None
    district: str | None
    plot_m2: float | None = None
    energy_class: str | None = None
    image: str | None = None
    seller: Seller | None = None
    new_build: bool = False

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Page:
    """Result of parsing one fetched page."""

    offers: list[Offer] = field(default_factory=list)
    follow: list[str] = field(default_factory=list)


class Source(Protocol):
    """A listing portal. Implementations live in ``hausfeed.sources``."""

    name: str
    label: str

    def seeds(self) -> list[str]:
        """Start URLs for one run (all kinds and places)."""
        ...

    def parse(self, html: str, url: str) -> Page:
        """Parse one page. Must not do IO."""
        ...


# --- number parsing ---------------------------------------------------------------------------

_NUM = r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?"


def de_number(text: str) -> float | None:
    """Parse the first German-formatted number ("1.245,5") in ``text``."""
    m = re.search(_NUM, text.replace("\xa0", " "))
    if not m:
        return None
    whole = m.group(1).replace(".", "")
    return float(f"{whole}.{m.group(2)}") if m.group(2) else float(whole)


def parse_price(text: str) -> int | None:
    """'499.000 € VB' → 499000. Returns None for 'auf Anfrage' or implausible values."""
    if "€" not in text and "EUR" not in text:
        return None
    v = de_number(text)
    if v is None or v < 10_000:
        return None
    return int(v)


def parse_area(text: str, unit_suffix: str = "m²") -> float | None:
    """First number directly followed by m² (e.g. '118,5 m²')."""
    m = re.search(_NUM + r"\s*" + re.escape(unit_suffix), text.replace("\xa0", " "))
    if not m:
        return None
    return de_number(m.group(0))


def parse_rooms(text: str) -> float | None:
    """'4,5 Zimmer' / '4 Zi.' → 4.5 / 4."""
    m = re.search(r"(\d+(?:,\d)?)\s*(?:Zimmer|Zi\.)", text)
    return float(m.group(1).replace(",", ".")) if m else None


# --- location ---------------------------------------------------------------------------------

# Names that appear on portals, mapped to the district names used in data/market.json.
DISTRICT_ALIASES: dict[str, str] = {
    "Ippendorf": "Ippendorf",
    "Venusberg": "Venusberg",
    "Röttgen": "Röttgen",
    "Ückesdorf": "Ückesdorf",
    "Uckesdorf": "Ückesdorf",
    "Poppelsdorf": "Poppelsdorf",
    "Kessenich": "Kessenich",
    "Südstadt": "Südstadt",
    "Zentrum": "Zentrum",
    "Bonn-Zentrum": "Zentrum",
    "Altstadt": "Zentrum",
    "Weststadt": "Weststadt",
    "Endenich": "Endenich",
    "Dottendorf": "Dottendorf",
    "Gronau": "Gronau",
    "Lengsdorf": "Lengsdorf",
    "Duisdorf": "Duisdorf",
    "Brüser Berg": "Brüser Berg",
    "Hardtberg": "Duisdorf",
    "Schweinheim": "Schweinheim",
    "Friesdorf": "Friesdorf",
    "Alt-Godesberg": "Alt-Godesberg",
    "Godesberg-Villenviertel": "Godesberg-Villenviertel",
    "Villenviertel": "Godesberg-Villenviertel",
    "Plittersdorf": "Plittersdorf",
    "Mehlem": "Mehlem",
    "Heiderhof": "Heiderhof",
    "Muffendorf": "Muffendorf",
    "Lannesdorf": "Lannesdorf",
    "Rüngsdorf": "Rüngsdorf",
    "Rungsdorf": "Rüngsdorf",
    "Pennenfeld": "Pennenfeld",
    "Beuel": "Beuel-Mitte",
    "Beuel-Mitte": "Beuel-Mitte",
    "Holzlar": "Holzlar",
    "Wachtberg": "Wachtberg",
    "Alfter": "Alfter",
    # Wachtberg villages
    "Adendorf": "Wachtberg",
    "Arzdorf": "Wachtberg",
    "Berkum": "Wachtberg",
    "Fritzdorf": "Wachtberg",
    "Gimmersdorf": "Wachtberg",
    "Holzem": "Wachtberg",
    "Ließem": "Wachtberg",
    "Niederbachem": "Wachtberg",
    "Oberbachem": "Wachtberg",
    "Pech": "Wachtberg",
    "Villiprott": "Wachtberg",
    "Werthhoven": "Wachtberg",
    "Züllighoven": "Wachtberg",
}

_STREET = re.compile(r"(stra(ß|ss)e|str\.|weg\b|allee|platz|gasse|ring\b|ufer|chaussee|\d)", re.IGNORECASE)


def in_area(zip_code: str | None) -> bool:
    """Bonn (531xx, 532xx) and Wachtberg (53343)."""
    if not zip_code:
        return False
    return zip_code.startswith(("531", "532")) or zip_code == "53343"


def zip_area(zip_code: str | None) -> str:
    """Coarse area name for a postcode, used only for display when no district matched."""
    if not zip_code:
        return "Bonn"
    areas = {
        ("53173", "53175", "53177", "53179"): "Bad Godesberg",
        ("53225", "53227", "53229"): "Beuel",
        ("53123", "53125"): "Hardtberg",
        ("53117", "53119"): "Bonn-Nord",
        ("53343",): "Wachtberg",
    }
    return next((name for zips, name in areas.items() if zip_code in zips), "Bonn")


def match_district(text: str) -> str | None:
    """Longest known district name contained in ``text``."""
    best: tuple[int, str] | None = None
    for alias, district in DISTRICT_ALIASES.items():
        hit = re.search(rf"(?<![\wäöüß]){re.escape(alias)}(?![\wäöüß])", text)
        if hit and (best is None or len(alias) > best[0]):
            best = (len(alias), district)
    return best[1] if best else None


def clean_location(raw: str) -> tuple[str | None, str | None]:
    """Reduce a portal location string to (zip, district); street parts are dropped first."""
    raw = raw.replace("\xa0", " ").strip()
    zm = re.search(r"\b(5\d{4})\b", raw)
    zip_code = zm.group(1) if zm else None
    parts = [p.strip() for p in re.split(r"[,()]", raw) if p.strip()]
    # Drop parts that look like a street or a house number (but keep the bare zip code).
    safe = [p for p in parts if not _STREET.search(re.sub(r"\b5\d{4}\b", "", p))]
    return zip_code, match_district(" ".join(safe))


_SCRUB = [
    # street + house number ("Rheingasse 4", "Breite Str. 68", "Am Hang 3a")
    re.compile(
        r"\b[A-ZÄÖÜ][\wäöüß.-]*(?:stra(?:ß|ss)e|str\.|weg|allee|gasse|platz|ring|ufer|pfad|chaussee)\s*\d+\s*[a-z]?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:Am|An der|Im|In der|Auf der|Zum|Zur)\s+[A-ZÄÖÜ][\wäöüß-]+\s+\d+\s*[a-z]?\b"),
    # salutation + name, phone numbers, e-mail addresses
    re.compile(r"\b(?:Herr|Frau|Hr\.|Fr\.)\s+(?:Dr\.\s+)?[A-ZÄÖÜ][\wäöüß-]+(?:\s+[A-ZÄÖÜ][\wäöüß-]+)?"),
    re.compile(r"(?:\+49|\b0)[\d /-]{7,}\d"),
    re.compile(r"\S+@\S+"),
]


def scrub(text: str) -> str:
    """Remove street addresses, names after a salutation, phone numbers and e-mails from free text."""
    for pat in _SCRUB:
        text = pat.sub("…", text)
    return text


_NEW_BUILD = re.compile(
    r"neubau|projektiert|bauprojekt|bauvorhaben|bauträger|\bentsteht\b|\bentstehen\b|im bau\b|baubeginn|rohbau"
    r"|fertigstellung|bezugsfertig\w* (?:ab |im |voraussichtlich )?\w* ?20(?:2[6-9]|3\d)|vorvermarktung|baugenehmigung"
    r"|noch zu (?:errichten|bauen)|wird (?:neu )?errichtet|hausbau|bauen sie|ihr (?:neues )?traumhaus|livinghaus"
    r"|\berstbezug\b(?! nach)"
    r"|doppelhauspartner|partner gesucht|bereits reserviert|individuell geplant|maßgeschneidert|hanse ?haus|designhaus"
    r"|schwörer|kampa|okal|streif|viebrockhaus|town ?& ?country|massa ?haus|fertighaus",
    re.IGNORECASE,
)


def is_new_build(text: str) -> bool:
    """Off-plan or still-to-be-built offers (a renovated 'Erstbezug nach Sanierung' is not one)."""
    return bool(_NEW_BUILD.search(text))


def squash(text: str, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", scrub(text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
