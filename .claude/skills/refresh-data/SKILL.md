---
name: refresh-data
description: Pull the latest listing data for the Hauskauf Bonn site – offers from Immowelt, Kleinanzeigen and ohne-makler, optionally OpenStreetMap neighbourhood facts – rebuild the pages, check them and publish. Use when asked to refresh, update or pull the latest offers/data, or to check on the scheduled "Refresh data" GitHub Action.
---

# Refresh data

The GitHub Action `.github/workflows/refresh-data.yml` already does this **every other day** (06:17 CET on odd days of
the month) and refreshes neighbourhood facts on the 1st. Prefer triggering that workflow; run locally only when the
Action is failing or the user wants to watch it here.

## 1. See what's there

```bash
gh run list --workflow refresh-data.yml --limit 5
git pull --rebase
python3 -c "import json;f=json.load(open('data/feed.json'));print(f['updated'], sum(r['active'] for r in f['offers'].values()), 'active');print(f['runs'][-3:])"
```

If the last run failed, open it with `gh run view <id> --log-failed` before doing anything else.

## 2a. Refresh via GitHub Actions (preferred)

```bash
gh workflow run refresh-data.yml                    # offers only (~6 min)
gh workflow run refresh-data.yml -f amenities=true  # + OpenStreetMap neighbourhood facts (~20 min)
gh run watch $(gh run list --workflow refresh-data.yml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
git pull --rebase
```

Run `gh run watch` in the background; you'll be notified when it ends.

## 2b. Refresh locally (fallback)

```bash
uv run scripts/scrape.py                 # all portals, polite 2 s delay, ~6 min – run in the background
uv run scripts/amenities.py --refresh    # optional; Overpass is often busy – it retries, resumes and skips failures
uv run scripts/build.py
uv run pytest -q && uv run ruff check scripts tests && uv run ty check scripts tests
```

## 3. Sanity-check before publishing

- Scrape summary: every portal `0 errors` (or only 404s past the last page); offers per portal roughly as before
  (Immowelt ~450, Kleinanzeigen ~250, ohne-makler ~15). A portal suddenly at 0 means its markup changed – fix the
  adapter in `scripts/hausfeed/sources/` and add a fixture test; don't publish a feed that marked everything gone
  (failed runs never mark offers gone, so a 0 is a parsing problem).
- New builds and builder ads stay out (`core.is_new_build`); spot-check the newest offers on `offers.html`.
- Amenities: forest distances should match reality (Röttgen/Heiderhof at the Kottenforst, Schweinheim/Venusberg at
  the Stadtwald); never publish a run where most districts lost their forest.
- Privacy (see CLAUDE.md): no street addresses, contact names or owner data in `data/feed.json`
  (`grep -iE "straße [0-9]|str\. [0-9]|herr |frau " data/feed.json` should find nothing).
- Look at both pages in the browser (`.claude/launch.json` → `site` on port 8765) before pushing.

## 4. Publish (local route only)

```bash
git add data/feed.json data/amenities.json offers.html overview.html index.html data/listings.csv
git -c user.name=thomascamminady -c user.email=24543638+thomascamminady@users.noreply.github.com \
  commit -m "Refresh data $(date +%F)"
git push
```

## Not automated

- **ImmoScout24** (shortlist homes, `data/market.json` district €/m²) shows a bot check to automated clients. Never
  try to get around it; those figures are updated by hand from a normal browser session when the user asks.
- **Shortlist model numbers** (`data/model_public.json`) come from `private/compute.py` and only change when the
  user adds or re-prices a shortlist home.
