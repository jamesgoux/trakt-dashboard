#!/usr/bin/env python3
"""
Refresh Trakt watch history and rebuild the dashboard HTML.
Reads headshots from data/headshots.json and posters from data/posters.json.
Outputs index.html for GitHub Pages.
"""

import os, json, time, requests
from collections import defaultdict, Counter
from datetime import datetime

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
USERNAME = os.environ.get("TRAKT_USERNAME")
BASE_URL = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}

if not CLIENT_ID or not USERNAME:
    print("ERROR: Set TRAKT_CLIENT_ID and TRAKT_USERNAME"); exit(1)

def fetch_history(media_type):
    items = []; page = 1
    while True:
        r = requests.get(f"{BASE_URL}/users/{USERNAME}/history/{media_type}",
                         params={"page": page, "limit": 100, "extended": "full"}, headers=HEADERS)
        if r.status_code != 200: break
        batch = r.json()
        if not batch: break
        items.extend(batch)
        if page >= int(r.headers.get("X-Pagination-Page-Count", 1)): break
        page += 1; time.sleep(0.3)
    print(f"  {media_type}: {len(items)}")
    return items

def norm_movie(e):
    m = e.get("movie", {}); ids = m.get("ids", {})
    return {"type": "movie", "watched_at": e.get("watched_at", ""), "title": m.get("title", ""),
            "year": m.get("year", ""), "runtime": m.get("runtime", ""),
            "genres": ", ".join(m.get("genres", [])), "trakt_slug": ids.get("slug", ""),
            "tmdb_id": ids.get("tmdb", ""),
            "show_title": "", "season": "", "episode_number": "", "network": ""}

def norm_show(e):
    s = e.get("show", {}); ep = e.get("episode", {}); ids = s.get("ids", {})
    return {"type": "episode", "watched_at": e.get("watched_at", ""), "title": ep.get("title", ""),
            "year": s.get("year", ""), "runtime": ep.get("runtime", ""),
            "genres": ", ".join(s.get("genres", [])), "trakt_slug": ids.get("slug", ""),
            "tmdb_id": ids.get("tmdb", ""),
            "show_title": s.get("title", ""), "season": ep.get("season", ""),
            "episode_number": ep.get("number", ""), "network": s.get("network", "")}

def fetch_cast_and_studios(entries):
    show_slugs = set(); movie_slugs = set()
    for e in entries:
        if e["trakt_slug"]:
            (movie_slugs if e["type"] == "movie" else show_slugs).add(e["trakt_slug"])
    people = defaultdict(lambda: {"name": "", "gender": None, "titles": set()})
    studios = Counter()  # studio name -> episode/movie count
    slug_studio = {}  # slug -> primary studio name
    total = len(show_slugs) + len(movie_slugs); done = 0
    for slugs, kind in [(show_slugs, "shows"), (movie_slugs, "movies")]:
        for slug in slugs:
            try:
                r = requests.get(f"{BASE_URL}/{kind}/{slug}/people?extended=full", headers=HEADERS, timeout=10)
                if r.status_code == 200:
                    for c in r.json().get("cast", []):
                        p = c.get("person", {}); pid = p.get("ids", {}).get("slug", "")
                        if pid:
                            people[pid]["name"] = p.get("name", "")
                            if p.get("gender") is not None: people[pid]["gender"] = p.get("gender")
                            people[pid]["titles"].add(slug)
            except: pass
            # Fetch studios
            try:
                r2 = requests.get(f"{BASE_URL}/{kind}/{slug}/studios", headers=HEADERS, timeout=5)
                if r2.status_code == 200:
                    st = r2.json()
                    if st:
                        slug_studio[slug] = st[0]["name"]
            except: pass
            done += 1
            if done % 100 == 0: print(f"  cast+studios: {done}/{total}")
            time.sleep(0.12)
    print(f"  people: {len(people)}, studios: {len(slug_studio)}")
    people_out = {pid: {"name": i["name"], "gender": i["gender"], "titles": list(i["titles"])} for pid, i in people.items()}
    return people_out, slug_studio

