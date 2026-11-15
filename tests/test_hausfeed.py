"""Tests for the offer feed. Fixtures are small synthetic pages that mirror each portal's markup."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hausfeed import store
from hausfeed.core import (
    Offer,
    Page,
    clean_location,
    de_number,
    in_area,
    parse_area,
    parse_price,
    parse_rooms,
    squash,
)
from hausfeed.fetch import CrawlResult, crawl
from hausfeed.sources.immowelt import Immowelt
from hausfeed.sources.kleinanzeigen import Kleinanzeigen, search_url
from hausfeed.sources.ohnemakler import OhneMakler

# --- helpers -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [("499.000 €", 499000.0), ("118,5 m²", 118.5), ("1.245,25", 1245.25), ("kein", None)],
)
def test_de_number(text: str, value: float | None) -> None:
    assert de_number(text) == value


def test_parsers() -> None:
    assert parse_price("549.000\xa0€ VB") == 549000
    assert parse_price("Preis auf Anfrage") is None
    assert parse_area("5 Zimmer · 165 m² · 429 m² Grundstück") == 165
    assert parse_rooms("4,5 Zimmer") == 4.5
    assert parse_rooms("215 m² · 9 Zi.") == 9


@pytest.mark.parametrize(
    ("raw", "zip_code", "district"),
    [
        ("Breite Str. 68, Zentrum, Bonn (53111)", "53111", "Zentrum"),
        ("Mehlem, Bonn (53179)", "53179", "Mehlem"),
        ("53125 Brüser Berg", "53125", "Brüser Berg"),
        ("53179 Bonn (Lannesdorf)", "53179", "Lannesdorf"),
        ("53343 Wachtberg-Niederbachem", "53343", "Wachtberg"),
        ("Röttgener Straße 12, Ippendorf, Bonn (53127)", "53127", "Ippendorf"),
        ("53111 Bonn", "53111", None),
    ],
)
def test_clean_location_drops_streets(raw: str, zip_code: str, district: str | None) -> None:
    assert clean_location(raw) == (zip_code, district)


def test_street_named_after_district_is_not_used() -> None:
    # "Röttgener Straße" must not map to Röttgen when the district part says otherwise.
    assert clean_location("Mehlemer Str. 3, Friesdorf, Bonn (53175)")[1] == "Friesdorf"


@pytest.mark.parametrize(
    "text",
    [
        "Wohn- und Geschäftshaus in der Rheingasse 4 mit Mieterträgen",
        "Ihre Beraterin: Frau Marie Muster | Objektnummer K1",
        "Ruf an: 0178 123 4567 oder mail@example.org",
        "Haus Am Hang 3a mit Garten",
    ],
)
def test_squash_scrubs_personal_bits(text: str) -> None:
    out = squash(text)
    for bad in ["Rheingasse 4", "Marie", "Muster", "4567", "example", "Hang 3a"]:
        assert bad not in out


def test_in_area() -> None:
    assert in_area("53127") and in_area("53229") and in_area("53343")
    assert not in_area("53757") and not in_area(None)


# --- Immowelt ------------------------------------------------------------------------------------

IMMOWELT = """
<div data-testid="serp-core-classified-card-testid">
  <a data-testid="card-mfe-covering-link-testid" href="https://www.immowelt.de/expose/abc-123"
     title="Haus zum Kauf - Bonn - 549.000 € - 5 Zimmer, 165 m²"></a>
  <img src="https://mms.immowelt.de/a/b.jpg?h=50">
  <img src="https://mms.immowelt.de/c/d.jpg?w=626&h=470">
  <span data-testid="cardmfe-agency-publisher-xl-test-id">Frau Erika Muster</span>
  <div data-testid="cardmfe-description-box-text-test-id">
    <div data-testid="cardmfe-price-testid"><span>549.000&nbsp;€</span><span>3.327&nbsp;€/m²</span></div>
    <div>Einfamilienhaus zum Kauf</div>
    <div>5 Zimmer · 165 m² · 429 m² Grundstück</div>
    <span data-testid="card-mfe-energy-performance-class">D</span>
    <div data-testid="cardmfe-description-box-address">Musterweg 7, Mehlem, Bonn (53179)</div>
  </div>
  <div data-testid="cardmfe-description-text-test-id">Massive Doppelhaushälfte aus 1986.</div>
</div>
<div data-testid="serp-core-classified-card-testid">
  <a data-testid="card-mfe-covering-link-testid" href="/expose/far-away"></a>
  <div data-testid="cardmfe-description-box-address">Sankt Augustin (53757)</div>
