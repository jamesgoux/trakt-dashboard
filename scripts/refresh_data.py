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
            "show_title": "", "season": "", "episode_number": "", "network": "",
            "country": m.get("country", ""), "language": m.get("language", "")}

def norm_show(e):
    s = e.get("show", {}); ep = e.get("episode", {}); ids = s.get("ids", {})
    return {"type": "episode", "watched_at": e.get("watched_at", ""), "title": ep.get("title", ""),
            "year": s.get("year", ""), "runtime": ep.get("runtime", ""),
            "genres": ", ".join(s.get("genres", [])), "trakt_slug": ids.get("slug", ""),
            "tmdb_id": ids.get("tmdb", ""),
            "show_title": s.get("title", ""), "season": ep.get("season", ""),
            "episode_number": ep.get("number", ""), "network": s.get("network", ""),
            "country": s.get("country", ""), "language": s.get("language", ""),
            "first_aired": ep.get("first_aired", "")}

def fetch_cast_and_studios(entries):
    show_slugs = set(); movie_slugs = set()
    for e in entries:
        if e["trakt_slug"]:
            (movie_slugs if e["type"] == "movie" else show_slugs).add(e["trakt_slug"])
    # MERGE with existing people data so we never lose actors
    people = defaultdict(lambda: {"name": "", "gender": None, "titles": set()})
    directors = defaultdict(lambda: {"name": "", "titles": set()})
    writers = defaultdict(lambda: {"name": "", "titles": set()})
    # Load existing crew data
    for crew_file, crew_dict in [("data/directors.json", directors), ("data/writers.json", writers)]:
        if os.path.exists(crew_file):
            with open(crew_file) as f:
                for pid, info in json.load(f).items():
                    crew_dict[pid]["name"] = info["name"]
                    crew_dict[pid]["titles"] = set(info.get("titles", []))
    if os.path.exists("data/people.json"):
        with open("data/people.json") as f:
            existing = json.load(f)
        for pid, info in existing.items():
            people[pid]["name"] = info["name"]
            people[pid]["gender"] = info["gender"]
            people[pid]["titles"] = set(info.get("titles", []))
        print(f"  Loaded {len(existing)} existing people (merging)")
    # Merge with existing studios too - now stores LIST of studios per slug
    slug_studios = {}  # slug -> [studio1, studio2, ...]
    if os.path.exists("data/studios.json"):
        with open("data/studios.json") as f:
            raw = json.load(f)
        # Migrate old format (string) to new (list)
        for k, v in raw.items():
            slug_studios[k] = v if isinstance(v, list) else [v]
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
                    # Also extract directors and writers from crew
                    crew = r.json().get("crew", {})
                    dir_roles = {"Director", "Co-Director"}
                    wr_roles = {"Writer", "Screenplay", "Author", "Original Story", "Story"}
                    for cp in crew.get("directing", []):
                        jobs = set(cp.get("jobs", []))
                        if jobs & dir_roles:
                            pid2 = cp.get("person", {}).get("ids", {}).get("slug", "")
                            if pid2:
                                directors[pid2]["name"] = cp["person"].get("name", "")
                                directors[pid2]["titles"].add(slug)
                    for cp in crew.get("writing", []):
                        jobs = set(cp.get("jobs", []))
                        if jobs & wr_roles:
                            pid2 = cp.get("person", {}).get("ids", {}).get("slug", "")
                            if pid2:
                                writers[pid2]["name"] = cp["person"].get("name", "")
                                writers[pid2]["titles"].add(slug)
            except: pass
            # Fetch studios (store ALL, not just first)
            try:
                r2 = requests.get(f"{BASE_URL}/{kind}/{slug}/studios", headers=HEADERS, timeout=5)
                if r2.status_code == 200:
                    st = r2.json()
                    if st:
                        names = [s["name"] for s in st]
                        # Merge: keep any existing studios + new ones
                        existing = set(slug_studios.get(slug, []))
                        existing.update(names)
                        slug_studios[slug] = list(existing)
            except: pass
            done += 1
            if done % 100 == 0: print(f"  cast+studios: {done}/{total}")
            time.sleep(0.12)
    print(f"  people: {len(people)}, studios: {len(slug_studios)}, directors: {len(directors)}, writers: {len(writers)}")
    people_out = {pid: {"name": i["name"], "gender": i["gender"], "titles": list(i["titles"])} for pid, i in people.items()}
    dir_out = {pid: {"name": i["name"], "titles": list(i["titles"])} for pid, i in directors.items()}
    wr_out = {pid: {"name": i["name"], "titles": list(i["titles"])} for pid, i in writers.items()}
    # Save persistently
    os.makedirs("data", exist_ok=True)
    with open("data/studios.json", "w") as f:
        json.dump(slug_studios, f, separators=(',', ':'))
    with open("data/directors.json", "w") as f:
        json.dump(dir_out, f, separators=(',', ':'))
    with open("data/writers.json", "w") as f:
        json.dump(wr_out, f, separators=(',', ':'))
    return people_out, slug_studios, dir_out, wr_out

