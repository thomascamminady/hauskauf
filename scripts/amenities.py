# /// script
# requires-python = ">=3.12"
# dependencies = ["fire", "httpx"]
# ///
"""Neighbourhood facts per district centre from OpenStreetMap (Overpass API) → data/amenities.json.

Distances are measured from the approximate district centre in data/market.json, not from any home
(homes are only published at district level). Re-run every few months:

    uv run scripts/amenities.py                 # all districts
    uv run scripts/amenities.py --only=Ippendorf,Röttgen
"""

from __future__ import annotations

import itertools
import json
import math
import time
from datetime import date
from pathlib import Path
from typing import Any

import fire
import httpx

ROOT = Path(__file__).resolve().parent.parent
MIRRORS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {"User-Agent": "hauskauf-research/0.1 (district amenity summary)"}
RADIUS = 2500  # metres around the district centre
HBF = (50.7320, 7.0970)  # Bonn Hauptbahnhof
GODESBERG = (50.6840, 7.1580)  # Bad Godesberg station

POI_QUERY = """
[out:json][timeout:60];
(
  nwr(around:{r},{lat},{lon})[shop=supermarket];
  nwr(around:{r},{lat},{lon})[amenity=school];
  nwr(around:{r},{lat},{lon})[amenity=kindergarten];
  nwr(around:{r},{lat},{lon})[amenity=pharmacy];
  nwr(around:{r},{lat},{lon})[amenity=doctors];
  nwr(around:{r},{lat},{lon})[amenity~"^(cafe|restaurant)$"];
  node(around:{r},{lat},{lon})[railway~"^(station|halt|tram_stop)$"];
  node(around:{r},{lat},{lon})[highway=bus_stop];
);
out tags center;
"""
GREEN_QUERY = """
[out:json][timeout:90];
(
  way(around:{r},{lat},{lon})[landuse=forest];
  way(around:{r},{lat},{lon})[natural=wood];
  relation(around:{r},{lat},{lon})[landuse=forest];
  relation(around:{r},{lat},{lon})[natural=wood];
  way(around:{r},{lat},{lon})[leisure=park];
);
out tags geom({s},{w},{n},{e});
"""
MIN_FOREST_HA = 5.0  # ignore small copses: only woodland of roughly this size counts as "forest"


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance in metres."""
    r = 6_371_000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def point(el: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else None


def bbox(lat: float, lon: float, r: float) -> dict[str, float]:
    dlat = r / 111_320
    dlon = r / (111_320 * math.cos(math.radians(lat)))
    return {"s": lat - dlat, "n": lat + dlat, "w": lon - dlon, "e": lon + dlon}


def query(client: httpx.Client, q: str, attempts: int = 12) -> list[dict[str, Any]]:
    """POST to the mirrors in turn with growing pauses; Overpass is often overloaded."""
    last = ""
    for attempt in range(attempts):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            r = client.post(url, data={"data": q})
        except httpx.TransportError as e:
            last = f"{url}: {type(e).__name__}"
        else:
            if r.status_code == 200:
                return r.json()["elements"]
            last = f"{url}: HTTP {r.status_code}"
            if r.status_code not in (429, 502, 503, 504):
                r.raise_for_status()
        time.sleep(min(60, 5 * (attempt + 1)))
    raise RuntimeError(f"Overpass kept refusing ({last})")


def school_kind(tags: dict[str, str]) -> str:
    name = tags.get("name", "").lower()
    isced = tags.get("isced:level", "")
    if "grundschule" in name or isced in ("1", "0;1"):
        return "primary"
    if (
        any(k in name for k in ("gymnasium", "gesamtschule", "realschule", "sekundarschule", "hauptschule"))
        or "2" in isced
    ):
        return "secondary"
    return "other"


def ring_area_ha(coords: list[tuple[float, float]]) -> float:
    if len(coords) < 3:
        return 0.0
    lat0 = coords[0][0]
    xs = [(lon * 111_320 * math.cos(math.radians(lat0))) for _, lon in coords]
    ys = [lat * 111_320 for lat, _ in coords]
    a = sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(xs) - 1))
    return abs(a) / 2 / 10_000


def ring_distance(centre: tuple[float, float], ring: list[tuple[float, float]]) -> float:
    """Metres from ``centre`` to the nearest edge of ``ring`` (0 if inside a closed ring)."""
    lat0, lon0 = centre
    kx, ky = 111_320 * math.cos(math.radians(lat0)), 111_320
    pts = [((lon - lon0) * kx, (lat - lat0) * ky) for lat, lon in ring]
    best = min(math.hypot(x, y) for x, y in pts)
    inside = False
    for (x1, y1), (x2, y2) in itertools.pairwise(pts):
        dx, dy = x2 - x1, y2 - y1
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / seg))
        best = min(best, math.hypot(x1 + t * dx, y1 + t * dy))
        if (y1 > 0) != (y2 > 0) and 0 < x1 + (0 - y1) * dx / (dy or 1e-12):
            inside = not inside
    closed = len(ring) > 3 and ring[0] == ring[-1]
    return 0.0 if closed and inside else best


def nearest(items: list[tuple[float, str]]) -> dict[str, Any] | None:
    if not items:
        return None
    d, name = min(items)
    return {"m": round(d), "name": name}


def summarise(centre: tuple[float, float], pois: list[dict[str, Any]], greens: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[tuple[float, str]]] = {
        k: []
        for k in ("supermarket", "primary", "secondary", "kindergarten", "pharmacy", "doctors", "food", "rail", "bus")
    }
    for el in pois:
        p, tags = point(el), el.get("tags", {})
        if p is None:
            continue
        d, name = haversine(centre, p), tags.get("name", "")
        if tags.get("shop") == "supermarket":
            by["supermarket"].append((d, name))
        elif tags.get("amenity") == "school":
            kind = school_kind(tags)
            if kind in by:
                by[kind].append((d, name))
        elif tags.get("amenity") in ("kindergarten", "pharmacy", "doctors"):
            by[tags["amenity"]].append((d, name))
        elif tags.get("amenity") in ("cafe", "restaurant"):
            by["food"].append((d, name))
        elif tags.get("railway") in ("station", "halt", "tram_stop"):
            by["rail"].append((d, name))
        elif tags.get("highway") == "bus_stop":
            by["bus"].append((d, name))
    forest: list[tuple[float, str]] = []
    park: list[tuple[float, str]] = []
    for el in greens:
        tags = el.get("tags", {})
        rings: list[list[tuple[float, float]]] = []
        if el["type"] == "way" and el.get("geometry"):
            rings.append([(g["lat"], g["lon"]) for g in el["geometry"] if g])
        for m in el.get("members", []):
            if m.get("geometry"):
                rings.append([(g["lat"], g["lon"]) for g in m["geometry"] if g])
        rings = [r for r in rings if r]
        if not rings:
            continue
        d = min(ring_distance(centre, r) for r in rings)
        name = tags.get("name", "")
        if tags.get("leisure") == "park":
            park.append((d, name))
        elif el["type"] == "relation" or ring_area_ha(rings[0]) >= MIN_FOREST_HA:
            forest.append((d, name or "Wald"))
    near = lambda k, r: sum(1 for d, _ in by[k] if d <= r)
    return {
        "supermarket": nearest(by["supermarket"]),
        "supermarkets_1km": near("supermarket", 1000),
        "primary_school": nearest(by["primary"]),
        "secondary_school": nearest(by["secondary"]),
        "kindergarten": nearest(by["kindergarten"]),
        "kindergartens_1km": near("kindergarten", 1000),
        "pharmacy": nearest(by["pharmacy"]),
        "doctors_1km": near("doctors", 1000),
        "cafes_restaurants_1km": near("food", 1000),
        "rail": nearest(by["rail"]),
        "bus_stops_500m": near("bus", 500),
        "forest": nearest(forest),
        "park": nearest(park),
        "hbf_km": round(haversine(centre, HBF) / 1000, 1),
        "godesberg_km": round(haversine(centre, GODESBERG) / 1000, 1),
    }


def main(only: str | tuple[str, ...] = "", delay: float = 3.0, refresh: bool = False) -> None:
    """Fetch amenities for district centres in data/market.json.

    Args:
        only: comma-separated district names (default: all).
        delay: seconds between queries.
        refresh: re-fetch districts that are already in data/amenities.json.
    """
    names = [n for n in (",".join(only) if isinstance(only, tuple) else only).split(",") if n]
    market = json.loads((ROOT / "data" / "market.json").read_text(encoding="utf-8"))
    out_path = ROOT / "data" / "amenities.json"
    out: dict[str, Any] = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {"districts": {}}
    with httpx.Client(headers=HEADERS, timeout=150) as client:
        for name, d in market["districts"].items():
            if names and name not in names:
                continue
            if name in out["districts"] and not refresh and not names:
                continue
            lat, lon = d["lat"], d["lon"]
            try:
                pois = query(client, POI_QUERY.format(r=RADIUS, lat=lat, lon=lon))
                time.sleep(delay)
                greens = query(client, GREEN_QUERY.format(r=RADIUS, lat=lat, lon=lon, **bbox(lat, lon, RADIUS + 500)))
                time.sleep(delay)
            except RuntimeError as e:
                print(f"{name}: skipped – {e}", flush=True)
                continue
            out["districts"][name] = summarise((lat, lon), pois, greens)
            s = out["districts"][name]
            print(f"{name}: supermarket {s['supermarket']}, forest {s['forest']}, rail {s['rail']}", flush=True)
            out["source"] = (
                "OpenStreetMap via Overpass API (© OpenStreetMap contributors, ODbL). Distances are straight-line"
                f" from the approximate district centre, read {date.today().isoformat()}."
            )
            out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    fire.Fire(main)