def build_data(entries, people, headshots, posters, slug_studio):
    # Titles
    tw = defaultdict(lambda: {"type":"","title":"","year":"","eby":defaultdict(int),"total":0,"runtime":0})
    for e in entries:
        s = e["trakt_slug"]
        if not s: continue
        wy = e["watched_at"][:4] if e["watched_at"] else ""
        if e["type"] == "movie":
            k = f"movie:{s}"; tw[k]["type"] = "movie"; tw[k]["title"] = e["title"]
            tw[k]["year"] = str(e["year"]) if e["year"] else ""
            tw[k]["runtime"] = int(e["runtime"]) if e["runtime"] else 0
            if wy: tw[k]["eby"][wy] += 1
            tw[k]["total"] += 1
        else:
            k = f"show:{s}"; tw[k]["type"] = "show"; tw[k]["title"] = e["show_title"]
            tw[k]["year"] = str(e["year"]) if e["year"] else ""
            if wy: tw[k]["eby"][wy] += 1
            tw[k]["total"] += 1
            if e["runtime"]: tw[k]["runtime"] = int(e["runtime"])
    tl = []; ti = {}
    for k, t in tw.items():
        ti[k] = len(tl)
        tl.append({"t":t["title"],"type":t["type"],"yr":t["year"],"eby":dict(t["eby"]),"tot":t["total"]})

    # People
    ism = lambda g: g in (2, 'male'); isf = lambda g: g in (1, 'female')
    pd = []
    for pid, info in people.items():
        if not ism(info["gender"]) and not isf(info["gender"]): continue
        tis = []; mc = sc = 0
        for ts in info["titles"]:
            for pre, typ in [("movie:", "movie"), ("show:", "show")]:
                k = pre + ts
                if k in ti: tis.append(ti[k]); mc += (1 if typ == "movie" else 0); sc += (1 if typ == "show" else 0)
        if mc + sc >= 2:
            pd.append({"n": info["name"], "g": "m" if ism(info["gender"]) else "f", "m": mc, "s": sc, "tt": mc+sc, "ti": tis})
    pd.sort(key=lambda x: x["tt"], reverse=True)

    # Show year data
    syd = defaultdict(lambda: {"name": "", "yd": defaultdict(lambda: {"e": 0, "m": 0}), "net": ""})
    for e in entries:
        if e["type"] == "episode" and e["show_title"] and e["watched_at"]:
            s = e["trakt_slug"]; yr = e["watched_at"][:4]
            syd[s]["name"] = e["show_title"]; syd[s]["yd"][yr]["e"] += 1
            if e["runtime"]: syd[s]["yd"][yr]["m"] += int(e["runtime"])
            if e["network"]: syd[s]["net"] = e["network"]

    # Movie year data
    myd = defaultdict(lambda: {"name": "", "yr": "", "rt": 0, "yd": defaultdict(int)})
    for e in entries:
        if e["type"] == "movie" and e["title"] and e["watched_at"]:
            k = e["title"]; yr = e["watched_at"][:4]
            myd[k]["name"] = e["title"]; myd[k]["yr"] = str(e["year"]) if e["year"] else ""
            if e["runtime"]: myd[k]["rt"] = int(e["runtime"])
            myd[k]["yd"][yr] += 1

    # Charts
    monthly = defaultdict(lambda: {"movies": 0, "episodes": 0})
    yearly = defaultdict(lambda: {"movies": 0, "episodes": 0, "total": 0})
    genre_movie = Counter(); genre_show = Counter()
    dwc = Counter(); dwn = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    hod = defaultdict(lambda: defaultdict(int))  # hour of day by year
    net_counter = Counter()
    studio_counter = Counter()
    recent_all = []  # full list for year filtering

    for e in entries:
        if not e["watched_at"]: continue
        m = e["watched_at"][:7]; y = e["watched_at"][:4]
        if e["type"] == "movie": monthly[m]["movies"] += 1; yearly[y]["movies"] += 1
        else: monthly[m]["episodes"] += 1; yearly[y]["episodes"] += 1
        yearly[y]["total"] += 1
        if e["genres"]:
            for g in e["genres"].split(", "):
                gs = g.strip()
                if e["type"] == "movie": genre_movie[gs] += 1
                else: genre_show[gs] += 1
        if e["network"]: net_counter[e["network"]] += 1
        st = slug_studio.get(e["trakt_slug"])
        if st: studio_counter[st] += 1
        try:
            dt = datetime.fromisoformat(e["watched_at"].replace("Z", "+00:00"))
            dwc[dwn[dt.weekday()]] += 1
            hod[y][dt.hour] += 1
        except: pass

    # Recent: keep 200 most recent for filtering
    sorted_entries = sorted(entries, key=lambda x: x["watched_at"], reverse=True)
    for e in sorted_entries[:200]:
        recent_all.append({
            "type": e["type"],
            "title": e["show_title"] or e["title"],
            "detail": f"S{e['season']}E{e['episode_number']}" if e["type"] == "episode" else str(e["year"]),
            "watched_at": e["watched_at"][:10],
            "yr": e["watched_at"][:4] if e["watched_at"] else ""
        })

    ml = [e for e in entries if e["type"] == "movie"]
    el = [e for e in entries if e["type"] == "episode"]
    tr = sum(int(e["runtime"]) for e in entries if e["runtime"])

    # Hour of day aggregate (all time)
    hod_all = Counter()
    for yr_data in hod.values():
        for h, c in yr_data.items():
            hod_all[h] += c
    hod_by_year = {y: dict(d) for y, d in hod.items()}

    return {
        "a": [p for p in pd if p["g"] == "m"],
        "x": [p for p in pd if p["g"] == "f"],
        "tl": tl, "hs": headshots, "ps": posters,
        "syd": [{"n": i["name"], "net": i["net"],
                 "yd": {y: {"e": d["e"], "m": d["m"]} for y, d in i["yd"].items()}}
                for _, i in syd.items()],
        "myd": [{"n": i["name"], "yr": i["yr"], "rt": i["rt"], "yd": dict(i["yd"])}
                for i in myd.values()],
        "c": {
            "s": {"total_watches": len(entries), "movie_watches": len(ml), "episode_watches": len(el),
                  "unique_movies": len(set(e["title"] for e in ml)),
                  "unique_shows": len(set(e["show_title"] for e in el if e["show_title"])),
                  "total_runtime_days": round(tr/60/24, 1)},
            "m": [{"month": m, **d} for m, d in sorted(monthly.items())],
            "y": [{"year": y, **d} for y, d in sorted(yearly.items())],
            "gm": [{"genre": g, "count": c} for g, c in genre_movie.most_common(20)],
            "gs": [{"genre": g, "count": c} for g, c in genre_show.most_common(20)],
            "ga": [{"genre": g, "count": genre_movie[g] + genre_show[g]}
                   for g, _ in (genre_movie + genre_show).most_common(20)],
            "dw": [{"day": d, "count": dwc.get(d, 0)} for d in dwn],
            "hod": {str(h): hod_all.get(h, 0) for h in range(24)},
            "hod_y": hod_by_year,
            "net": [{"network": n, "count": c} for n, c in net_counter.most_common(25)],
            "stu": [{"studio": s, "count": c} for s, c in studio_counter.most_common(25)],
            "r": recent_all,
        }
    }

