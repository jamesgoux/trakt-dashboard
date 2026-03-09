#!/usr/bin/env python3
"""Fast bulk poster backfill from TMDB via Trakt TMDB IDs. ~4 min for all."""
import json, os, time, requests

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TRAKT_KEY = os.environ.get("TRAKT_CLIENT_ID", "de055ca9c6de268c33c77950f21564c1183ff852b18534f4d33eebc14d05616d")
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": TRAKT_KEY}

ps = {}
if os.path.exists("data/posters.json"):
    with open("data/posters.json") as f:
        ps = json.load(f)

sr = {}
if os.path.exists("data/slug_recency.json"):
    with open("data/slug_recency.json") as f:
        sr = json.load(f)

need = [(s, yr) for s, yr in sr.items() if s and s not in ps]
need.sort(key=lambda x: x[1], reverse=True)

print(f"=== Poster Backfill ===")
print(f"  Existing: {len(ps)}, Need: {len(need)}")

count = 0
errors = 0
for i, (slug, yr) in enumerate(need):
    # Try shows first, then movies (from Trakt → get TMDB ID → scrape TMDB page)
    found = False
    for kind, trakt_kind in [("tv", "shows"), ("movie", "movies")]:
        try:
            r = requests.get(f"https://api.trakt.tv/{trakt_kind}/{slug}",
                           headers=HEADERS, timeout=5)
            if r.status_code == 200:
                tmdb_id = r.json().get("ids", {}).get("tmdb")
                if tmdb_id:
                    # Scrape TMDB page for poster
                    r2 = requests.get(f"https://www.themoviedb.org/{kind}/{tmdb_id}",
                                     headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                    if r2.status_code == 200:
                        import re
                        imgs = re.findall(r'media\.themoviedb\.org/t/p/w\d+/([a-zA-Z0-9]+\.jpg)', r2.text)
                        if imgs:
                            ps[slug] = f"https://image.tmdb.org/t/p/w185/{imgs[0]}"
                            count += 1
                            found = True
                            break
            elif r.status_code == 429:
                time.sleep(2)
        except Exception:
            errors += 1
        time.sleep(0.1)

    if (i + 1) % 25 == 0:
        print(f"  {i+1}/{len(need)}: +{count} posters ({errors} errors)")
        with open("data/posters.json", "w") as f:
            json.dump(ps, f, separators=(",", ":"))

    if r.status_code == 429 if 'r' in dir() else False:
        time.sleep(3)
    else:
        time.sleep(0.15)

with open("data/posters.json", "w") as f:
    json.dump(ps, f, separators=(",", ":"))

print(f"  Done: +{count} posters ({len(ps)} total)")
