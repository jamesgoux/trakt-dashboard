#!/usr/bin/env python3
"""
Refresh Trakt watch history and rebuild the dashboard HTML.
Reads headshots from data/headshots.json and posters from data/posters.json.
Outputs index.html for GitHub Pages.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, time, requests
from collections import defaultdict, Counter
from datetime import datetime
from utils import retry_request

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
USERNAME = os.environ.get("TRAKT_USERNAME")
BASE_URL = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE = "https://api.themoviedb.org/3"

def _slugify(name):
    """Convert a person name to a slug: 'Melanie Lynskey' -> 'melanie-lynskey'"""
    import re
    s = name.lower().strip()
    s = re.sub(r"['\"]", "", s)  # Remove apostrophes/quotes
    s = re.sub(r"[^a-z0-9]+", "-", s)  # Replace non-alphanumeric with hyphens
    return s.strip("-")

if not CLIENT_ID or not USERNAME:
    print("ERROR: Set TRAKT_CLIENT_ID and TRAKT_USERNAME"); exit(1)

def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def fetch_history(media_type):
    items = []; page = 1
    while True:
        r = retry_request("get", f"{BASE_URL}/users/{USERNAME}/history/{media_type}",
                         params={"page": page, "limit": 100, "extended": "full"}, headers=HEADERS)
        if not r or r.status_code != 200: break
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
            "country": m.get("country", ""), "language": m.get("language", ""),
            "trakt_rating": m.get("rating", "")}

def norm_show(e):
    s = e.get("show", {}); ep = e.get("episode", {}); ids = s.get("ids", {})
    return {"type": "episode", "watched_at": e.get("watched_at", ""), "title": ep.get("title", ""),
            "year": s.get("year", ""), "runtime": ep.get("runtime", ""),
            "genres": ", ".join(s.get("genres", [])), "trakt_slug": ids.get("slug", ""),
            "tmdb_id": ids.get("tmdb", ""),
            "show_title": s.get("title", ""), "season": ep.get("season", ""),
            "episode_number": ep.get("number", ""), "network": s.get("network", ""),
            "country": s.get("country", ""), "language": s.get("language", ""),
            "first_aired": ep.get("first_aired", ""),
            "trakt_rating": s.get("rating", "")}

def fetch_cast_and_studios(entries):
    show_slugs = set(); movie_slugs = set()
    slug_tmdb = {}  # slug -> (tmdb_id, is_show)
    # Build show → seasons → episodes map from user's watch history
    show_episodes = defaultdict(lambda: defaultdict(set))  # slug -> season -> set of episode nums
    ep_watch_year = {}  # (slug, season, episode) -> watch year
    for e in entries:
        if e["trakt_slug"]:
            is_show = e["type"] != "movie"
            (show_slugs if is_show else movie_slugs).add(e["trakt_slug"])
            if e.get("tmdb_id"):
                slug_tmdb[e["trakt_slug"]] = (str(e["tmdb_id"]), is_show)
            if is_show and e.get("season") and e.get("episode_number"):
                sn = int(e["season"]); en = int(e["episode_number"])
                show_episodes[e["trakt_slug"]][sn].add(en)
                wa = e.get("watched_at", "")
                if wa and len(wa) >= 4:
                    ep_watch_year[(e["trakt_slug"], sn, en)] = wa[:4]
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
    # Merge with existing studios too
    slug_studios = {}
    if os.path.exists("data/studios.json"):
        with open("data/studios.json") as f:
            raw = json.load(f)
        for k, v in raw.items():
            slug_studios[k] = v if isinstance(v, list) else [v]
    total = len(show_slugs) + len(movie_slugs); done = 0; skipped = 0; tmdb_ok = 0; trakt_fallback = 0
    slug_people_count = Counter()
    for pid, info in people.items():
        for t in info["titles"]:
            slug_people_count[t] += 1
    all_slugs = [(s, "shows") for s in show_slugs] + [(s, "movies") for s in movie_slugs]
    for slug, kind in all_slugs:
        # Skip if we have >=15 people AND studios (TMDB gives more, so raise threshold)
        if slug_people_count.get(slug, 0) >= 15 and slug in slug_studios:
            done += 1; skipped += 1; continue
        fetched = False
        # Try TMDB first (richer cast data: 30-50+ vs Trakt's 5-10)
        tmdb_info = slug_tmdb.get(slug)
        if TMDB_API_KEY and tmdb_info:
            tmdb_id, is_show = tmdb_info
            tmdb_type = "tv" if is_show else "movie"
            try:
                tr = retry_request("get", f"{TMDB_BASE}/{tmdb_type}/{tmdb_id}/credits?api_key={TMDB_API_KEY}", timeout=10)
                if tr and tr.status_code == 200:
                    data = tr.json()
                    # Cast (limit to top 40 billed)
                    for c in sorted(data.get("cast", []), key=lambda x: x.get("order", 999))[:40]:
                        name = c.get("name", "")
                        if not name: continue
                        pid = _slugify(name)
                        if not pid: continue
                        people[pid]["name"] = name
                        # TMDB gender: 1=female, 2=male, 0/3=other
                        g = c.get("gender", 0)
                        if g in (1, 2): people[pid]["gender"] = g
                        people[pid]["titles"].add(slug)
                    # Crew: directors + writers
                    for c in data.get("crew", []):
                        name = c.get("name", "")
                        if not name: continue
                        pid = _slugify(name)
                        if not pid: continue
                        job = c.get("job", "")
                        dept = c.get("department", "")
                        if dept == "Directing" and job in ("Director", "Co-Director"):
                            directors[pid]["name"] = name
                            directors[pid]["titles"].add(slug)
                        elif dept == "Writing" and job in ("Writer", "Screenplay", "Author", "Original Story", "Story", "Novel"):
                            writers[pid]["name"] = name
                            writers[pid]["titles"].add(slug)
                    fetched = True; tmdb_ok += 1
            except Exception as e:
                pass
            time.sleep(0.05)  # TMDB rate limit: ~40/sec
        # Fallback to Trakt if TMDB didn't work
        if not fetched:
            try:
                r = retry_request("get", f"{BASE_URL}/{kind}/{slug}/people?extended=full", headers=HEADERS, timeout=10)
                if r and r.status_code == 200:
                    for c in r.json().get("cast", []):
                        p = c.get("person", {}); pid = p.get("ids", {}).get("slug", "")
                        if pid:
                            people[pid]["name"] = p.get("name", "")
                            if p.get("gender") is not None: people[pid]["gender"] = p.get("gender")
                            people[pid]["titles"].add(slug)
                    crew = r.json().get("crew", {})
                    for cp in crew.get("directing", []):
                        if set(cp.get("jobs", [])) & {"Director", "Co-Director"}:
                            pid2 = cp.get("person", {}).get("ids", {}).get("slug", "")
                            if pid2: directors[pid2]["name"] = cp["person"].get("name", ""); directors[pid2]["titles"].add(slug)
                    for cp in crew.get("writing", []):
                        if set(cp.get("jobs", [])) & {"Writer", "Screenplay", "Author", "Original Story", "Story"}:
                            pid2 = cp.get("person", {}).get("ids", {}).get("slug", "")
                            if pid2: writers[pid2]["name"] = cp["person"].get("name", ""); writers[pid2]["titles"].add(slug)
                    trakt_fallback += 1
            except Exception: pass
        # Fetch studios from Trakt (TMDB doesn't have good studio data)
        try:
            r2 = retry_request("get", f"{BASE_URL}/{kind}/{slug}/studios", headers=HEADERS, timeout=5)
            if r2 and r2.status_code == 200:
                st = r2.json()
                if st:
                    names = [s["name"] for s in st]
                    existing_st = set(slug_studios.get(slug, []))
                    existing_st.update(names)
                    slug_studios[slug] = list(existing_st)
        except Exception: pass
        done += 1
        if done % 100 == 0:
            print(f"  cast+studios: {done}/{total} (skipped {skipped}, TMDB: {tmdb_ok}, Trakt: {trakt_fallback})")
            _p = {pid: {"name": i["name"], "gender": i["gender"], "titles": list(i["titles"])} for pid, i in people.items()}
            with open("data/people.json", "w") as f: json.dump(_p, f, separators=(',', ':'))
            with open("data/studios.json", "w") as f: json.dump(slug_studios, f, separators=(',', ':'))
            time.sleep(0.8)  # respect Trakt rate limits (0.3 caused frequent 429s)
    print(f"  people: {len(people)}, studios: {len(slug_studios)}, directors: {len(directors)}, writers: {len(writers)}")
    print(f"  Sources: TMDB={tmdb_ok}, Trakt fallback={trakt_fallback}, Skipped={skipped}")

    # === EPISODE-LEVEL CREDITS: fetch per-season cast from TMDB ===
    # This gives accurate episode counts per person per show
    ep_credits = defaultdict(lambda: defaultdict(set))  # person_slug -> show_slug -> set of (s,e,year) tuples
    # Load cached season credits (avoid re-fetching from TMDB)
    season_cache_path = "data/season_credits.json"
    season_cache = {}
    if os.path.exists(season_cache_path):
        with open(season_cache_path) as f:
            season_cache = json.load(f)

    if TMDB_API_KEY and show_episodes:
        season_count = sum(len(seasons) for seasons in show_episodes.values())
        cached_count = 0; fetched_count = 0
        print(f"\n  Episode-level credits for {len(show_episodes)} shows, {season_count} seasons...")

        for slug, seasons in show_episodes.items():
            tmdb_info = slug_tmdb.get(slug)
            if not tmdb_info: continue
            tmdb_id, _ = tmdb_info
            for season_num, ep_nums in seasons.items():
                cache_key = f"{tmdb_id}|{season_num}"
                # Use cache if available
                if cache_key in season_cache:
                    sdata = season_cache[cache_key]
                    cached_count += 1
                else:
                    # Fetch from TMDB
                    try:
                        url = f"{TMDB_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}&append_to_response=credits"
                        sr = retry_request("get", url, timeout=10)
                        if not sr or sr.status_code != 200: continue
                        sdata = sr.json()
                        # Cache: store only cast/guest_stars (not full episode data)
                        season_cache[cache_key] = {
                            "credits": {"cast": [{"name": c.get("name",""), "gender": c.get("gender",0)} for c in sdata.get("credits",{}).get("cast",[])]},
                            "episodes": [{"episode_number": ep.get("episode_number"), "guest_stars": [{"name": gs.get("name",""), "gender": gs.get("gender",0)} for gs in ep.get("guest_stars",[])]} for ep in sdata.get("episodes",[])]
                        }
                        fetched_count += 1
                        if fetched_count % 50 == 0:
                            print(f"  fetched {fetched_count} seasons (cached {cached_count})...")
                            with open(season_cache_path, "w") as f:
                                json.dump(season_cache, f, separators=(',', ':'))
                        time.sleep(0.05)
                    except Exception:
                        continue

                # Process season data (from cache or fresh fetch)
                season_cast = sdata.get("credits", {}).get("cast", [])
                for c in season_cast:
                    pid = _slugify(c.get("name", ""))
                    if not pid: continue
                    for ep_num in ep_nums:
                        wy = ep_watch_year.get((slug, season_num, ep_num), "")
                        ep_credits[pid][slug].add((season_num, ep_num, wy))
                    # Always add show to person's titles (even if person already exists)
                    people[pid]["titles"].add(slug)
                    if not people[pid]["name"]:
                        people[pid]["name"] = c.get("name", "")
                        g = c.get("gender", 0)
                        if g in (1, 2): people[pid]["gender"] = g
                for ep_data in sdata.get("episodes", []):
                    ep_num = ep_data.get("episode_number")
                    if ep_num not in ep_nums: continue
                    for gs in ep_data.get("guest_stars", []):
                        pid = _slugify(gs.get("name", ""))
                        if not pid: continue
                        wy = ep_watch_year.get((slug, season_num, ep_num), "")
                        ep_credits[pid][slug].add((season_num, ep_num, wy))
                        # Always add show to person's titles
                        people[pid]["titles"].add(slug)
                        if not people[pid]["name"]:
                            people[pid]["name"] = gs.get("name", "")
                            g = gs.get("gender", 0)
                            if g in (1, 2): people[pid]["gender"] = g
                            people[pid]["titles"].add(slug)

        # Save cache
        with open(season_cache_path, "w") as f:
            json.dump(season_cache, f, separators=(',', ':'))
        print(f"  Episode credits: {len(ep_credits)} people (fetched {fetched_count}, cached {cached_count})")

    # Build ep_credits output: person_slug -> {show_slug: [[s,e],[s,e],...]}
    ep_credits_out = {}
    for pid, shows in ep_credits.items():
        ep_credits_out[pid] = {slug: sorted([list(t) for t in eps]) for slug, eps in shows.items()}

    people_out = {pid: {"name": i["name"], "gender": i["gender"], "titles": list(i["titles"])} for pid, i in people.items()}
    # Add ep_credits to people_out
    for pid in people_out:
        if pid in ep_credits_out:
            people_out[pid]["eps"] = ep_credits_out[pid]
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
            tw[k]["runtime"] = safe_int(e["runtime"]) if e["runtime"] else 0
            if wy: tw[k]["eby"][wy] += 1
            tw[k]["total"] += 1
        else:
            k = f"show:{s}"; tw[k]["type"] = "show"; tw[k]["title"] = e["show_title"]
            tw[k]["year"] = str(e["year"]) if e["year"] else ""
            if wy: tw[k]["eby"][wy] += 1
            tw[k]["total"] += 1
            if e["runtime"]: tw[k]["runtime"] = safe_int(e["runtime"])
    tl = []; ti = {}
    for k, t in tw.items():
        ti[k] = len(tl)
        slug = k.split(":", 1)[1] if ":" in k else ""
        tl.append({"t":t["title"],"type":t["type"],"yr":t["year"],"eby":dict(t["eby"]),"tot":t["total"],"sl":slug})

    # People — use episode-level credits (eps) for accurate show counts
    ism = lambda g: g in (2, 'male'); isf = lambda g: g in (1, 'female')
    pd = []
    for pid, info in people.items():
        if not ism(info["gender"]) and not isf(info["gender"]): continue
        tis = []; mc = sc = 0
        max_recency = 0
        person_eps = info.get("eps", {})  # show_slug -> [[s,e],[s,e],...]
        for ts in info["titles"]:
            rec = slug_recency.get(ts, 0)
            if rec > max_recency: max_recency = rec
            mk = "movie:" + ts
            if mk in ti:
                tis.append(ti[mk]); mc += 1
            sk = "show:" + ts
            if sk in ti:
                tis.append(ti[sk])
                sc += 1  # Count 1 per show for ranking (episode detail shown on click)
        if mc + sc >= 2:
            entry = {"n": info["name"], "g": "m" if ism(info["gender"]) else "f", "m": mc, "s": sc, "tt": mc+sc, "ti": tis, "_rec": max_recency}
            # Add episode credits as year-counts: {slug: {year: count}} — compact for bandwidth
            if person_eps:
                eps_yc = {}
                for slug, ep_list in person_eps.items():
                    yc = defaultdict(int)
                    for ep in ep_list:
                        yr = ep[2] if len(ep) > 2 else ""
                        if yr: yc[yr] += 1
                    total_eps_count = len(ep_list)
                    eps_yc[slug] = {"t": total_eps_count, "y": dict(yc)} if yc else {"t": total_eps_count}
                entry["eps"] = eps_yc
            pd.append(entry)
    pd.sort(key=lambda x: (x["tt"], x["_rec"]), reverse=True)
    for p in pd: del p["_rec"]

    # Show year data
    syd = defaultdict(lambda: {"name": "", "yd": defaultdict(lambda: {"e": 0, "m": 0}), "net": ""})
    for e in entries:
        if e["type"] == "episode" and e["show_title"] and e["watched_at"]:
            s = e["trakt_slug"]; yr = e["watched_at"][:4]
            syd[s]["name"] = e["show_title"]; syd[s]["yd"][yr]["e"] += 1
            if e["runtime"]: syd[s]["yd"][yr]["m"] += safe_int(e["runtime"])
            if e["network"]: syd[s]["net"] = e["network"]

    # Time-to-watch: avg days between air date and watch date, at SEASON level
    # Group episodes by (show, season), compute per-season delay
    season_eps = defaultdict(list)  # (slug, season) -> [{aired, watched, year, show}]
    for e in entries:
        if e["type"] != "episode" or not e["show_title"] or not e["watched_at"]: continue
        fa = e.get("first_aired", "")
        if not fa or not e.get("season"): continue
        season_eps[(e["trakt_slug"], str(e["season"]))].append({
            "show": e["show_title"], "slug": e["trakt_slug"],
            "aired": fa, "watched": e["watched_at"], "year": e["watched_at"][:4],
            "season": str(e["season"])
        })

    # Compute per-season delay
    season_delays = []
    for (slug, sn), eps in season_eps.items():
        delays = []
        for ep in eps:
            try:
                aired = datetime.fromisoformat(ep["aired"].replace("Z", "+00:00"))
                watched = datetime.fromisoformat(ep["watched"].replace("Z", "+00:00"))
                days = (watched - aired).total_seconds() / 86400
                if days < 0: days = 0
                delays.append(days)
            except Exception: pass
        if not delays or len(delays) < 4: continue
        avg_delay = sum(delays) / len(delays)
        watch_year = max(ep["year"] for ep in eps if ep.get("year"))
        # Exclude June 2016 bulk import
        if watch_year == "2016" and any(ep["watched"][:7] == "2016-06" for ep in eps if ep.get("watched")):
            continue
        season_delays.append({
            "show": eps[0]["show"], "slug": slug, "season": sn,
            "delay": round(avg_delay, 1), "eps": len(delays), "year": watch_year
        })

    # Split: TTW filters out <1 day (bulk imports), catch-up does NOT
    ttw_all = []
    catchup_all = []
    for sd in season_delays:
        label = sd["show"] + " S" + sd["season"].zfill(2)
        if sd["delay"] > 365:
            catchup_all.append({"n": label, "avg": round(sd["delay"] / 365, 1), "ct": sd["eps"]})
        elif sd["delay"] >= 1.0:
            ttw_all.append({"n": label, "avg": sd["delay"], "ct": sd["eps"]})

    ttw_all.sort(key=lambda x: x["avg"])
    catchup_all.sort(key=lambda x: x["avg"], reverse=True)  # longest first

    # Per-year breakdowns
    ttw_by_year = defaultdict(list)
    catchup_by_year = defaultdict(list)
    for sd in season_delays:
        label = sd["show"] + " S" + sd["season"].zfill(2)
        yr = sd["year"]
        if sd["delay"] > 365:
            catchup_by_year[yr].append({"n": label, "avg": round(sd["delay"] / 365, 1), "ct": sd["eps"]})
        elif sd["delay"] >= 1.0:
            ttw_by_year[yr].append({"n": label, "avg": sd["delay"], "ct": sd["eps"]})
        else:
            catchup_by_year[yr].append({"n": label, "avg": round(sd["delay"] / 365, 1), "ct": sd["eps"]})
    for yr in ttw_by_year: ttw_by_year[yr].sort(key=lambda x: x["avg"])
    for yr in catchup_by_year: catchup_by_year[yr].sort(key=lambda x: x["avg"], reverse=True)

    # Content vintage: count unique titles by their release year (not watch year)
    vintage_movies = Counter()  # release_year -> count of unique movie titles
    vintage_shows = Counter()   # release_year -> count of unique show titles
    vintage_seen = set()
    for e in entries:
        ry = str(e.get("year", ""))
        if not ry: continue
        wy = e["watched_at"][:4] if e["watched_at"] else ""
        # Use slug if available, else title+year for dedup
        vid = e["trakt_slug"] if e["trakt_slug"] else (e.get("title","") + "|" + ry)
        if not vid: continue
        vkey = (vid, wy)
        if vkey not in vintage_seen:
            vintage_seen.add(vkey)
            if e["type"] == "movie":
                vintage_movies[ry] += 1
            elif e.get("show_title"):
                vintage_shows[ry] += 1

    # Build vintage data grouped by decade for cleaner display
    all_vy = sorted(set(list(vintage_movies) + list(vintage_shows)))
    vintage_data = [{"yr": y, "m": vintage_movies.get(y, 0), "s": vintage_shows.get(y, 0)} for y in all_vy if int(y) >= 1920]

    # Also per watch-year
    vintage_by_wy = defaultdict(lambda: {"movies": Counter(), "shows": Counter(), "seen": set()})
    for e in entries:
        ry = str(e.get("year", ""))
        if not ry or not e["trakt_slug"] or not e["watched_at"]: continue
        wy = e["watched_at"][:4]
        vkey = (e["trakt_slug"], wy)
        if vkey not in vintage_by_wy[wy]["seen"]:
            vintage_by_wy[wy]["seen"].add(vkey)
            if e["type"] == "movie":
                vintage_by_wy[wy]["movies"][ry] += 1
            elif e["show_title"]:
                vintage_by_wy[wy]["shows"][ry] += 1

    vintage_by_year = {}
    for wy, data in vintage_by_wy.items():
        all_y = sorted(set(list(data["movies"]) + list(data["shows"])))
        vintage_by_year[wy] = [{"yr": y, "m": data["movies"].get(y, 0), "s": data["shows"].get(y, 0)} for y in all_y if int(y) >= 1920]

    # Movie year data
    myd = defaultdict(lambda: {"name": "", "yr": "", "rt": 0, "yd": defaultdict(int)})
    for e in entries:
        if e["type"] == "movie" and e["title"] and e["watched_at"]:
            k = e["title"]; yr = e["watched_at"][:4]
            myd[k]["name"] = e["title"]; myd[k]["yr"] = str(e["year"]) if e["year"] else ""
            if e["runtime"]: myd[k]["rt"] = safe_int(e["runtime"])
            myd[k]["yd"][yr] += 1

    # Charts
    monthly = defaultdict(lambda: {"movies": 0, "episodes": 0, "rt": 0, "rt_m": 0, "rt_s": 0})
    yearly = defaultdict(lambda: {"movies": 0, "episodes": 0, "total": 0})
    genre_movie = Counter(); genre_show = Counter()
    genre_movie_y = defaultdict(Counter); genre_show_y = defaultdict(Counter)
    genre_titles = {}  # genre -> {"m": [movie titles], "s": [show titles]}
    dwc = Counter(); dwc_m = Counter(); dwc_s = Counter(); dwn = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    dwc_y = defaultdict(Counter)  # year -> day -> count
    dwc_my = defaultdict(Counter)  # year -> day -> movie count
    dwc_sy = defaultdict(Counter)  # year -> day -> show count
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
    ctry_movies = Counter(); ctry_shows = Counter()
    lang_counter = Counter()
    lang_counter_y = defaultdict(Counter)
    lang_movies = Counter(); lang_shows = Counter()
    recent_all = []

    for e in entries:
        if not e["watched_at"]: continue
        m = e["watched_at"][:7]; y = e["watched_at"][:4]
        rt = safe_int(e["runtime"]) if e["runtime"] else 0
        if e["type"] == "movie":
            monthly[m]["movies"] += 1; yearly[y]["movies"] += 1
            monthly[m]["rt"] += rt; monthly[m]["rt_m"] += rt
        else:
            monthly[m]["episodes"] += 1; yearly[y]["episodes"] += 1
            monthly[m]["rt"] += rt; monthly[m]["rt_s"] += rt
        yearly[y]["total"] += 1
        if e["genres"]:
            slug = e["trakt_slug"]
            title_name = e.get("show_title") or e.get("title") or ""
            for g in e["genres"].split(", "):
                gs = g.strip()
                if e["type"] == "movie":
                    genre_movie[gs] += 1; genre_movie_y[y][gs] += 1
                    gtkey = (gs, "m", title_name)
                    if gtkey not in seen_net and title_name:
                        seen_net.add(gtkey)
                        if gs not in genre_titles: genre_titles[gs] = {"m": [], "s": []}
                        genre_titles[gs]["m"].append({"t": title_name, "y": y})
                else:
                    gkey = (slug, gs, y)
                    if gkey not in seen_net:
                        seen_net.add(gkey)
                        genre_show[gs] += 1; genre_show_y[y][gs] += 1
                    gtkey = (gs, "s", title_name)
                    if gtkey not in seen_net and title_name:
                        seen_net.add(gtkey)
                        if gs not in genre_titles: genre_titles[gs] = {"m": [], "s": []}
                        genre_titles[gs]["s"].append({"t": title_name, "y": y})
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
            if e["type"] == "movie": ctry_movies[ctry] += 1
            else: ctry_shows[ctry] += 1
        if lang and lang_key not in seen_stu:
            seen_stu.add(lang_key)
            lang_counter[lang] += 1
            lang_counter_y[y][lang] += 1
            if e["type"] == "movie": lang_movies[lang] += 1
            else: lang_shows[lang] += 1
        try:
            dt = datetime.fromisoformat(e["watched_at"].replace("Z", "+00:00"))
            # Convert UTC to Pacific time (UTC-8 PST / UTC-7 PDT)
            from zoneinfo import ZoneInfo
            dt_local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
            dw_name = dwn[dt_local.weekday()]
            dwc_y[y][dw_name] += 1
            # All-time counters exclude June 2016 bulk-import day
            m_check = e["watched_at"][:7] if e["watched_at"] else ""
            if m_check != "2016-06":
                dwc[dw_name] += 1
                if e["type"] == "movie": dwc_m[dw_name] += 1
                else: dwc_s[dw_name] += 1
            # Per-year counters always include
            if e["type"] == "movie": dwc_my[y][dw_name] += 1
            else: dwc_sy[y][dw_name] += 1
            h_key = f"{dt_local.hour}_{e['type']}"
            hod[y][h_key] += 1
        except Exception: pass

    # Build season-level data: group episodes by show+season, assign to completion month
    season_data = defaultdict(lambda: {"eps": 0, "months": set()})  # (show, season) -> data
    movie_month = defaultdict(lambda: defaultdict(int))  # month -> movie -> count
    for e in entries:
        if not e["watched_at"]: continue
        m = e["watched_at"][:7]
        if e["type"] == "episode" and e.get("show_title") and e.get("season"):
            key = (e["show_title"], str(e["season"]))
            season_data[key]["eps"] += 1
            season_data[key]["months"].add(m)
        elif e["type"] == "movie" or (e["type"] == "episode" and not e.get("season")):
            name = e.get("show_title") or e.get("title") or ""
            etype = "movie" if e["type"] == "movie" else "show"
            if name:
                mkey = (m, name, etype)
                movie_month[mkey] = movie_month.get(mkey, 0) + 1

    # Assign each season to its completion month (last month with a watched episode)
    # Also count seasons per month and year for the timeline bars
    season_by_month = defaultdict(list)  # month -> [{t, type, c}]
    season_count_monthly = Counter()  # month -> season count
    season_count_yearly = Counter()   # year -> season count
    for (show, sn), data in season_data.items():
        completion_month = sorted(data["months"])[-1]  # last month
        label = show + " S" + sn.zfill(2)
        season_by_month[completion_month].append({"t": label, "type": "show", "c": data["eps"]})
        season_count_monthly[completion_month] += 1
        season_count_yearly[completion_month[:4]] += 1

    # Add season counts to monthly/yearly chart data
    for m in monthly:
        monthly[m]["seasons"] = season_count_monthly.get(m, 0)
    for y in yearly:
        yearly[y]["seasons"] = season_count_yearly.get(y, 0)

    # Build mt_out: seasons (at completion month) + movies + seasonless episodes
    mt_out = {}
    # Group movie_month by month
    mm_by_month = defaultdict(list)
    for (m, name, etype), count in movie_month.items():
        mm_by_month[m].append({"t": name, "type": etype, "c": count})
    all_months = set(list(season_by_month.keys()) + list(mm_by_month.keys()))
    for m in all_months:
        items = list(season_by_month.get(m, []))
        items.extend(mm_by_month.get(m, []))
        items.sort(key=lambda x: x["c"], reverse=True)
        mt_out[m] = items[:25]

    # Episode watch chart: per-month episodes by show (top shows get their own color)
    ep_by_month = defaultdict(lambda: defaultdict(int))  # month -> show -> count
    for e in entries:
        if e["type"] != "episode" or not e.get("watched_at") or not e.get("show_title"): continue
        m = e["watched_at"][:7]
        ep_by_month[m][e["show_title"]] += 1
    # Build: for each month, top shows + "other"
    ep_top_shows = Counter()
    for m, shows in ep_by_month.items():
        for s, c in shows.items():
            ep_top_shows[s] += c
    ep_legend = [s for s, _ in ep_top_shows.most_common(8)]
    ep_chart = {}
    for m in sorted(ep_by_month.keys()):
        row = {}
        other = 0
        for s, c in ep_by_month[m].items():
            if s in ep_legend:
                row[s] = c
            else:
                other += c
        if other:
            row["Other"] = other
        ep_chart[m] = row

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

    # First watches: earliest entries per year (so year filter works)
    first_all = []
    sorted_oldest = sorted(entries, key=lambda x: x["watched_at"])
    first_by_year = defaultdict(list)
    for e in sorted_oldest:
        if not e["watched_at"]: continue
        yr = e["watched_at"][:4]
        if len(first_by_year[yr]) < 10:
            entry = {
                "type": e["type"],
                "title": e["show_title"] or e["title"],
                "detail": f"S{e['season']}E{e['episode_number']}" if e["type"] == "episode" else str(e["year"]),
                "watched_at": e["watched_at"][:10],
                "yr": yr
            }
            first_by_year[yr].append(entry)
            first_all.append(entry)

    ml = [e for e in entries if e["type"] == "movie"]
    el = [e for e in entries if e["type"] == "episode"]
    tr = sum(safe_int(e["runtime"]) for e in entries if e["runtime"])
    tr_movies = sum(safe_int(e["runtime"]) for e in ml if e["runtime"])
    tr_shows = sum(safe_int(e["runtime"]) for e in el if e["runtime"])

    # Rating lists — include watch years so JS can filter
    movie_ratings = {}
    for e in entries:
        if e["type"] == "movie" and e["title"] and e.get("trakt_rating"):
            try:
                r = safe_float(e["trakt_rating"])
                wy = e["watched_at"][:4] if e["watched_at"] else ""
                if r > 0:
                    if e["title"] not in movie_ratings:
                        movie_ratings[e["title"]] = {"t": e["title"], "yr": str(e["year"]) if e["year"] else "", "r": round(r, 1), "wy": set()}
                    if wy: movie_ratings[e["title"]]["wy"].add(wy)
            except Exception: pass
    for v in movie_ratings.values(): v["wy"] = sorted(v["wy"])
    movies_by_community = sorted(movie_ratings.values(), key=lambda x: x["r"], reverse=True)

    # Highest/lowest rated TV shows by Trakt community
    show_ratings = {}
    for e in entries:
        if e["type"] == "episode" and e["show_title"] and e.get("trakt_rating"):
            try:
                r = safe_float(e["trakt_rating"])
                wy = e["watched_at"][:4] if e["watched_at"] else ""
                if r > 0:
                    if e["show_title"] not in show_ratings:
                        show_ratings[e["show_title"]] = {"t": e["show_title"], "yr": str(e["year"]) if e["year"] else "", "r": round(r, 1), "wy": set()}
                    if wy: show_ratings[e["show_title"]]["wy"].add(wy)
            except Exception: pass
    for v in show_ratings.values(): v["wy"] = sorted(v["wy"])
    shows_by_community = sorted(show_ratings.values(), key=lambda x: x["r"], reverse=True)

    # Hour of day aggregate (all time) — split by movie/episode, skip June 2016 bulk-import
    hod_movies = Counter()
    hod_episodes = Counter()
    for y, yr_data in hod.items():
        if y == "2016":
            # Only skip June 2016 data, keep rest of 2016
            continue  # TODO: per-month hod tracking needed for finer exclusion
        for k, c in yr_data.items():
            h, typ = k.rsplit("_", 1)
            if typ == "movie": hod_movies[int(h)] += c
            else: hod_episodes[int(h)] += c
    hod_all = {str(h): {"m": hod_movies.get(h, 0), "e": hod_episodes.get(h, 0)} for h in range(24)}
    hod_by_year = {}
    for y, yr_data in hod.items():
        ym = Counter(); ye = Counter()
        for k, c in yr_data.items():
            h, typ = k.rsplit("_", 1)
            if typ == "movie": ym[int(h)] += c
            else: ye[int(h)] += c
        hod_by_year[y] = {str(h): {"m": ym.get(h, 0), "e": ye.get(h, 0)} for h in range(24)}

    # Build director/writer lists with title indices
    def build_crew(crew_raw):
        cl = []
        for pid, info in crew_raw.items():
            tis = []; mc = sc = 0
            max_rec = 0
            for ts in info["titles"]:
                rec = slug_recency.get(ts, 0)
                if rec > max_rec: max_rec = rec
                for pre, typ in [("movie:", "movie"), ("show:", "show")]:
                    k = pre + ts
                    if k in ti: tis.append(ti[k]); mc += (1 if typ == "movie" else 0); sc += (1 if typ == "show" else 0)
            if mc + sc >= 2:
                cl.append({"n": info["name"], "m": mc, "s": sc, "tt": mc + sc, "ti": tis, "_rec": max_rec})
        cl.sort(key=lambda x: (x["tt"], x["_rec"]), reverse=True)
        for c in cl: del c["_rec"]
        return cl

    # Genre trends: year-over-year + month-over-month data for top genres
    genre_monthly = defaultdict(Counter)  # month -> genre -> count
    for e in entries:
        if not e["watched_at"] or not e["genres"]: continue
        mo = e["watched_at"][:7]
        for g in e["genres"].split(", "):
            genre_monthly[mo][g.strip()] += 1

    def _build_genre_trends(gm_y, gs_y):
        all_years = sorted(set(list(gm_y) + list(gs_y)))
        all_years = [y for y in all_years if int(y) >= 2012]
        total = Counter()
        for y in all_years:
            for g, c in (gm_y[y] + gs_y[y]).items():
                total[g] += c
        top_genres = [g for g, _ in total.most_common(12)]
        series = {}
        for g in top_genres:
            series[g] = []
            for y in all_years:
                series[g].append(gm_y[y].get(g, 0) + gs_y[y].get(g, 0))
        # Monthly breakdowns per year for filtered view
        monthly = {}
        for y in all_years:
            months = sorted([m for m in genre_monthly if m.startswith(y)])
            if not months: continue
            mseries = {}
            for g in top_genres:
                mseries[g] = [genre_monthly[m].get(g, 0) for m in months]
            monthly[y] = {"months": months, "data": mseries}
        return {"years": all_years, "genres": top_genres, "data": series, "monthly": monthly}

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
                  "total_runtime_days": round(tr/60/24, 1),
                  "movie_runtime_days": round(tr_movies/60/24, 1),
                  "show_runtime_days": round(tr_shows/60/24, 1)},
            "m": [{"month": m, **d} for m, d in sorted(monthly.items())],
            "y": [{"year": y, **d} for y, d in sorted(yearly.items())],
            "con_y": {},  # placeholder, filled below
            "th_y": {},   # placeholder, filled below
            "gm": [{"genre": g, "count": c} for g, c in genre_movie.most_common(20)],
            "gs": [{"genre": g, "count": c} for g, c in genre_show.most_common(20)],
            "ga": [{"genre": g, "count": genre_movie[g] + genre_show[g], "m": genre_movie[g], "s": genre_show[g]}
                   for g, _ in (genre_movie + genre_show).most_common(20)],
            "gt_titles": {g: {"m": v["m"][:20], "s": v["s"][:20]} for g, v in genre_titles.items()},
            "gm_y": {y: [{"genre": g, "count": c} for g, c in ct.most_common(20)] for y, ct in genre_movie_y.items()},
            "gs_y": {y: [{"genre": g, "count": c} for g, c in ct.most_common(20)] for y, ct in genre_show_y.items()},
            "ga_y": {y: [{"genre": g, "count": (genre_movie_y[y][g] + genre_show_y[y][g]), "m": genre_movie_y[y][g], "s": genre_show_y[y][g]} for g, _ in (genre_movie_y[y] + genre_show_y[y]).most_common(20)] for y in set(list(genre_movie_y) + list(genre_show_y))},
            "gt": _build_genre_trends(genre_movie_y, genre_show_y),
            "dw": [{"day": d, "count": dwc.get(d, 0), "m": dwc_m.get(d, 0), "s": dwc_s.get(d, 0)} for d in dwn],
            "dw_y": {y: [{"day": d, "count": dwc_y[y].get(d, 0), "m": dwc_my[y].get(d, 0), "s": dwc_sy[y].get(d, 0)} for d in dwn] for y in dwc_y},
            "hod": hod_all,
            "hod_y": hod_by_year,
            "net": [{"n": n, "s": net_shows[n]} for n in sorted(net_shows, key=net_shows.get, reverse=True)[:25]],
            "net_y": {y: [{"n": n, "s": ct[n]} for n in sorted(ct, key=ct.get, reverse=True)[:25]] for y, ct in net_shows_y.items()},
            "stu": [{"n": s, "m": stu_movies[s], "s": stu_shows[s]} for s in sorted(set(list(stu_movies)+list(stu_shows)), key=lambda x: stu_movies[x]+stu_shows[x], reverse=True)[:25]],
            "stu_y": {y: [{"n": s, "m": stu_movies_y[y][s], "s": stu_shows_y[y][s]} for s in sorted(set(list(stu_movies_y[y])+list(stu_shows_y[y])), key=lambda x: stu_movies_y[y][x]+stu_shows_y[y][x], reverse=True)[:25]] for y in set(list(stu_movies_y)+list(stu_shows_y))},
            "ctry": [{"n": c, "count": n, "m": ctry_movies[c], "s": ctry_shows[c]} for c, n in ctry_counter.most_common(20)],
            "ctry_y": {y: [{"n": c, "count": n} for c, n in ct.most_common(20)] for y, ct in ctry_counter_y.items()},
            "lang": [{"n": l, "count": n, "m": lang_movies[l], "s": lang_shows[l]} for l, n in lang_counter.most_common(20)],
            "lang_y": {y: [{"n": l, "count": n} for l, n in ct.most_common(20)] for y, ct in lang_counter_y.items()},
            "r": recent_all,
            "f": first_all,
            "mt": mt_out,
            "epc": ep_chart,
            "epl": ep_legend,
            "ttw": ttw_all[:25],
            "ttw_y": {y: v[:25] for y, v in ttw_by_year.items()},
            "cup": catchup_all,
            "cup_y": {y: v for y, v in catchup_by_year.items()},
            "vy": vintage_data,
            "vy_y": vintage_by_year,
            "mch": movies_by_community,
            "mcl": list(reversed(movies_by_community)) if movies_by_community else [],
            "sch": shows_by_community,
            "scl": list(reversed(shows_by_community)) if shows_by_community else [],
        }
    }

# ---- Main ----
print("=== Trakt Data Refresh ===")

print("\n[1/3] Fetching watch history...")
raw_movies = fetch_history("movies")
raw_shows = fetch_history("shows")
entries = [norm_movie(e) for e in raw_movies] + [norm_show(e) for e in raw_shows]
entries.sort(key=lambda x: x["watched_at"], reverse=True)
print(f"  Total: {len(entries)} entries (Trakt)")

# ── Letterboxd backfill: merge old watches (2015-2022) not in Trakt ──
if os.path.exists("data/letterboxd.json"):
    with open("data/letterboxd.json") as f:
        lb_data = json.load(f)
    
    # Build lookup: (title_lower, year) -> set of watched dates from Trakt
    trakt_watches = defaultdict(set)
    for e in entries:
        if e["type"] == "movie" and e["title"] and e["watched_at"]:
            key = (e["title"].lower(), str(e.get("year", "")))
            trakt_watches[key].add(e["watched_at"][:10])
    
    lb_added = 0
    for lb_key, lb_entry in lb_data.items():
        title = lb_entry.get("title", "")
        year = str(lb_entry.get("year", ""))
        if not title:
            continue
        key = (title.lower(), year)
        
        for lb_date in lb_entry.get("dates", []):
            if not lb_date or lb_date[:4] < "2015" or lb_date[:4] > "2022":
                continue
            
            # Check if Trakt already has a watch within 30 days
            is_dupe = False
            for trakt_date in trakt_watches[key]:
                try:
                    td = abs((datetime.strptime(lb_date, "%Y-%m-%d") - datetime.strptime(trakt_date, "%Y-%m-%d")).days)
                    if td <= 30:
                        is_dupe = True
                        break
                except Exception:
                    pass
            
            if not is_dupe:
                entries.append({
                    "type": "movie",
                    "watched_at": lb_date + "T12:00:00.000Z",
                    "title": title,
                    "year": year,
                    "runtime": "",
                    "genres": "",
                    "trakt_slug": "",
                    "tmdb_id": lb_entry.get("tmdb_id", ""),
                    "show_title": "",
                    "season": "",
                    "episode_number": "",
                    "network": "",
                    "country": "",
                    "language": "",
                    "trakt_rating": "",
                })
                trakt_watches[key].add(lb_date)
                lb_added += 1
    
    if lb_added:
        entries.sort(key=lambda x: x["watched_at"], reverse=True)
        print(f"  Letterboxd backfill: +{lb_added} watches merged (2015-2022, deduped within 30 days)")
    else:
        print(f"  Letterboxd backfill: no new watches to merge")
    
    # Also add undated watches (from watched.csv) — no date, only count on all-time
    lb_undated = 0
    for lb_key, lb_entry in lb_data.items():
        if not lb_entry.get("undated"):
            continue
        title = lb_entry.get("title", "")
        year = str(lb_entry.get("year", ""))
        if not title:
            continue
        key = (title.lower(), year)
        # Skip if already in Trakt by any date
        if key in trakt_watches and trakt_watches[key]:
            continue
        entries.append({
            "type": "movie",
            "watched_at": "",  # no date
            "title": title,
            "year": year,
            "runtime": "",
            "genres": "",
            "trakt_slug": "",
            "tmdb_id": lb_entry.get("tmdb_id", ""),
            "show_title": "",
            "season": "",
            "episode_number": "",
            "network": "",
            "country": "",
            "language": "",
            "trakt_rating": "",
            "undated": True,
        })
        lb_undated += 1
    if lb_undated:
        print(f"  Letterboxd undated: +{lb_undated} movies added (all-time only)")

print(f"  Total: {len(entries)} entries (after merge)")

# Resolve missing Trakt slugs (from Letterboxd backfill entries)
missing_slugs = set()
for e in entries:
    if e["type"] == "movie" and not e["trakt_slug"] and e["title"]:
        missing_slugs.add((e["title"], str(e.get("year", ""))))

if missing_slugs:
    print(f"  Resolving {len(missing_slugs)} missing Trakt slugs...")
    slug_cache_path = "data/lb_slug_cache.json"
    slug_cache = {}
    if os.path.exists(slug_cache_path):
        with open(slug_cache_path) as f:
            slug_cache = json.load(f)
    
    resolved = 0
    for i, (title, year) in enumerate(missing_slugs):
        cache_key = f"{title}|{year}"
        if cache_key in slug_cache:
            slug = slug_cache[cache_key]
        else:
            # Search Trakt by title
            try:
                params = {"query": title, "years": year} if year else {"query": title}
                r = retry_request("get", f"{BASE_URL}/search/movie",
                                  params=params, headers=HEADERS, timeout=10)
                slug = ""
                if r and r.status_code == 200:
                    results = r.json()
                    for res in results[:3]:
                        m = res.get("movie", {})
                        if m.get("title", "").lower() == title.lower():
                            slug = m.get("ids", {}).get("slug", "")
                            break
                    if not slug and results:
                        slug = results[0].get("movie", {}).get("ids", {}).get("slug", "")
                slug_cache[cache_key] = slug
                time.sleep(0.15)
            except Exception:
                slug_cache[cache_key] = ""
        
        if slug:
            for e in entries:
                if e["type"] == "movie" and e["title"] == title and str(e.get("year", "")) == year and not e["trakt_slug"]:
                    e["trakt_slug"] = slug
            resolved += 1
        
        if (i + 1) % 50 == 0:
            print(f"    {i+1}/{len(missing_slugs)} searched, {resolved} resolved")
    
    with open(slug_cache_path, "w") as f:
        json.dump(slug_cache, f, separators=(",", ":"))
    print(f"  Resolved {resolved}/{len(missing_slugs)} slugs")

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

# Export visible-on-dashboard priority list for image backfill
# These are the people/shows that appear on the "all time / all types" page
visible_priority = {"people": [], "shows": [], "directors": [], "writers": []}
# Top actors + actresses (all time, sorted by total titles)
for pid, info in people.items():
    mc = sc = 0
    for ts in info["titles"]:
        for pre, typ in [("movie:", "movie"), ("show:", "show")]:
            k = pre + ts
            if k in {f"movie:{s}" for s in info["titles"]} | {f"show:{s}" for s in info["titles"]}:
                if typ == "movie": mc += 1
                else: sc += 1
                break
    if mc + sc >= 2:
        visible_priority["people"].append({"pid": pid, "name": info["name"], "rank": mc + sc})
visible_priority["people"].sort(key=lambda x: x["rank"], reverse=True)
visible_priority["people"] = visible_priority["people"][:100]  # top 100 visible
# Top directors + writers
for crew_raw, key in [(directors_raw, "directors"), (writers_raw, "writers")]:
    crew_vis = []
    for pid, info in crew_raw.items():
        mc = sc = 0
        for ts in info.get("titles", []):
            for pre, typ in [("movie:", "movie"), ("show:", "show")]:
                k = pre + ts
                if ts in slug_recency:
                    if typ == "movie": mc += 1
                    else: sc += 1
                    break
        if mc + sc >= 2:
            crew_vis.append({"pid": pid, "name": info["name"], "rank": mc + sc})
    crew_vis.sort(key=lambda x: x["rank"], reverse=True)
    visible_priority[key] = crew_vis[:50]
# Top shows (all time by total episodes)
show_eps = defaultdict(int)
for e in entries:
    if e["type"] == "episode" and e["show_title"] and e["trakt_slug"]:
        show_eps[e["trakt_slug"]] += 1
top_show_slugs = sorted(show_eps, key=show_eps.get, reverse=True)[:30]
visible_priority["shows"] = top_show_slugs
# Top movies (all time by watch count / runtime)
movie_rt = defaultdict(int)
for e in entries:
    if e["type"] == "movie" and e["trakt_slug"]:
        movie_rt[e["trakt_slug"]] += safe_int(e["runtime"]) if e["runtime"] else 0
top_movie_slugs = sorted(movie_rt, key=movie_rt.get, reverse=True)[:30]
visible_priority["movies"] = top_movie_slugs

with open("data/visible_priority.json", "w") as f:
    json.dump(visible_priority, f, separators=(',', ':'))
print(f"  Visible priority: {len(visible_priority['people'])} people, {len(visible_priority['shows'])} shows, {len(visible_priority['directors'])} directors, {len(visible_priority['writers'])} writers")

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
lb = {}
if os.path.exists("data/letterboxd.json"):
    with open("data/letterboxd.json") as f: lb = json.load(f)
concerts = []
if os.path.exists("data/setlist.json"):
    with open("data/setlist.json") as f: concerts = json.load(f)

# Podcast data from Pocket Casts
PODCAST_ALIASES = {
    "The Filmcast's Patreon Feed": "The Filmcast",
    "/Filmcast": "The Filmcast",
    "slashfilmcast": "The Filmcast",
}
def _pc_name(n):
    return PODCAST_ALIASES.get(n, n)

pc_data = {}
if os.path.exists("data/pocketcasts.json"):
    with open("data/pocketcasts.json") as f: pc_data = json.load(f)

# Theater data from Mezzanine
theater = []
if os.path.exists("data/mezzanine.csv"):
    import csv
    with open("data/mezzanine.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date = row.get("date","")[:10]
            year = date[:4] if date else ""
            tags = [t.strip() for t in row.get("customTags","").split(",") if t.strip()]
            theater.append({
                "show": row.get("show",""), "date": date, "year": year,
                "theater": row.get("theater",""), "location": row.get("location",""),
                "time": row.get("time",""), "rating": float(row["rating"]) if row.get("rating") else None,
                "tags": tags, "seat": row.get("seat","")
            })

print(f"\n[3/3] Building dashboard ({len(entries)} entries, {len(people)} people, {len(hs)} headshots, {len(ps)} posters)...")
data = build_data(entries, people, hs, ps, slug_studios, directors_raw, writers_raw)
data["lg"] = logos  # studio/network logos

# Letterboxd data: match to Trakt entries via TMDB ID, build rating distribution + tag cloud
lb_ratings = {}  # tmdb_id -> {rating, liked, tags}
lb_tags = Counter()
lb_rating_dist = Counter()  # rating -> count
lb_rating_dist_y = defaultdict(Counter)  # year -> rating -> count
for key, entry in lb.items():
    tmdb_id = entry.get("tmdb_id")
    if tmdb_id:
        lb_ratings[str(tmdb_id)] = {
            "r": entry.get("rating"),
            "liked": entry.get("liked", False),
            "tags": entry.get("tags", [])
        }
    if entry.get("rating"):
        lb_rating_dist[str(entry["rating"])] += 1
        # Per-year distribution based on watch dates
        watch_years = set(d[:4] for d in entry.get("dates", []) if d)
        for wy in watch_years:
            lb_rating_dist_y[wy][str(entry["rating"])] += 1
    for tag in entry.get("tags", []):
        lb_tags[tag] += 1

# Load tag categories
tag_cats = {}
if os.path.exists("data/tag_categories.json"):
    with open("data/tag_categories.json") as f:
        tag_cats = json.load(f)
data["tc"] = tag_cats  # tag categories for JS classification

# Build categorized tag data by year
def categorize_tags(lb_data, tag_cats):
    people_set = set(t.lower() for t in tag_cats.get("people", []))
    home_set = set(t.lower() for t in tag_cats.get("home", []))
    family_set = set(t.lower() for t in tag_cats.get("family", []))
    theater_set = set(t.lower() for t in tag_cats.get("theater", []))
    travel_set = set(t.lower() for t in tag_cats.get("travel", []))
    streaming_set = set(t.lower() for t in tag_cats.get("streaming", []))
    device_set = set(t.lower() for t in tag_cats.get("devices", []))

    # Per-year counts for each category
    from collections import defaultdict, Counter
    people_y = defaultdict(Counter)
    loc_y = defaultdict(Counter)  # home/theater/travel/other
    streaming_y = defaultdict(Counter)
    device_y = defaultdict(Counter)
    # All-time
    people_all = Counter()
    loc_all = Counter()
    loc_detail_y = defaultdict(Counter)
    loc_detail_all = Counter()
    streaming_all = Counter()
    device_all = Counter()

    # Build per-watch tag data from CSV (each row = one watch with its own tags+date)
    watch_tags = []  # [{title, yr, tags}]
    if os.path.exists("data/letterboxd_tags.csv"):
        import csv
        with open("data/letterboxd_tags.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get("Name", "")
                tags_str = row.get("Tags", "")
                watched = row.get("Watched Date", "") or row.get("Date", "")
                if not title or not watched: continue
                tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()] if tags_str else []
                watch_tags.append({"title": title, "yr": watched[:4], "tags": tags})

    # If we have per-watch data, use it; otherwise fall back to per-film
    tag_source = watch_tags if watch_tags else []
    if not tag_source:
        for key, entry in lb_data.items():
            tags = [t.lower() for t in entry.get("tags", [])]
            if not tags: continue
            dates = entry.get("dates", [])
            yr = max(dates)[:4] if dates else ""
            if yr: tag_source.append({"title": entry.get("title",""), "yr": yr, "tags": tags})

    for wt in tag_source:
        tags = wt["tags"]
        yr = wt["yr"]
        if not tags or not yr: continue

        # People
        ptags = [t for t in tags if t in people_set]
        for t in ptags:
            # Clean "with " prefix for display
            display = t.replace("with ", "").strip()
            people_y[yr][display] += 1
            people_all[display] += 1
        if not ptags:
            people_y[yr]["solo"] += 1
            people_all["solo"] += 1

        # Location (simple) — first matching tag wins (no double counting)
        has_loc = False
        for t in tags:
            if t in home_set or t == "quarantine":
                loc_y[yr]["home"] += 1; loc_all["home"] += 1; has_loc = True; break
            elif t in family_set:
                loc_y[yr]["family/friends"] += 1; loc_all["family/friends"] += 1; has_loc = True; break
            elif t in theater_set:
                loc_y[yr]["theater"] += 1; loc_all["theater"] += 1; has_loc = True; break
            elif t in travel_set:
                loc_y[yr]["travel"] += 1; loc_all["travel"] += 1; has_loc = True; break
        if not has_loc:
            loc_y[yr]["other"] += 1; loc_all["other"] += 1
        # Location detail (individual venues) — first matching tag wins
        loc_found = False
        all_loc_tags = home_set | family_set | theater_set | travel_set
        for t in tags:
            if t in all_loc_tags or t == "quarantine":
                display = t.replace("quarantine", "home (quarantine)")
                loc_detail_y[yr][display] += 1; loc_detail_all[display] += 1; loc_found = True; break
        if not loc_found:
            loc_detail_y[yr]["other"] += 1; loc_detail_all["other"] += 1

        # Streaming — only count if a streaming tag is present
        stags = [t for t in tags if t in streaming_set]
        for t in stags:
            streaming_y[yr][t] += 1; streaming_all[t] += 1

        # Devices — only count if a device tag is present
        dtags = [t for t in tags if t in device_set]
        for t in dtags:
            device_y[yr][t] += 1; device_all[t] += 1

    # Build title lists per category value with watch years for click-to-see
    cat_titles = defaultdict(lambda: defaultdict(list))  # category -> value -> [{t, wy}]
    for wt2 in tag_source:
        tags = wt2["tags"]
        if not tags: continue
        title = wt2["title"]
        yr2 = wt2["yr"]
        item = {"t": title, "wy": [yr2]}
        loc_assigned = False
        for t in tags:
            if t in streaming_set:
                cat_titles["stream"][t].append(item)
            if t in device_set:
                cat_titles["dev"][t].append(item)
            # Location: only first match (no double counting)
            if not loc_assigned:
                if t in home_set or t == "quarantine":
                    cat_titles["loc"]["home"].append(item)
                    cat_titles["locd"][t.lower()].append(item)
                    loc_assigned = True
                elif t in family_set:
                    cat_titles["loc"]["family/friends"].append(item)
                    cat_titles["locd"][t.lower()].append(item)
                    loc_assigned = True
                elif t in theater_set:
                    cat_titles["loc"]["theater"].append(item)
                    cat_titles["locd"][t.lower()].append(item)
                    loc_assigned = True
                elif t in travel_set:
                    cat_titles["loc"]["travel"].append(item)
                    cat_titles["locd"][t.lower()].append(item)
                    loc_assigned = True
            # People: track titles per person
            if t.startswith("with ") or t in people_set:
                display = t.replace("with ", "").strip()
                cat_titles["people"][display].append(item)

    # Merge duplicate titles (combine watch years), keep all entries
    ct_out = {}
    for cat, vals in cat_titles.items():
        ct_out[cat] = {}
        for v, items in vals.items():
            merged = {}
            for item in items:
                if item["t"] in merged:
                    for y in item["wy"]:
                        if y not in merged[item["t"]]["wy"]:
                            merged[item["t"]]["wy"].append(y)
                else:
                    merged[item["t"]] = {"t": item["t"], "wy": list(item["wy"])}
            ct_out[cat][v] = list(merged.values())

    years = sorted(set(list(people_y) + list(loc_y) + list(streaming_y) + list(device_y)))

    return {
        "years": years,
        "people": {"all": [{"n": n, "c": c} for n, c in people_all.most_common(20)],
                   "y": {y: [{"n": n, "c": c} for n, c in ct.most_common(15)] for y, ct in people_y.items()}},
        "loc": {"all": [{"n": n, "c": c} for n, c in loc_all.most_common()],
                "y": {y: [{"n": n, "c": c} for n, c in ct.most_common()] for y, ct in loc_y.items()}},
        "locd": {"all": [{"n": n, "c": c} for n, c in loc_detail_all.most_common(20)],
                 "y": {y: [{"n": n, "c": c} for n, c in ct.most_common(15)] for y, ct in loc_detail_y.items()}},
        "stream": {"all": [{"n": n, "c": c} for n, c in streaming_all.most_common(15)],
                   "y": {y: [{"n": n, "c": c} for n, c in ct.most_common(10)] for y, ct in streaming_y.items()}},
        "dev": {"all": [{"n": n, "c": c} for n, c in device_all.most_common(15)],
                "y": {y: [{"n": n, "c": c} for n, c in ct.most_common(10)] for y, ct in device_y.items()}},
        "ct": ct_out,
    }

tag_data = categorize_tags(lb, tag_cats)

# Personal rating lists from Letterboxd
my_rated = [{"t": e["title"], "yr": e.get("year"), "r": e["rating"],
             "wy": sorted(set(d[:4] for d in e.get("dates",[]) if d))}
            for e in lb.values() if e.get("rating")]
my_rated_high = sorted(my_rated, key=lambda x: x["r"], reverse=True)
my_rated_low = sorted(my_rated, key=lambda x: x["r"])

data["lb"] = {
    "ratings": lb_ratings,
    "dist": [{"r": r, "c": c} for r, c in sorted(lb_rating_dist.items())],
    "dist_y": {y: [{"r": r, "c": c} for r, c in sorted(ct.items())] for y, ct in lb_rating_dist_y.items()},
    "tags": tag_data,
    "total": len(lb),
    "rated": sum(1 for e in lb.values() if e.get("rating")),
    "avg": round(sum(e["rating"] for e in lb.values() if e.get("rating")) / max(1, sum(1 for e in lb.values() if e.get("rating"))), 1),
    "myh": my_rated_high,
    "myl": my_rated_low,
}

# Serializd TV ratings
sz = {}
if os.path.exists("data/serializd.json"):
    with open("data/serializd.json") as f:
        sz = json.load(f)

if sz:
    # Build per-show average rating and collect all ratings with dates
    sz_shows = []  # {t, r, wy} for highest/lowest lists
    sz_dist = Counter()  # rating -> count (half-star buckets)
    sz_dist_y = defaultdict(Counter)  # year -> rating -> count
    sz_total = 0

    for sid, show in sz.items():
        ratings = show.get("ratings", [])
        if not ratings:
            continue
        for r in ratings:
            sn = r.get("sn")
            label = show["name"] + (" S" + str(sn).zfill(2) if sn else "")
            wy = [r["date"][:4]] if r.get("date") else []
            sz_shows.append({"t": label, "r": r["r"], "wy": wy, "yr": ""})

            bucket = str(r["r"])
            sz_dist[bucket] += 1
            sz_total += 1
            if r.get("date"):
                yr = r["date"][:4]
                sz_dist_y[yr][bucket] += 1

    sz_high = sorted(sz_shows, key=lambda x: x["r"], reverse=True)
    sz_low = sorted(sz_shows, key=lambda x: x["r"])
    sz_avg = round(sum(s["r"] for s in sz_shows) / max(1, len(sz_shows)), 1)

    data["sz"] = {
        "dist": [{"r": r, "c": c} for r, c in sorted(sz_dist.items(), key=lambda x: float(x[0]))],
        "dist_y": {y: [{"r": r, "c": c} for r, c in sorted(ct.items(), key=lambda x: float(x[0]))] for y, ct in sz_dist_y.items()},
        "total": len(sz_shows),
        "rated": sz_total,
        "avg": sz_avg,
        "szh": sz_high,
        "szl": sz_low,
    }
    print(f"  Serializd: {len(sz_shows)} shows, {sz_total} ratings, avg {sz_avg}★")
else:
    data["sz"] = {}

# Concert data from setlist.fm
from collections import Counter as Ctr2
if concerts:
    # Deduplicate concerts: group by date+venue to count real events (not per-artist)
    event_key = lambda c: f"{c['date']}|{c['venue']}"
    unique_events = {}
    for c in concerts:
        ek = event_key(c)
        if ek not in unique_events:
            unique_events[ek] = {"date": c["date"], "year": c["year"], "venue": c["venue"], "city": c["city"], "artists": [], "songs": 0}
        unique_events[ek]["artists"].append(c["artist"])
        unique_events[ek]["songs"] += c["song_count"]

    real_concert_count = len(unique_events)
    total_songs = sum(e["songs"] for e in unique_events.values())

    # Artist counts: 1 per artist per concert (not per setlist)
    ca = Ctr2(c["artist"] for c in concerts)
    ca_songs = defaultdict(int)
    ca_song_list = defaultdict(lambda: Ctr2())
    for c in concerts:
        ca_songs[c["artist"]] += c["song_count"]
        for s in c.get("songs", []):
            if s: ca_song_list[c["artist"]][s] += 1

    # Venue counts: per unique event, not per setlist
    cv = Ctr2()
    for e in unique_events.values():
        if e["venue"]:
            cv[f"{e['venue']}, {e['city']}"] += 1

    # Year counts: per unique event + per set (each artist performance)
    cy2 = Ctr2()
    cy2_songs = defaultdict(int)
    cy2_sets = Ctr2()
    for e in unique_events.values():
        cy2[e["year"]] += 1
        cy2_songs[e["year"]] += e["songs"]
        cy2_sets[e["year"]] += len(e["artists"])
    total_sets = sum(cy2_sets.values())
    # Album breakdown per artist
    ca_albums = defaultdict(Counter)
    for c in concerts:
        sa = c.get("song_albums", {})
        for song, album in sa.items():
            if album: ca_albums[c["artist"]][album] += 1
    artist_detail = {}
    for artist in ca:
        top_songs = [(s,ct) for s,ct in ca_song_list[artist].most_common() if ct>=2]
        albums = [{"n":a,"c":ct} for a,ct in ca_albums[artist].most_common()]
        artist_detail[artist] = {"songs":[{"n":s,"c":ct} for s,ct in ca_song_list[artist].most_common(20)],"top":[{"n":s,"c":ct} for s,ct in top_songs[:15]],"albums":albums}
    # Load artist genres from MusicBrainz
    artist_genres_map = {}
    if os.path.exists("data/artist_genres.json"):
        with open("data/artist_genres.json") as f:
            artist_genres_map = json.load(f)
    con_genre_counter = Ctr2()
    for c in concerts:
        for g in artist_genres_map.get(c["artist"], []):
            con_genre_counter[g] += 1
    con_genres = [{"n": g, "c": c} for g, c in con_genre_counter.most_common(15)]

    data["con"] = {
        "total": real_concert_count, "songs": total_songs, "sets": total_sets,
        "artists": [{"n": a, "c": c, "s": ca_songs[a]} for a, c in ca.most_common(25)],
        "adetail": artist_detail,
        "venues": [{"n": v, "c": c} for v, c in cv.most_common(25)],
        "genres": con_genres,
        "years": [{"yr": y, "c": c, "s": cy2_songs.get(y,0), "st": cy2_sets.get(y,0)} for y, c in sorted(cy2.items())],
        "recent": [{"artist": c["artist"], "venue": c["venue"], "city": c["city"],
                    "date": c["date"], "yr": c["year"], "tour": c["tour"],
                    "songs": c["song_count"], "genres": artist_genres_map.get(c["artist"], [])} for c in concerts],
    }

# Theater data from Mezzanine
if theater:
    # Load companion names to separate from descriptive tags
    th_companion_names = set()
    if os.path.exists("data/theater_companions.json"):
        with open("data/theater_companions.json") as f:
            th_companion_names = set(json.load(f))
    th_theaters = Ctr2(t["theater"] for t in theater if t["theater"])
    th_locations = Ctr2(t["location"] for t in theater if t["location"])
    th_years = Ctr2(t["year"] for t in theater)
    th_people = Ctr2()        # companions only
    th_people_shows = defaultdict(list)
    th_theater_shows = defaultdict(list)
    th_all_tags = Ctr2()      # non-companion tags only
    th_tag_shows = defaultdict(list)
    for t in theater:
        for tag in t["tags"]:
            if tag in th_companion_names:
                th_people[tag] += 1
                th_people_shows[tag].append(t["show"])
            else:
                th_all_tags[tag] += 1
                th_tag_shows[tag].append(t["show"])
        if t["theater"]:
            th_theater_shows[t["theater"]].append(t["show"])
    th_rated = [t for t in theater if t["rating"]]
    # Rating distribution with titles
    th_rating_dist = defaultdict(list)
    for t in theater:
        if t["rating"]:
            th_rating_dist[str(t["rating"])].append(t["show"])
    data["th"] = {
        "total": len(theater),
        "rated": len(th_rated),
        "avg": round(sum(t["rating"] for t in th_rated)/len(th_rated),1) if th_rated else 0,
        "theaters": [{"n":t,"c":c,"shows":th_theater_shows[t]} for t,c in th_theaters.most_common(20)],
        "locations": [{"n":l,"c":c} for l,c in th_locations.most_common(20)],
        "people": [{"n":p,"c":c,"shows":th_people_shows[p]} for p,c in th_people.most_common(20)],
        "tags": [{"n":t,"c":c,"shows":th_tag_shows[t]} for t,c in th_all_tags.most_common(30)],
        "companions": list(th_companion_names),
        "dist": [{"r":r,"c":len(ts),"titles":ts} for r,ts in sorted(th_rating_dist.items())],
        "recent": [{"show":t["show"],"date":t["date"],"yr":t["year"],"theater":t["theater"],
                    "location":t["location"],"rating":t["rating"]} for t in sorted(theater,key=lambda x:x["date"],reverse=True)[:15]],
        "all": [{"s":t["show"],"y":t["year"],"t":t["theater"],"r":t["rating"],"g":t["tags"]} for t in theater],
    }

# Add concert + theater monthly/yearly counts to chart data
if concerts:
    con_monthly = defaultdict(int)
    for e in unique_events.values():
        if e["date"]: con_monthly[e["date"][:7]] += 1
    data["c"]["con_m"] = dict(con_monthly)
    data["c"]["con_y"] = dict(cy2)

if theater:
    th_monthly = defaultdict(int)
    for t in theater:
        if t["date"]: th_monthly[t["date"][:7]] += 1
    data["c"]["th_m"] = dict(th_monthly)
    data["c"]["th_y"] = dict(th_years)

# Podcast data from Pocket Casts
if pc_data:
    data["pc"] = pc_data
    # Add podcast monthly/yearly episode counts for timeline charts — real data only, >5min
    pc_poll_monthly = defaultdict(int)
    pc_poll_yearly = defaultdict(int)
    if os.path.exists("data/pocketcasts_history.json"):
        with open("data/pocketcasts_history.json") as f:
            _pch = json.load(f)
        for ev in _pch.values():
            if ev.get("src") in ("poll", "export") and ev.get("d"):
                played = ev.get("played", 0) or 0
                if played > 0 and played < 300:
                    continue
                d = ev["d"]
                pc_poll_monthly[d[:7]] += 1
                pc_poll_yearly[d[:4]] += 1
    data["c"]["pc_m"] = dict(pc_poll_monthly)
    data["c"]["pc_y"] = dict(pc_poll_yearly)
    # Add podcast series to monthly title data (mt) for click detail
    for ev in _pch.values():
        if ev.get("src") in ("poll", "export") and ev.get("d"):
            played = ev.get("played", 0) or 0
            if played > 0 and played < 300:
                continue
            mo = ev["d"][:7]
            pod_name = _pc_name(ev.get("p", "Unknown Podcast"))
            if mo not in data["c"]["mt"]:
                data["c"]["mt"][mo] = []
            # Find existing podcast entry for this month or create one
            found = False
            for item in data["c"]["mt"][mo]:
                if item["t"] == pod_name and item.get("type") == "podcast":
                    item["c"] += 1
                    found = True
                    break
            if not found:
                data["c"]["mt"][mo].append({"t": pod_name, "type": "podcast", "c": 1})
    
    # Build per-year top podcast lists from history
    pc_by_year = defaultdict(lambda: defaultdict(lambda: {"eps": 0, "sec": 0}))
    for ev in _pch.values():
        if ev.get("src") in ("poll", "export") and ev.get("d"):
            played = ev.get("played", 0) or 0
            if played > 0 and played < 300:
                continue
            yr = ev["d"][:4]
            pod = _pc_name(ev.get("p", "Unknown"))
            pc_by_year[yr][pod]["eps"] += 1
            pc_by_year[yr][pod]["sec"] += played
    
    # Build top_y: {year: [{title, played, listened_hrs}]}
    pc_top_y = {}
    for yr, pods in pc_by_year.items():
        top_list = sorted(pods.items(), key=lambda x: x[1]["sec"], reverse=True)
        pc_top_y[yr] = [{"title": name, "played": d["eps"], "listened_hrs": round(d["sec"]/3600, 1)} for name, d in top_list[:25]]
    data["pc"]["top_y"] = pc_top_y
    
    print(f"  Podcasts: {pc_data.get('total_podcasts', 0)} shows, {pc_data.get('total_listened_hrs', 0)}h listened, {sum(pc_poll_yearly.values())} episodes in timeline")

# Merge concert + theater titles into monthly title lists (mt)
mt = data["c"].get("mt", {})
if concerts:
    for e in unique_events.values():
        if e["date"]:
            m = e["date"][:7]
            if m not in mt: mt[m] = []
            mt[m].append({"t": " / ".join(e["artists"]), "type": "concert", "c": 1})
if theater:
    for t in theater:
        if t["date"]:
            m = t["date"][:7]
            if m not in mt: mt[m] = []
            mt[m].append({"t": t["show"], "type": "theater", "c": 1})
data["c"]["mt"] = mt

# Goodreads data
gr_books = []
if os.path.exists("data/goodreads.json"):
    with open("data/goodreads.json") as f:
        gr_books = json.load(f)
if gr_books:
    # Books per year
    gr_year = Counter()
    gr_pages_year = Counter()
    for b in gr_books:
        yr = b.get("year_read", "")
        if yr:
            gr_year[yr] += 1
            gr_pages_year[yr] += b.get("pages", 0)
    gr_years = [{"yr": y, "c": gr_year[y], "p": gr_pages_year[y]} for y in sorted(gr_year.keys())]

    # Time to read (date_added → date_read)
    gr_ttr = []
    for b in gr_books:
        if b.get("date_added") and b.get("date_read") and b["date_added"] < b["date_read"]:
            try:
                da = datetime.strptime(b["date_added"], "%Y-%m-%d")
                dr = datetime.strptime(b["date_read"], "%Y-%m-%d")
                days = (dr - da).days
                if 0 < days < 3650:  # filter out unreasonable values
                    gr_ttr.append({"t": b["title"], "a": b["author"], "d": days, "p": b.get("pages", 0)})
            except Exception:
                pass
    gr_ttr.sort(key=lambda x: x["d"])

    # Most read authors
    gr_authors = Counter()
    gr_author_pages = Counter()
    for b in gr_books:
        if b.get("author"):
            gr_authors[b["author"]] += 1
            gr_author_pages[b["author"]] += b.get("pages", 0)
    gr_top_authors = [{"n": a, "c": c, "p": gr_author_pages[a]} for a, c in gr_authors.most_common(15)]

    # Page counts: longest and shortest
    gr_with_pages = [b for b in gr_books if b.get("pages", 0) > 0]
    gr_longest = sorted(gr_with_pages, key=lambda x: x["pages"], reverse=True)[:10]
    gr_shortest = sorted(gr_with_pages, key=lambda x: x["pages"])[:10]

    # Rating distribution + highest/lowest rated
    gr_rated = [b for b in gr_books if b.get("user_rating", 0) > 0]
    gr_rating_dist = Counter()
    for b in gr_rated:
        gr_rating_dist[str(b["user_rating"])] += 1
    gr_dist = [{"r": r, "c": gr_rating_dist[r]} for r in sorted(gr_rating_dist.keys())]
    gr_highest = sorted(gr_rated, key=lambda x: (x["user_rating"], x.get("pages", 0)), reverse=True)[:10]
    gr_lowest = sorted(gr_rated, key=lambda x: (x["user_rating"], -x.get("pages", 0)))[:10]

    # Shelves/genres — merge user shelves + scraped community genres
    gr_community_genres = {}
    if os.path.exists("data/book_genres.json"):
        with open("data/book_genres.json") as f:
            gr_community_genres = json.load(f)
    gr_shelves = Counter()  # user shelves
    gr_genres = Counter()   # community genres
    for b in gr_books:
        for s in b.get("shelves", []):
            gr_shelves[s] += 1
        cg = gr_community_genres.get(b["book_id"], [])
        for g in cg:
            gr_genres[g] += 1
        # Store merged genres per book for click filtering
        b["_genres"] = list(dict.fromkeys(b.get("shelves", []) + cg))
    gr_shelf_list = [{"n": g, "c": c} for g, c in gr_shelves.most_common(15)]
    gr_genre_list = [{"n": g, "c": c} for g, c in gr_genres.most_common(15)]

    # Reading pace: pages per day for books with both dates and pages
    gr_pace = []
    for b in gr_books:
        if b.get("date_added") and b.get("date_read") and b.get("pages", 0) > 0:
            try:
                da = datetime.strptime(b["date_added"], "%Y-%m-%d")
                dr = datetime.strptime(b["date_read"], "%Y-%m-%d")
                days = max((dr - da).days, 1)
                if days < 3650:
                    gr_pace.append({"t": b["title"], "ppd": round(b["pages"] / days, 1), "p": b["pages"], "d": days})
            except Exception:
                pass
    gr_pace.sort(key=lambda x: x["ppd"], reverse=True)

    # Monthly book counts for timeline
    gr_monthly = Counter()
    for b in gr_books:
        if b.get("date_read"):
            gr_monthly[b["date_read"][:7]] += 1
    gr_month_counts = dict(gr_monthly)

    data["gr"] = {
        "total": len(gr_books),
        "total_pages": sum(b.get("pages", 0) for b in gr_books),
        "rated": len(gr_rated),
        "avg": round(sum(b["user_rating"] for b in gr_rated) / len(gr_rated), 1) if gr_rated else 0,
        "years": gr_years,
        "ttr": gr_ttr,
        "ttr_avg": round(sum(t["d"] for t in gr_ttr) / len(gr_ttr)) if gr_ttr else 0,
        "authors": gr_top_authors,
        "longest": [{"t": b["title"], "a": b["author"], "p": b["pages"]} for b in gr_longest],
        "shortest": [{"t": b["title"], "a": b["author"], "p": b["pages"]} for b in gr_shortest],
        "dist": gr_dist,
        "highest": [{"t": b["title"], "a": b["author"], "r": b["user_rating"], "p": b.get("pages", 0)} for b in gr_highest],
        "lowest": [{"t": b["title"], "a": b["author"], "r": b["user_rating"], "p": b.get("pages", 0)} for b in gr_lowest],
        "pace": gr_pace[:15],
        "shelves": gr_shelf_list,
        "genres": gr_genre_list,
        "month_counts": gr_month_counts,
        "all": [{"t": b["title"], "a": b["author"], "p": b.get("pages", 0), "r": b.get("user_rating", 0),
                 "yr": b.get("year_read", ""), "dr": b.get("date_read", ""), "da": b.get("date_added", ""),
                 "sh": b.get("shelves", []), "gn": b.get("_genres", []), "img": b.get("image", "")} for b in gr_books],
    }
    # Add books to monthly timeline counts
    data["c"]["gr_m"] = gr_month_counts
    gr_yearly = {}
    for yr, c in gr_year.items():
        gr_yearly[yr] = c
    data["c"]["gr_y"] = gr_yearly
    # Add books to monthly title lists
    mt = data["c"].get("mt", {})
    for b in gr_books:
        if b.get("date_read"):
            m = b["date_read"][:7]
            if m not in mt: mt[m] = []
            mt[m].append({"t": b["title"] + " — " + b["author"], "type": "book", "c": 1})
    data["c"]["mt"] = mt
    print(f"  Goodreads: {len(gr_books)} books, {len(gr_rated)} rated")

# Last.fm data
if os.path.exists("data/lastfm.json"):
    with open("data/lastfm.json") as f:
        data["lfm"] = json.load(f)
    print(f"  Last.fm: {data['lfm']['total']} scrobbles")

# Lifeline: per-day activity with timestamped events for chronological display
from datetime import timedelta
from zoneinfo import ZoneInfo
_tz_pac = ZoneInfo("America/Los_Angeles")
ll_counts = defaultdict(lambda: {"ep": 0, "mv": 0, "bk": 0, "sc": 0, "co": 0, "th": 0, "pc": 0})
ll_events = defaultdict(list)  # day -> [{t: time, n: name, ty: type}]

# Episodes + Movies from Trakt (have full timestamps — convert UTC to Pacific)
for e in entries:
    if not e.get("watched_at"): continue
    try:
        dt_utc = datetime.fromisoformat(e["watched_at"].replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(_tz_pac)
        d = dt_local.strftime("%Y-%m-%d")
        ts = dt_local.strftime("%H:%M")
    except Exception:
        d = e["watched_at"][:10]
        ts = e["watched_at"][11:16] if len(e["watched_at"]) > 11 else "00:00"
    if e["type"] == "episode":
        name = (e.get("show_title") or "") + " S" + str(e.get("season","")) + "E" + str(e.get("episode_number",""))
        ll_counts[d]["ep"] += 1
        ll_events[d].append({"t": ts, "n": name, "ty": "ep"})
    elif e["type"] == "movie":
        ll_counts[d]["mv"] += 1
        ll_events[d].append({"t": ts, "n": e.get("title",""), "ty": "mv"})

# Books from Goodreads (date only, no time)
if gr_books:
    for b in gr_books:
        if b.get("date_read"):
            d = b["date_read"]
            ll_counts[d]["bk"] += 1
            ll_events[d].append({"t": "12:00", "n": b["title"], "ty": "bk"})

# Scrobbles from Last.fm
exact_sc_days = set()

# Load backfilled daily scrobble counts (from backfill_lastfm_daily.py)
lastfm_daily_counts = {}
if os.path.exists("data/lastfm_daily.json"):
    with open("data/lastfm_daily.json") as f:
        lastfm_daily_counts = json.load(f)
    print(f"  Loaded {len(lastfm_daily_counts)} days of backfilled scrobble data")
    # Apply backfilled counts to lifeline
    for d, count in lastfm_daily_counts.items():
        if count > 0:
            ll_counts[d]["sc"] = count
            exact_sc_days.add(d)

LASTFM_KEY = os.environ.get("LASTFM_API_KEY", "")
LASTFM_USER = os.environ.get("LASTFM_USER", "")
if LASTFM_KEY and LASTFM_USER:
    # Fetch exact daily scrobbles for last 35 days via API
    import urllib.request as urlreq
    print("  Fetching daily scrobbles for lifeline...")
    for days_ago in range(35):
        try:
            day_start = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - timedelta(days=days_ago)
            day_end = day_start + timedelta(days=1)
            d = day_start.strftime("%Y-%m-%d")
            fr = int(day_start.timestamp()); to = int(day_end.timestamp())
            url = f"https://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&user={LASTFM_USER}&api_key={LASTFM_KEY}&format=json&limit=200&from={fr}&to={to}"
            req = urlreq.Request(url, headers={"User-Agent": "Iris/1.0"})
            with urlreq.urlopen(req, timeout=10) as resp:
                lfm_resp = json.loads(resp.read())
            tracks = lfm_resp.get("recenttracks", {}).get("track", [])
            for t in tracks:
                if not t.get("date"): continue
                try:
                    ts_parsed = datetime.strptime(t["date"]["#text"], "%d %b %Y, %H:%M")
                    ts = ts_parsed.strftime("%H:%M")
                except Exception:
                    ts = "00:00"
                ll_counts[d]["sc"] += 1
                ll_events[d].append({"t": ts, "n": t["artist"]["#text"] + " — " + t["name"], "ty": "sc"})
            exact_sc_days.add(d)
            import time as tm; tm.sleep(0.2)
        except Exception: pass

# Approximate older days from stored Last.fm data
today_str = datetime.now().strftime("%Y-%m-%d")
if os.path.exists("data/lastfm.json"):
    with open("data/lastfm.json") as f:
        lfm_data = json.load(f)
    # Approximate from weekly totals
    for w in lfm_data.get("weekly", []):
        if w.get("week") and w.get("c"):
            try:
                wk_start = datetime.strptime(w["week"], "%Y-%m-%d")
                daily = max(1, w["c"] // 7)
                for i in range(7):
                    d = (wk_start + timedelta(days=i)).strftime("%Y-%m-%d")
                    if d > today_str: continue
                    if d not in exact_sc_days:
                        ll_counts[d]["sc"] += daily
            except Exception: pass
    # Approximate from monthly for oldest data
    weekly_dates = set()
    for w in lfm_data.get("weekly", []):
        if w.get("week"):
            try:
                ws = datetime.strptime(w["week"], "%Y-%m-%d")
                for i in range(7): weekly_dates.add((ws + timedelta(days=i)).strftime("%Y-%m-%d"))
            except Exception: pass
    for m in lfm_data.get("monthly", []):
        if m.get("m") and m.get("s"):
            mo = m["m"]
            daily = max(1, m["s"] // 30)
            for day in range(1, 32):
                try:
                    d = f"{mo}-{day:02d}"
                    datetime.strptime(d, "%Y-%m-%d")
                    if d > today_str: continue
                    if d not in exact_sc_days and d not in weekly_dates:
                        ll_counts[d]["sc"] += daily
                except Exception: pass

# Concerts
if concerts:
    for c in concerts:
        if c.get("date"):
            d = c["date"]
            ll_counts[d]["co"] += 1
            ll_events[d].append({"t": "20:00", "n": "🎸 " + c["artist"] + " @ " + c.get("venue",""), "ty": "co"})

# Theater
if theater:
    for t in theater:
        if t.get("date"):
            d = t["date"][:10]
            ll_counts[d]["th"] += 1
            ll_events[d].append({"t": "19:30", "n": "🎭 " + t["show"], "ty": "th"})

# Podcasts — include episodes with real dates (poll or export), min 5 min listened
if os.path.exists("data/pocketcasts_history.json"):
    with open("data/pocketcasts_history.json") as f:
        pc_history = json.load(f)
    pc_ll_count = 0
    for ep_uuid, ev in pc_history.items():
        src = ev.get("src", "")
        if src not in ("poll", "export"):
            continue
        # Skip episodes listened less than 5 minutes
        played = ev.get("played", 0) or 0
        if played > 0 and played < 300:
            continue
        d = ev.get("d", "")
        if not d or len(d) < 10:
            continue
        # Convert to Pacific timezone if it looks like a UTC date
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            d = dt.astimezone(_tz_pac).strftime("%Y-%m-%d")
        except Exception:
            pass
        ll_counts[d]["pc"] += 1
        ll_events[d].append({"t": "12:00", "n": "🎙️ " + ev.get("p", "") + " — " + ev.get("t", ""), "ty": "pc"})
        pc_ll_count += 1
    if pc_ll_count:
        print(f"  Podcasts in lifeline: {pc_ll_count} episodes (poll+export, >5min)")

# Build output: counts for bars + detailed events for all dates
lifeline_all = {}
for d in sorted(ll_counts.keys()):
    c = ll_counts[d]
    if c["ep"] or c["mv"] or c["bk"] or c["sc"] or c["co"] or c["th"] or c["pc"]:
        entry = {"ep": c["ep"], "mv": c["mv"], "bk": c["bk"],
                 "sc": c["sc"], "co": c["co"], "th": c["th"], "pc": c["pc"]}
        evts = sorted(ll_events.get(d, []), key=lambda x: x["t"])
        # For days with scrobble counts but no individual tracks, add summary entry
        if c["sc"] and not any(e["ty"] == "sc" for e in evts):
            evts.append({"t": "12:00", "n": "~" + str(c["sc"]) + " scrobbles", "ty": "sc"})
        if evts:
            entry["e"] = evts[:100]
        lifeline_all[d] = entry
data["ll"] = lifeline_all

# Up Next — load pre-computed show progress
if os.path.exists("data/up_next.json"):
    with open("data/up_next.json") as f:
        un_raw = json.load(f)
        # Support both old (list) and new (dict) format
        if isinstance(un_raw, list):
            data["un"] = {"shows": un_raw, "recent": []}
        else:
            data["un"] = un_raw

# Sports — load from repo-backed JSON
if os.path.exists("data/sports.json"):
    with open("data/sports.json") as f:
        sp_raw = json.load(f)
    if sp_raw:
        data["sp"] = sp_raw
        print(f"  Sports: {len(sp_raw)} events loaded from data/sports.json")

# Inject Trakt credentials for client-side mark-as-watched
_trakt_token = os.environ.get("TRAKT_ACCESS_TOKEN", "")
if _trakt_token and CLIENT_ID:
    data["_tc"] = CLIENT_ID
    data["_tt"] = _trakt_token

data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
with open("templates/dashboard.html") as f:
    template = f.read()
html = template.replace("__DASHBOARD_DATA__", data_str)
html = html.replace("__BUILD_TIME__", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
with open("index.html", "w") as f:
    f.write(html)

print(f"  index.html: {len(html)//1024}KB")
print(f"  Actors: {len(data.get('a',[]))}, Actresses: {len(data.get('x',[]))}")
print(f"  Networks: {len(data.get('c',{}).get('net',[]))}, Studios: {len(data.get('c',{}).get('stu',[]))}")
print("Done!")
