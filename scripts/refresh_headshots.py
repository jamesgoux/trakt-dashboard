#!/usr/bin/env python3
"""
Incrementally fetch headshot images + show/movie posters.
Prioritizes actors from recently-watched content.
Saves progress every 200 items.
"""

import os, json, time, re, requests

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
BASE_URL = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}
MAX_HEADSHOTS = 800
MAX_POSTERS = 200

if not CLIENT_ID:
    print("ERROR: Set TRAKT_CLIENT_ID"); exit(1)

os.makedirs("data", exist_ok=True)

def load_json(path):
    if os.path.exists(path):
        with open(path) as f: return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, separators=(',', ':'))

def fetch_tmdb_image(tmdb_url):
    """Scrape TMDB page for primary image."""
    try:
        r = requests.get(tmdb_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            imgs = re.findall(r'https://image\.tmdb\.org/t/p/w500/([^"\']+\.jpg)', r.text)
            if imgs:
                return imgs[0]
    except: pass
    return None

# ============================================================
# HEADSHOTS
# ============================================================
def refresh_headshots():
    hs = load_json("data/headshots.json")
    people = load_json("data/people.json")
    slug_recency = load_json("data/slug_recency.json")

    if not people:
        print("  No people data. Run refresh_data.py first."); return

    # Score each person by most recent title they appeared in
    def person_recency(slug):
        titles = people.get(slug, {}).get("titles", [])
        return max((slug_recency.get(t, 0) for t in titles), default=0)

    # People needing headshots, sorted by recency (newest first)
    need = [(slug, info) for slug, info in people.items() if info["name"] not in hs]
    need.sort(key=lambda x: person_recency(x[0]), reverse=True)
    need = need[:MAX_HEADSHOTS]

    print(f"\n=== Headshots: {len(hs)} cached, {len(need)} to fetch ===")
    if not need: print("  All up to date!"); return

    count = 0
    for i, (slug, info) in enumerate(need):
        try:
            r1 = requests.get(f"{BASE_URL}/people/{slug}?extended=full", headers=HEADERS, timeout=5)
            if r1.status_code == 200:
                tmdb_id = r1.json().get("ids", {}).get("tmdb")
                if tmdb_id:
                    hash = fetch_tmdb_image(f"https://www.themoviedb.org/person/{tmdb_id}")
                    if hash:
                        hs[info["name"]] = f"https://image.tmdb.org/t/p/w185/{hash}"
                        count += 1
        except: pass
        if (i+1) % 200 == 0:
            print(f"  {i+1}/{len(need)} processed, {count} found")
            save_json("data/headshots.json", hs)
        time.sleep(0.1)

    save_json("data/headshots.json", hs)
    print(f"  +{count} new headshots, {len(hs)} total")

# ============================================================
# POSTERS (show/movie cover images)
# ============================================================
def refresh_posters():
    ps = load_json("data/posters.json")
    slug_recency = load_json("data/slug_recency.json")

    # Get all unique show/movie slugs from people's titles
    people = load_json("data/people.json")
    all_slugs = set()
    for info in people.values():
        all_slugs.update(info.get("titles", []))

    # Also include slugs from recency data
    all_slugs.update(slug_recency.keys())

    # Filter to those without posters, prioritize recent
    need = [(s, slug_recency.get(s, 0)) for s in all_slugs if s and s not in ps]
    need.sort(key=lambda x: x[1], reverse=True)
    need = need[:MAX_POSTERS]

    print(f"\n=== Posters: {len(ps)} cached, {len(need)} to fetch ===")
    if not need: print("  All up to date!"); return

    count = 0
    for i, (slug, _) in enumerate(need):
        # Try as show first, then movie
        for kind in ["tv", "movie"]:
            try:
                # Get TMDB ID from Trakt
                trakt_kind = "shows" if kind == "tv" else "movies"
                r1 = requests.get(f"{BASE_URL}/{trakt_kind}/{slug}", headers=HEADERS, timeout=5)
                if r1.status_code == 200:
                    tmdb_id = r1.json().get("ids", {}).get("tmdb")
                    if tmdb_id:
                        hash = fetch_tmdb_image(f"https://www.themoviedb.org/{kind}/{tmdb_id}")
                        if hash:
                            ps[slug] = f"https://image.tmdb.org/t/p/w185/{hash}"
                            count += 1
                            break
            except: pass
            time.sleep(0.08)

        if (i+1) % 50 == 0:
            print(f"  {i+1}/{len(need)} processed, {count} found")
            save_json("data/posters.json", ps)
        time.sleep(0.08)

    save_json("data/posters.json", ps)
    print(f"  +{count} new posters, {len(ps)} total")

# ---- Main ----
print("=== Image Refresh ===")
refresh_headshots()
refresh_posters()
print("\nDone!")