def build_data(entries, people, headshots, posters, slug_studios, directors_raw, writers_raw):
    # Per-slug metadata for clickable charts
    slug_meta = {}
    for e in entries:
        s = e["trakt_slug"]
        if not s or s in slug_meta: continue
        slug_meta[s] = {"t": e["show_title"] or e["title"], "type": "show" if e["type"] == "episode" else "movie",
                        "net": e.get("network",""), "ctry": e.get("country",""),
                        "lang": e.get("language",""), "g": e.get("genres",""), "stu": slug_studios.get(s,[])}
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

    # Time-to-watch: avg days between air date and first watch per show
    # Track first watch per episode (slug + season + episode_number)
    ep_first_watch = {}  # (show_slug, season, ep_num) -> {aired, watched, year}
    for e in entries:
        if e["type"] != "episode" or not e["show_title"] or not e["watched_at"]: continue
        fa = e.get("first_aired", "")
        if not fa: continue
        key = (e["trakt_slug"], e.get("season"), e.get("episode_number"))
        wa = e["watched_at"]
        # Keep earliest watch
        if key not in ep_first_watch or wa < ep_first_watch[key]["watched"]:
            ep_first_watch[key] = {"show": e["show_title"], "slug": e["trakt_slug"],
                                    "aired": fa, "watched": wa, "year": wa[:4]}

    # Aggregate by show: avg days
    show_ttw = defaultdict(lambda: {"name": "", "delays": [], "delays_y": defaultdict(list)})
    for key, info in ep_first_watch.items():
        try:
            aired = datetime.fromisoformat(info["aired"].replace("Z", "+00:00"))
            watched = datetime.fromisoformat(info["watched"].replace("Z", "+00:00"))
            days = (watched - aired).total_seconds() / 86400
            if days < 0: days = 0  # watched before air (timezone diff)
            if days > 365: continue  # skip old backfills
            show_ttw[info["slug"]]["name"] = info["show"]
            show_ttw[info["slug"]]["delays"].append(days)
            show_ttw[info["slug"]]["delays_y"][info["year"]].append(days)
        except: pass

    # Build ttw data: [{n, avg, count}] sorted by avg ascending (fastest first)
    ttw_all = []
    for slug, info in show_ttw.items():
        if len(info["delays"]) >= 3:  # need at least 3 episodes
            ttw_all.append({"n": info["name"], "avg": round(sum(info["delays"])/len(info["delays"]), 1),
                           "ct": len(info["delays"])})
    ttw_all.sort(key=lambda x: x["avg"])

    ttw_by_year = {}
    for slug, info in show_ttw.items():
        for yr, delays in info["delays_y"].items():
            if len(delays) >= 2:
                if yr not in ttw_by_year: ttw_by_year[yr] = []
                ttw_by_year[yr].append({"n": info["name"], "avg": round(sum(delays)/len(delays), 1),
                                        "ct": len(delays)})
    for yr in ttw_by_year:
        ttw_by_year[yr].sort(key=lambda x: x["avg"])

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
    genre_movie_y = defaultdict(Counter); genre_show_y = defaultdict(Counter)
    dwc = Counter(); dwn = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    hod = defaultdict(lambda: defaultdict(int))  # hour of day by year
    net_movies = Counter()  # count unique titles, not episodes
    net_shows = Counter()
    net_movies_y = defaultdict(Counter)
    net_shows_y = defaultdict(Counter)
    stu_movies = Counter()
    stu_shows = Counter()
    stu_movies_y = defaultdict(Counter)
    stu_shows_y = defaultdict(Counter)
    # Track which slug+year combos we've already counted for title-based counting
    seen_net = set()
    seen_stu = set()
    ctry_counter = Counter()
    ctry_counter_y = defaultdict(Counter)
    lang_counter = Counter()
    lang_counter_y = defaultdict(Counter)
    recent_all = []

    for e in entries:
        if not e["watched_at"]: continue
        m = e["watched_at"][:7]; y = e["watched_at"][:4]
        if e["type"] == "movie": monthly[m]["movies"] += 1; yearly[y]["movies"] += 1
        else: monthly[m]["episodes"] += 1; yearly[y]["episodes"] += 1
        yearly[y]["total"] += 1
        if e["genres"]:
            for g in e["genres"].split(", "):
                gs = g.strip()
                if e["type"] == "movie": genre_movie[gs] += 1; genre_movie_y[y][gs] += 1
                else: genre_show[gs] += 1; genre_show_y[y][gs] += 1
        # Networks: count unique titles (slug), not episodes
        slug = e["trakt_slug"]
        net_key = (slug, y)
        if e["network"] and net_key not in seen_net:
            seen_net.add(net_key)
            if e["type"] == "episode":
                net_shows[e["network"]] += 1
                net_shows_y[y][e["network"]] += 1
            # Movies don't typically have networks but just in case
        # Studios: count unique titles under EACH studio
        stu_list = slug_studios.get(slug, [])
        stu_key = (slug, y)
        if stu_list and stu_key not in seen_stu:
            seen_stu.add(stu_key)
            title_name = e["show_title"] or e["title"]
            for st in stu_list:
                if e["type"] == "movie":
                    stu_movies[st] += 1
                    stu_movies_y[y][st] += 1
                else:
                    stu_shows[st] += 1
                    stu_shows_y[y][st] += 1
        # Country and language: count unique titles
        ctry = e.get("country", "")
        lang = e.get("language", "")
        ctry_key = (slug, y, "c")
        lang_key = (slug, y, "l")
        if ctry and ctry_key not in seen_stu:
            seen_stu.add(ctry_key)
            ctry_counter[ctry] += 1
            ctry_counter_y[y][ctry] += 1
        if lang and lang_key not in seen_stu:
            seen_stu.add(lang_key)
            lang_counter[lang] += 1
            lang_counter_y[y][lang] += 1
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

    # Build director/writer lists with title indices
    def build_crew(crew_raw):
        cl = []
        for pid, info in crew_raw.items():
            tis = []; mc = sc = 0
            for ts in info["titles"]:
                for pre, typ in [("movie:", "movie"), ("show:", "show")]:
                    k = pre + ts
                    if k in ti: tis.append(ti[k]); mc += (1 if typ == "movie" else 0); sc += (1 if typ == "show" else 0)
            if mc + sc >= 2:
                cl.append({"n": info["name"], "m": mc, "s": sc, "tt": mc + sc, "ti": tis})
        cl.sort(key=lambda x: x["tt"], reverse=True)
        return cl

    dir_list = build_crew(directors_raw)
    wr_list = build_crew(writers_raw)

    return {
        "a": [p for p in pd if p["g"] == "m"],
        "x": [p for p in pd if p["g"] == "f"],
        "d": dir_list, "w": wr_list,
        "tl": tl, "hs": headshots, "ps": posters, "sm": slug_meta,
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
            "gm_y": {y: [{"genre": g, "count": c} for g, c in ct.most_common(20)] for y, ct in genre_movie_y.items()},
            "gs_y": {y: [{"genre": g, "count": c} for g, c in ct.most_common(20)] for y, ct in genre_show_y.items()},
            "ga_y": {y: [{"genre": g, "count": (genre_movie_y[y][g] + genre_show_y[y][g])} for g, _ in (genre_movie_y[y] + genre_show_y[y]).most_common(20)] for y in set(list(genre_movie_y) + list(genre_show_y))},
            "dw": [{"day": d, "count": dwc.get(d, 0)} for d in dwn],
            "hod": {str(h): hod_all.get(h, 0) for h in range(24)},
            "hod_y": hod_by_year,
            "net": [{"n": n, "s": net_shows[n]} for n in sorted(net_shows, key=net_shows.get, reverse=True)[:25]],
            "net_y": {y: [{"n": n, "s": ct[n]} for n in sorted(ct, key=ct.get, reverse=True)[:25]] for y, ct in net_shows_y.items()},
            "stu": [{"n": s, "m": stu_movies[s], "s": stu_shows[s]} for s in sorted(set(list(stu_movies)+list(stu_shows)), key=lambda x: stu_movies[x]+stu_shows[x], reverse=True)[:25]],
            "stu_y": {y: [{"n": s, "m": stu_movies_y[y][s], "s": stu_shows_y[y][s]} for s in sorted(set(list(stu_movies_y[y])+list(stu_shows_y[y])), key=lambda x: stu_movies_y[y][x]+stu_shows_y[y][x], reverse=True)[:25]] for y in set(list(stu_movies_y)+list(stu_shows_y))},
            "ctry": [{"n": c, "count": n} for c, n in ctry_counter.most_common(20)],
            "ctry_y": {y: [{"n": c, "count": n} for c, n in ct.most_common(20)] for y, ct in ctry_counter_y.items()},
            "lang": [{"n": l, "count": n} for l, n in lang_counter.most_common(20)],
            "lang_y": {y: [{"n": l, "count": n} for l, n in ct.most_common(20)] for y, ct in lang_counter_y.items()},
            "r": recent_all,
            "ttw": ttw_all[:25],
            "ttw_y": {y: v[:25] for y, v in ttw_by_year.items()},
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

os.makedirs("data", exist_ok=True)

# Cast+studios: only on full refresh (FULL_REFRESH=1) or when no people.json exists
do_cast = os.environ.get("FULL_REFRESH") == "1" or not os.path.exists("data/people.json")
if do_cast:
    print("\n[2/3] Fetching cast + studios + crew...")
    people, slug_studios, directors_raw, writers_raw = fetch_cast_and_studios(entries)
    with open("data/people.json", "w") as f:
        json.dump(people, f, separators=(',', ':'))
else:
    print("\n[2/3] Using cached cast + studios + crew (set FULL_REFRESH=1 to re-fetch)")
    with open("data/people.json") as f:
        people = json.load(f)
    slug_studios = {}
    if os.path.exists("data/studios.json"):
        with open("data/studios.json") as f:
            raw = json.load(f)
        for k, v in raw.items():
            slug_studios[k] = v if isinstance(v, list) else [v]
    directors_raw = {}
    if os.path.exists("data/directors.json"):
        with open("data/directors.json") as f: directors_raw = json.load(f)
    writers_raw = {}
    if os.path.exists("data/writers.json"):
        with open("data/writers.json") as f: writers_raw = json.load(f)

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
logos = {}
if os.path.exists("data/logos.json"):
    with open("data/logos.json") as f: logos = json.load(f)

print(f"\n[3/3] Building dashboard ({len(entries)} entries, {len(people)} people, {len(hs)} headshots, {len(ps)} posters)...")
data = build_data(entries, people, hs, ps, slug_studios, directors_raw, writers_raw)
data["lg"] = logos  # studio/network logos

data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
with open("templates/dashboard.html") as f:
    template = f.read()
html = template.replace("__DASHBOARD_DATA__", data_str)
html = html.replace("__BUILD_TIME__", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
with open("index.html", "w") as f:
    f.write(html)

print(f"  index.html: {len(html)//1024}KB")
print(f"  Actors: {len(data['a'])}, Actresses: {len(data['x'])}")
print(f"  Networks: {len(data['c']['net'])}, Studios: {len(data['c']['stu'])}")
print("Done!")