# ---- Main ----
print("=== Trakt Data Refresh ===")

print("\n[1/3] Fetching watch history...")
raw_movies = fetch_history("movies")
raw_shows = fetch_history("shows")
entries = [norm_movie(e) for e in raw_movies] + [norm_show(e) for e in raw_shows]
entries.sort(key=lambda x: x["watched_at"], reverse=True)
print(f"  Total: {len(entries)} entries")

print("\n[2/3] Fetching cast + studios...")
people, slug_studio = fetch_cast_and_studios(entries)

# Save people and entries for other scripts
os.makedirs("data", exist_ok=True)
with open("data/people.json", "w") as f:
    json.dump(people, f, separators=(',', ':'))

# Save entry slugs with last watched year for headshot priority
slug_recency = {}
for e in entries:
    if e["watched_at"]:
        yr = int(e["watched_at"][:4])
        slug_recency[e["trakt_slug"]] = max(slug_recency.get(e["trakt_slug"], 0), yr)
with open("data/slug_recency.json", "w") as f:
    json.dump(slug_recency, f, separators=(',', ':'))

# Load headshots and posters
hs = {}
if os.path.exists("data/headshots.json"):
    with open("data/headshots.json") as f: hs = json.load(f)
ps = {}
if os.path.exists("data/posters.json"):
    with open("data/posters.json") as f: ps = json.load(f)

print(f"\n[3/3] Building dashboard ({len(entries)} entries, {len(people)} people, {len(hs)} headshots, {len(ps)} posters)...")
data = build_data(entries, people, hs, ps, slug_studio)

data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
with open("templates/dashboard.html") as f:
    template = f.read()
html = template.replace("__DASHBOARD_DATA__", data_str)
with open("index.html", "w") as f:
    f.write(html)

print(f"  index.html: {len(html)//1024}KB")
print(f"  Actors: {len(data['a'])}, Actresses: {len(data['x'])}")
print(f"  Networks: {len(data['c']['net'])}, Studios: {len(data['c']['stu'])}")
print("Done!")
