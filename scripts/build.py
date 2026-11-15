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
from pathlib import Path
from typing import Any

import fire

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


def payload(private_model: Path | None, updated: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "updated": updated,
        "listings": load("listings.json"),
        "model": load("model_public.json"),
        "market": load("market.json"),
        "log": load("log.json"),
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
    template = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
    vendor = ROOT / "site" / "vendor"
    template = template.replace("/*__LEAFLET_CSS__*/", (vendor / "leaflet.css").read_text(encoding="utf-8"))
    template = template.replace("/*__LEAFLET_JS__*/", (vendor / "leaflet.js").read_text(encoding="utf-8"))
    if MARKER not in template:
        raise SystemExit("data marker missing in template")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    target = ROOT / out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace(MARKER, blob), encoding="utf-8")
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