</div>
"""


def test_immowelt_card() -> None:
    url = "https://www.immowelt.de/suche/kaufen/haus/nordrhein-westfalen/bonn-53111/ad08de2178"
    page = Immowelt().parse(IMMOWELT, url)
    assert len(page.offers) == 1
    o = page.offers[0]
    assert (o.source_id, o.kind, o.price, o.size_m2, o.rooms, o.plot_m2) == ("abc-123", "house", 549000, 165, 5, 429)
    assert (o.zip, o.district, o.energy_class) == ("53179", "Mehlem", "D")
    assert o.image == "https://mms.immowelt.de/c/d.jpg?w=480&h=360"
    assert o.title == "Einfamilienhaus"
    # No street, no contact name anywhere in the stored record.
    blob = str(o.to_dict())
    assert "Musterweg" not in blob and "Erika" not in blob


# --- Kleinanzeigen -------------------------------------------------------------------------------

KLEINANZEIGEN = """
<ul>
<li><article data-adid="111" data-href="/s-anzeige/schoene-wohnung/111-196-1">
  <img src="https://img.kleinanzeigen.de/x.jpg">
  <div>53127 Ippendorf</div><h2>Schöne 4-Zimmer-Wohnung</h2><p>Text</p>
  <p>118 m² · 4 Zi.</p><p>499.000 €</p><p>Muster Immobilien GmbH</p>
</article></li>
<li><article data-adid="222" data-href="/s-anzeige/privat/222-196-1">
  <div>53175 Friesdorf</div><h2>Von privat: Maisonette</h2>
  <p>134 m² · 5 Zi.</p><p>498.000 € VB</p>
</article></li>
<li><article data-adid="333" data-href="/s-anzeige/weit/333-196-1"><div>53842 Troisdorf</div><p>1 €</p></article></li>
</ul>
<a href="/s-wohnung-kaufen/bonn/seite:2/c196l1038">2</a>
"""


def test_kleinanzeigen_cards_and_paging() -> None:
    url = search_url("flat", "bonn")
    page = Kleinanzeigen().parse(KLEINANZEIGEN, url)
    assert [o.source_id for o in page.offers] == ["111", "222"]
    a, b = page.offers
    assert (a.price, a.size_m2, a.rooms, a.district, a.seller) == (499000, 118, 4, "Ippendorf", "agent")
    assert (b.price, b.seller, b.image) == (498000, "private", None)
    assert page.follow == ["https://www.kleinanzeigen.de/s-wohnung-kaufen/bonn/seite:2/c196l1038"]
    assert "Muster" not in str(a.to_dict())


# --- ohne-makler ---------------------------------------------------------------------------------

OHNEMAKLER = """
<div class="grid">
 <div class="col-span-12"><a href="/immobilie/515530/"><img src="https://media.ohne-makler.net/p.jpg"></a>
  <div>465.000 €</div><div>Von Privat: 2,5 Zimmer in Lengsdorf</div><div>53127 Bonn-Lengsdorf</div>
  <div>2,5</div><div>88m²</div><div>E</div><div>Monatsrate ca.</div></div>
 <div class="col-span-12"><a href="/immobilie/9/"></a><div>1 €</div><div>Woanders</div><div>50667 Köln</div></div>
