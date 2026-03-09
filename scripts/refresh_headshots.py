#!/usr/bin/env python3
"""
Image backfill script — fetches posters, logos, and headshots from TMDB.

Priority order: posters → logos → actors → directors → writers
Within each: most recently watched content first.
Goal: complete coverage for recent watches before older ones.

Budget per run: ~1000 TMDB requests total (respects rate limits).
"""

import os, json, time, re, requests

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
BASE_URL = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}

# Total budget per run — split across categories
TOTAL_BUDGET = 1000

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
    try:
        r = requests.get(tmdb_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            imgs = re.findall(r'https://image\.tmdb\.org/t/p/w500/([^"\']+\.jpg)', r.text)
            if imgs:
                return imgs[0]
    except: pass
    return None

def fetch_tmdb_png(tmdb_url):
    try:
        r = requests.get(tmdb_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            imgs = re.findall(r'https://image\.tmdb\.org/t/p/[^"\']+\.png', r.text)
            if imgs:
                return imgs[0]
    except: pass
    return None

# ============================================================
# POSTERS (show/movie cover images) — PRIORITY 1
# ============================================================
def fetch_posters(budget):
    ps = load_json("data/posters.json")
    slug_recency = load_json("data/slug_recency.json")
    vis = load_json("data/visible_priority.json")

    # All slugs needing posters, sorted by most recent watch
    need = [(s, yr) for s, yr in slug_recency.items() if s and s not in ps]
    # Prioritize slugs visible on the all/all dashboard page
    vis_slugs = set(vis.get("shows", []) + vis.get("movies", []))
    need.sort(key=lambda x: (1 if x[0] in vis_slugs else 0, x[1]), reverse=True)
    need = need[:budget]

    print(f"\n[1/5] Posters: {len(ps)} cached, {len(need)} to fetch")
    if not need: return 0

    count = 0; used = 0
    for i, (slug, _) in enumerate(need):
        for kind in ["tv", "movie"]:
            try:
                trakt_kind = "shows" if kind == "tv" else "movies"
                r1 = requests.get(f"{BASE_URL}/{trakt_kind}/{slug}", headers=HEADERS, timeout=5)
                used += 1
                if r1.status_code == 200:
                    tmdb_id = r1.json().get("ids", {}).get("tmdb")
                    if tmdb_id:
                        h = fetch_tmdb_image(f"https://www.themoviedb.org/{kind}/{tmdb_id}")
                        used += 1
                        if h:
                            ps[slug] = f"https://image.tmdb.org/t/p/w185/{h}"
                            count += 1; break
            except: pass
            time.sleep(0.08)
        if (i+1) % 50 == 0:
            print(f"  {i+1}/{len(need)}, {count} found")
            save_json("data/posters.json", ps)
        time.sleep(0.08)

    save_json("data/posters.json", ps)
    print(f"  +{count} posters ({len(ps)} total), {used} requests")
    return used

# ============================================================
# LOGOS (studio/network) — PRIORITY 2
# ============================================================
def fetch_logos(budget):
    logos = load_json("data/logos.json")
    studios_raw = load_json("data/studios.json")
    slug_recency = load_json("data/slug_recency.json")

    # Score each studio by most recent title it appears on
    studio_recency = {}
    for slug, names in studios_raw.items():
        yr = slug_recency.get(slug, 0)
        ns = names if isinstance(names, list) else [names]
        for n in ns:
            studio_recency[n] = max(studio_recency.get(n, 0), yr)

    need = [(n, yr) for n, yr in studio_recency.items() if n not in logos]
    need.sort(key=lambda x: x[1], reverse=True)
    need = need[:budget]

    print(f"\n[2/5] Logos: {len(logos)} cached, {len(need)} to fetch")
    if not need: return 0

    count = 0; used = 0
    for i, (name, _) in enumerate(need):
        found_slug = None
        for slug, names in studios_raw.items():
            ns = names if isinstance(names, list) else [names]
            if name in ns:
                found_slug = slug; break
        if not found_slug: continue
        try:
            for kind in ["movies", "shows"]:
                r = requests.get(f"{BASE_URL}/{kind}/{found_slug}/studios", headers=HEADERS, timeout=5)
                used += 1
                if r.status_code == 200:
                    for s in r.json():
                        if s["name"] == name:
                            tmdb_id = s["ids"].get("tmdb")
                            if tmdb_id:
                                img = fetch_tmdb_png(f"https://www.themoviedb.org/company/{tmdb_id}")
                                used += 1
                                if img:
                                    logos[name] = img
                                    count += 1
                            break
                    if name in logos: break
        except: pass
        if (i+1) % 20 == 0:
            print(f"  {i+1}/{len(need)}, {count} found")
            save_json("data/logos.json", logos)
        time.sleep(0.15)

    save_json("data/logos.json", logos)
    print(f"  +{count} logos ({len(logos)} total), {used} requests")
    return used

# ============================================================
# HEADSHOTS (actors, directors, writers) — PRIORITY 3/4/5
# ============================================================
def fetch_headshots_for(label, priority, source_files, budget):
    hs = load_json("data/headshots.json")
    slug_recency = load_json("data/slug_recency.json")
    vis = load_json("data/visible_priority.json")

    # Build set of person slugs visible on the all/all page
    vis_key = "directors" if "director" in source_files[0] else "writers" if "writer" in source_files[0] else "people"
    vis_pids = set(p["pid"] for p in vis.get(vis_key, []))

    # Combine sources
    all_people = {}
    for src_file in source_files:
        src = load_json(src_file)
        for slug, info in src.items():
            if slug not in all_people:
                all_people[slug] = info

    def person_recency(slug):
        titles = all_people.get(slug, {}).get("titles", [])
        return max((slug_recency.get(t, 0) for t in titles), default=0)

    need = [(slug, info) for slug, info in all_people.items() if info["name"] not in hs]
    # Sort: visible on dashboard first, then by recency
    need.sort(key=lambda x: (1 if x[0] in vis_pids else 0, person_recency(x[0])), reverse=True)
    need = need[:budget]

    print(f"\n[{priority}/5] {label}: {sum(1 for p in all_people.values() if p['name'] in hs)} cached, {len(need)} to fetch")
    if not need: return 0

    count = 0; used = 0
    for i, (slug, info) in enumerate(need):
        try:
            r1 = requests.get(f"{BASE_URL}/people/{slug}?extended=full", headers=HEADERS, timeout=5)
            used += 1
            if r1.status_code == 200:
                tmdb_id = r1.json().get("ids", {}).get("tmdb")
                if tmdb_id:
                    h = fetch_tmdb_image(f"https://www.themoviedb.org/person/{tmdb_id}")
                    used += 1
                    if h:
                        hs[info["name"]] = f"https://image.tmdb.org/t/p/w185/{h}"
                        count += 1
        except: pass
        if (i+1) % 200 == 0:
            print(f"  {i+1}/{len(need)}, {count} found")
            save_json("data/headshots.json", hs)
        time.sleep(0.1)

    save_json("data/headshots.json", hs)
    print(f"  +{count} {label.lower()} ({len(hs)} total headshots), {used} requests")
    return used

# ============================================================
# MAIN — allocate budget across categories
# ============================================================
print("=== Iris Image Backfill ===")
print(f"Budget: {TOTAL_BUDGET} requests\n")

remaining = TOTAL_BUDGET

# 1. Posters (20% of budget)
used = fetch_posters(min(200, remaining))
remaining -= used

# 2. Logos (10% of budget)
used = fetch_logos(min(100, remaining))
remaining -= used

# 3. Actors (35% of remaining)
actor_budget = min(remaining * 35 // 100, remaining)
used = fetch_headshots_for("Actors", 3, ["data/people.json"], actor_budget // 2)  # 2 requests per person
remaining -= used

# 4. Directors (30% of remaining)
dir_budget = min(remaining * 45 // 100, remaining)
used = fetch_headshots_for("Directors", 4, ["data/directors.json"], dir_budget // 2)
remaining -= used

# 5. Writers (rest)
used = fetch_headshots_for("Writers", 5, ["data/writers.json"], remaining // 2)

# Summary
hs = load_json("data/headshots.json")
ps = load_json("data/posters.json")
lg = load_json("data/logos.json")
print(f"\n=== Summary ===")
print(f"Headshots: {len(hs)}, Posters: {len(ps)}, Logos: {len(lg)}")
print("Done!")
