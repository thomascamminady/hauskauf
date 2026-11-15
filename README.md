# Hauskauf Bonn

A personal research tool for buying a home in Bonn (around Ippendorf, the Kottenforst and Venusberg):
listings, cost analysis, rankings, district price levels, a map and calculators, all in one standalone page.

**Open the pages:** `overview.html` (shortlist, model, calculators) and `offers.html` (every current offer in Bonn
and Wachtberg from Immowelt, Kleinanzeigen and ohne-makler.net, refreshed daily with photos, price changes and a
preview), or the GitHub Pages site.

## What's inside

| Section | What it shows |
|---|---|
| Ranking | 21 modelled homes; weigh money vs quality with sliders |
| Cost vs quality | Scatter of 20-year wealth difference vs quality score |
| Map | Listings at district level (no addresses) and district €/m² |
| Market prices | Average asking €/m² and trend for 30 districts (ImmoScout24, Q3 2026) |
| Calculators | Purchase costs, mortgage, buy-vs-rent with break-even price, €/m² check |
| Listings | Facts, price history, good / risks / checks and a verdict for each home |
| Screened | Listings looked at and rejected, with reasons |
| Checklist, log, method | Documents to request, what was discussed, model assumptions |

## Layout

```
data/        listings.json, model_public.json, market.json, log.json, listings.csv (generated)
site/        template.html (HTML/CSS/JS) and vendor/leaflet.*
scripts/     build.py – injects the data into the templates → overview.html, offers.html, index.html, data/listings.csv
             scrape.py + hausfeed/ – daily offer feed (portal adapters, crawler, store) → data/feed.json
private/     git-ignored: personal model, inputs and reports (never published)
```

## Build

```bash
uv run scripts/scrape.py   # refresh data/feed.json (also runs daily on GitHub Actions)
uv run scripts/build.py    # render the pages
uv run pytest -q           # tests
```

## Privacy

No personal data is published. Model results are relative to a reference home; the personal inputs
behind them live only in `private/`, which is git-ignored. Calculator inputs stay in the browser.
The page sets `noindex` and `robots.txt` disallows crawling.

Listing data comes from public listings (ImmoScout24, Immowelt, Kleinanzeigen, ohne-makler.net, broker sites)
and changes daily. Not financial advice. Leaflet is BSD-2-licensed (`site/vendor/LEAFLET_LICENSE`).