</div>
"""


def test_ohnemakler_cards_and_paging() -> None:
    url = "https://www.ohne-makler.net/immobilien/wohnung-kaufen/nordrhein-westfalen/bonn/"
    page = OhneMakler().parse(OHNEMAKLER, url)
    assert len(page.offers) == 1
    o = page.offers[0]
    assert (o.price, o.rooms, o.size_m2, o.district, o.energy_class, o.seller) == (
        465000,
        2.5,
        88,
        "Lengsdorf",
        "E",
        "private",
    )
    assert page.follow == [url + "?page=2"]


# --- crawl + store -------------------------------------------------------------------------------


def _offer(source_id: str, price: int, source: str = "kleinanzeigen", size: float = 120) -> Offer:
    return Offer(source, source_id, f"https://x/{source_id}", "flat", "t", price, size, 4, "53127", "Ippendorf")


class FakeSource:
    name = "kleinanzeigen"
    label = "Fake"

    def seeds(self) -> list[str]:
        return ["seed"]

    def parse(self, html: str, url: str) -> Page:
        return Page(offers=[_offer(html, 400000)], follow=["p2"] if url == "seed" else [])


def test_crawl_follows_and_records_errors() -> None:
    pages = {"seed": "a", "p2": "b"}
    res = crawl(FakeSource(), lambda u: pages[u])
    assert sorted(o.source_id for o in res.offers) == ["a", "b"] and res.ok

    def boom(u: str) -> str:
        raise RuntimeError("blocked")

    bad = crawl(FakeSource(), boom)
    assert not bad.ok and bad.errors[0].startswith("seed")


def test_merge_tracks_new_price_change_and_gone() -> None:
    feed = store.load(Path("/nonexistent"))
    cfg: dict[str, object] = {"min_size_m2": 70}
    r1 = CrawlResult("kleinanzeigen", [_offer("a", 500000), _offer("b", 450000), _offer("tiny", 1, size=30)], 1)
    s1 = store.merge(feed, [r1], "2026-11-15", cfg)
    assert s1["new"] == 2 and "kleinanzeigen:tiny" not in feed["offers"]

    r2 = CrawlResult("kleinanzeigen", [_offer("a", 480000)], 1)
    s2 = store.merge(feed, [r2], "2026-11-16", cfg)
    a, b = feed["offers"]["kleinanzeigen:a"], feed["offers"]["kleinanzeigen:b"]
    assert s2 == {"new": 0, "price_changed": 1, "gone": 1, "seen": 1}
    assert a["price_history"] == [["2026-11-15", 500000], ["2026-11-16", 480000]]
    assert b["active"] is False and b["gone"] == "2026-11-16"

    # A failed run must not mark anything gone.
    failed = CrawlResult("kleinanzeigen", [], 1, ["seed x: blocked"])
    store.merge(feed, [failed], "2026-11-17", cfg)
    assert feed["offers"]["kleinanzeigen:a"]["active"] is True


def test_duplicates_across_portals() -> None:
    feed = store.load(Path("/nonexistent"))
    r1 = CrawlResult("kleinanzeigen", [_offer("a", 500000)], 1)
    r2 = CrawlResult("immowelt", [_offer("z", 505000, source="immowelt")], 1)
    store.merge(feed, [r1, r2], "2026-11-15", {})
    assert feed["offers"]["kleinanzeigen:a"]["same_as"] == ["immowelt:z"]


# --- amenities (OpenStreetMap summary) -----------------------------------------------------------


def test_amenities_summary() -> None:
    import amenities

    centre = (50.7155, 7.0645)
    pois = [
        {"type": "node", "lat": 50.7160, "lon": 7.0645, "tags": {"shop": "supermarket", "name": "Markt A"}},
        {"type": "node", "lat": 50.7300, "lon": 7.0645, "tags": {"shop": "supermarket", "name": "Markt B"}},
        {
            "type": "way",
            "center": {"lat": 50.7180, "lon": 7.0645},
            "tags": {"amenity": "school", "name": "KGS Grundschule"},
        },
        {"type": "node", "lat": 50.7155, "lon": 7.0700, "tags": {"amenity": "school", "name": "Städt. Gymnasium"}},
        {"type": "node", "lat": 50.7155, "lon": 7.0650, "tags": {"highway": "bus_stop"}},
        {"type": "node", "lat": 50.7200, "lon": 7.0645, "tags": {"railway": "tram_stop", "name": "Stop"}},
    ]
    # A ~1 km² square of forest starting ~330 m south of the centre, and a tiny copse right next to it.
    sq = [(50.7125, 7.06), (50.7125, 7.074), (50.7035, 7.074), (50.7035, 7.06), (50.7125, 7.06)]
    tiny = [(50.7156, 7.0646), (50.7156, 7.0647), (50.7157, 7.0647), (50.7156, 7.0646)]
    greens = [
        {
            "type": "way",
            "tags": {"landuse": "forest", "name": "Kottenforst"},
            "geometry": [{"lat": a, "lon": b} for a, b in sq],
        },
        {"type": "way", "tags": {"natural": "wood"}, "geometry": [{"lat": a, "lon": b} for a, b in tiny]},
    ]
    s = amenities.summarise(centre, pois, greens)
    assert s["supermarket"] == {"m": 56, "name": "Markt A"} and s["supermarkets_1km"] == 1
    assert s["primary_school"]["name"] == "KGS Grundschule" and s["secondary_school"]["name"] == "Städt. Gymnasium"
    assert s["forest"]["name"] == "Kottenforst" and 300 < s["forest"]["m"] < 360  # the copse is ignored
    assert s["rail"]["m"] == 500 and s["bus_stops_500m"] == 1
    assert 2 < s["hbf_km"] < 4
    inside = amenities.ring_distance((50.708, 7.067), sq)
    assert inside == 0.0
