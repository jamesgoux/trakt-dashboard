#!/usr/bin/env python3
"""Fetch box office (revenue) data from TMDB for all movies in the watch history.

Uses tmdb_trakt_cache.json to map Trakt slugs → TMDB IDs,
then fetches /movie/{id} for revenue + release_date.

Saves to data/box_office.json: {trakt_slug: {revenue, release_date, tmdb_id}}

Rate limit: TMDB allows ~40 req/10sec. We batch with small delays.
Caches results — only fetches movies not already in box_office.json.
"""
import json, os, sys, time
import requests

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BEARER = os.environ.get("TMDB_BEARER_TOKEN", "")
TMDB_BASE = "https://api.themoviedb.org/3"

if TMDB_BEARER:
    HEADERS = {"Authorization": f"Bearer {TMDB_BEARER}", "Accept": "application/json"}
    AUTH_PARAMS = {}
elif TMDB_API_KEY:
    HEADERS = {}
    AUTH_PARAMS = {"api_key": TMDB_API_KEY}
else:
    print("ERROR: No TMDB credentials found (TMDB_API_KEY or TMDB_BEARER_TOKEN)")
    sys.exit(1)

def fetch_movie(tmdb_id):
    """Fetch movie details from TMDB. Returns {revenue, release_date} or None."""
    url = f"{TMDB_BASE}/movie/{tmdb_id}"
    params = {**AUTH_PARAMS}
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", 2))
            time.sleep(retry)
            r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if r.status_code != 200:
            return None
        d = r.json()
        return {
            "revenue": d.get("revenue", 0),
            "release_date": d.get("release_date", ""),
            "budget": d.get("budget", 0),
        }
    except Exception as e:
        print(f"  Error fetching {tmdb_id}: {e}")
        return None

def main():
    # Load TMDB→Trakt cache (tmdb_id → trakt_slug)
    with open("data/tmdb_trakt_cache.json") as f:
        tmdb_to_slug = json.load(f)
    slug_to_tmdb = {v: k for k, v in tmdb_to_slug.items()}

    # Load timeline from index.html to get movie slugs
    with open("index.html") as f:
        html = f.read()
    start = html.find("var _irisEmbeddedData=") + len("var _irisEmbeddedData=")
    end = html.find(";\n", start)
    D = json.loads(html[start:end])
    tl = D.get("tl", [])
    movie_slugs = [t["sl"] for t in tl if t.get("type") == "movie" and t.get("sl")]
    print(f"Movies in timeline: {len(movie_slugs)}")

    # Load existing cache
    bo_path = "data/box_office.json"
    if os.path.exists(bo_path):
        with open(bo_path) as f:
            bo = json.load(f)
        print(f"Existing cache: {len(bo)} entries")
    else:
        bo = {}

    # Fetch missing
    to_fetch = [s for s in movie_slugs if s not in bo and s in slug_to_tmdb]
    print(f"To fetch: {len(to_fetch)}")

    fetched = 0
    errors = 0
    for i, slug in enumerate(to_fetch):
        tmdb_id = slug_to_tmdb[slug]
        result = fetch_movie(tmdb_id)
        if result:
            bo[slug] = result
            fetched += 1
        else:
            errors += 1
        # Rate limit: ~35 req/10sec to stay safe
        if (i + 1) % 35 == 0:
            time.sleep(10)
            print(f"  Progress: {i+1}/{len(to_fetch)} (fetched={fetched}, errors={errors})")

    print(f"Done: fetched={fetched}, errors={errors}, total={len(bo)}")

    # Save
    with open(bo_path, "w") as f:
        json.dump(bo, f, separators=(",", ":"))
    print(f"Saved to {bo_path}")

    # Quick stats
    with_revenue = sum(1 for v in bo.values() if v.get("revenue", 0) > 0)
    print(f"Movies with revenue data: {with_revenue}/{len(bo)}")

if __name__ == "__main__":
    main()
