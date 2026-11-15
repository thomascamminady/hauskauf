# /// script
# requires-python = ">=3.12"
# dependencies = ["fire"]
# ///
"""Build the standalone overview page (and a CSV export) from the JSON files in data/.

Usage:
    uv run scripts/build.py                      # public: overview.html, index.html, data/listings.csv
    uv run scripts/build.py --private_model=private/model_private.json --out=private/overview_private.html
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import fire

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hausfeed.core import zip_area

ROOT = Path(__file__).resolve().parent.parent
MARKER = "/*__DATA__*/null"
CSV_FIELDS = [
    "id",
    "category",
    "type",
    "title",
    "district",
    "asking",
    "size_m2",
    "plot_m2",
    "rooms",
    "bedrooms",
    "baths",
    "built",
    "heating",
    "energy",
    "service_charge",
    "broker_pct",
    "private_sale",
    "availability",
    "url",
    "all_in",
    "std_monthly",
    "vs_ref_20y",
    "vs_ref_min",
    "vs_ref_max",
    "own_vs_rent_20y",
    "reason",
    "verdict",
]


def load(name: str) -> Any:
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


SOURCE_LABELS = {"immowelt": "Immowelt", "kleinanzeigen": "Kleinanzeigen", "ohnemakler": "ohne-makler"}
FEED_FIELDS = [
    "source",
    "url",
    "kind",
    "title",
    "price",
    "size_m2",
    "rooms",
    "zip",
    "district",
    "plot_m2",
    "energy_class",
    "image",
    "seller",
    "first_seen",
    "last_seen",
    "active",
    "gone",
    "price_history",
]
SHOW_GONE_DAYS = 14


def feed_payload(listings: list[dict[str, Any]], market: dict[str, Any]) -> dict[str, Any] | None:
    """Offers for offers.html: one card per home (duplicates across portals merged), plus derived figures."""
    path = ROOT / "data" / "feed.json"
    if not path.exists():
        return None
    feed = json.loads(path.read_text(encoding="utf-8"))
    config = load("feed_config.json")
    scores: dict[str, float] = config.get("location_score", {})
    updated = feed["updated"]
    tracked = {row["url"]: row["id"] for row in listings if row.get("url")}

    def recent(rec: dict[str, Any]) -> bool:
        return (
            rec.get("active")
            or (date.fromisoformat(updated) - date.fromisoformat(rec.get("gone", updated))).days <= SHOW_GONE_DAYS
        )

    offers: list[dict[str, Any]] = []
    for key, rec in feed["offers"].items():
        if not recent(rec):
            continue
        group = [key, *rec.get("same_as", [])]
        if min(group) != key:  # show each home once, under the smallest key
            continue
        out = {k: rec.get(k) for k in FEED_FIELDS}
        out["key"] = key
        out["same_as"] = rec.get("same_as", [])
        out["sources"] = sorted({feed["offers"][k]["source"] for k in group if k in feed["offers"]})
        if not out["image"]:
            out["image"] = next(
                (feed["offers"][k].get("image") for k in group if feed["offers"].get(k, {}).get("image")), None
            )
        price, size, district = rec.get("price"), rec.get("size_m2"), rec.get("district")
        out["eur_m2"] = round(price / size) if price and size else None
        avg = (market["districts"].get(district or "", {}).get(rec["kind"]) or {}).get("eur")
        out["district_eur"] = avg
        out["vs_district"] = round(100 * (out["eur_m2"] / avg - 1)) if out["eur_m2"] and avg else None
        out["fit"] = scores.get(district or "")
        out["area"] = district or zip_area(rec.get("zip"))
        hist = rec.get("price_history") or []
        out["price_change"] = hist[-1][1] - hist[0][1] if len(hist) > 1 else None
        out["tracked"] = next((tracked[rec[k]] for k in ["url"] if rec.get(k) in tracked), None)
        offers.append(out)
    active = [o for o in offers if o["active"]]
    used = sorted({r["source"] for r in feed["runs"]})
    return {
        "updated": updated,
        "offers": offers,
        "active": len(active),
        "new_today": sum(1 for o in active if o["first_seen"] == updated),
        "fit": sum(1 for o in active if (o["fit"] or 0) >= 4 and (o["size_m2"] or 0) >= 105),
        "sources": [{"name": s, "label": SOURCE_LABELS.get(s, s)} for s in used],
        "runs": feed["runs"],
    }


def render(template_name: str, data: dict[str, Any]) -> str:
    template = (ROOT / "site" / template_name).read_text(encoding="utf-8")
    vendor = ROOT / "site" / "vendor"
    template = template.replace("/*__BASE_CSS__*/", (ROOT / "site" / "base.css").read_text(encoding="utf-8"))
    template = template.replace("/*__COMMON_JS__*/", (ROOT / "site" / "common.js").read_text(encoding="utf-8"))
    template = template.replace("/*__LEAFLET_CSS__*/", (vendor / "leaflet.css").read_text(encoding="utf-8"))
    template = template.replace("/*__LEAFLET_JS__*/", (vendor / "leaflet.js").read_text(encoding="utf-8"))
    if MARKER not in template:
        raise SystemExit(f"data marker missing in {template_name}")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return template.replace(MARKER, blob)


def shared() -> dict[str, Any]:
    """Data both pages need for quality criteria and neighbourhood facts."""
    market = load("market.json")
    amenities_path = ROOT / "data" / "amenities.json"
    return {
        "criteria": load("criteria.json"),
        "amenities": json.loads(amenities_path.read_text(encoding="utf-8")) if amenities_path.exists() else None,
        "districts": {n: {"lat": d["lat"], "lon": d["lon"]} for n, d in market["districts"].items()},
    }


def payload(private_model: Path | None, updated: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        **shared(),
        "updated": updated,
        "listings": load("listings.json"),
        "model": load("model_public.json"),
        "market": load("market.json"),
        "log": load("log.json"),
    }
    feed = feed_payload(data["listings"], data["market"])
    if feed is not None:
        data["feed"] = {k: v for k, v in feed.items() if k not in ("offers", "runs")} | {
            "sources": [s["label"] for s in feed["sources"]]
        }
    if private_model is not None:
        data["private"] = json.loads(private_model.read_text(encoding="utf-8"))
    return data


def write_csv(data: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in data["listings"]:
            w.writerow({**row, **data["model"].get(row["id"], {})})


def main(out: str = "overview.html", private_model: str | None = None, updated: str = "15 Nov 2026") -> None:
    """Render the page. A private model file adds personal columns; never publish that output."""
    pm = ROOT / private_model if private_model else None
    data = payload(pm, updated)
    target = ROOT / out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render("template.html", data), encoding="utf-8")
    feed = feed_payload(data["listings"], data["market"])
    if feed is not None:
        offers_page = target.parent / "offers.html"
        offers_page.write_text(render("offers.html", {"feed": feed, **shared()}), encoding="utf-8")
        print(
            f"wrote {offers_page.relative_to(ROOT)} ({offers_page.stat().st_size / 1024:.0f} KB, {feed['active']} active offers)"
        )
    if pm is None:
        (ROOT / "index.html").write_text(
            '<!DOCTYPE html><meta charset="utf-8"><meta name="robots" content="noindex, nofollow">'
            '<meta http-equiv="refresh" content="0; url=overview.html"><title>Hauskauf Bonn</title>'
            '<a href="overview.html">Overview</a>\n',
            encoding="utf-8",
        )
        write_csv(data, ROOT / "data" / "listings.csv")
    print(f"wrote {target.relative_to(ROOT)} ({target.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    fire.Fire(main)
