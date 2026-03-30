#!/usr/bin/env python3
"""
Backfill per-episode crew credits (directors/writers) for recently-watched shows.
Reads the season_credits.json cache, re-fetches seasons missing crew data
for shows watched in the last 7 days, and writes crew_episodes.json.

Lightweight: only touches ~30 seasons, not all 800+.
Run as part of the 2-hour refresh cycle.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from utils import retry_request

TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE = "https://api.themoviedb.org/3"

# All crew jobs to store in cache (matches CREW_ROLES in refresh_data.py + director/writer)
_CACHE_CREW_JOBS = {
    "Director", "Writer", "Screenplay", "Story", "Author", "Novel", "Original Story",
    "Producer", "Executive Producer", "Co-Director",
    "Characters", "Comic Book",
    "Casting", "Casting Director", "Editor",
    "Director of Photography",
    "First Assistant Director", "Second Assistant Director",
    "Additional Directing", "Second Unit Director",
    "Gaffer", "Best Boy Electric", "Lighting Director",
    "Camera Operator", "Steadicam Operator",
    "Additional Photography", "Second Unit Director of Photography",
    "Production Designer", "Production Design",
    "Art Director", "Art Direction",
    "Original Music Composer", "Music", "Music Supervisor",
    "Sound Designer", "Sound Editor", "Supervising Sound Editor",
    "Sound Re-Recording Mixer", "Sound Mixer", "Boom Operator", "Foley Artist",
    "Visual Effects Supervisor", "Visual Effects Producer", "Visual Effects",
    "Stunt Coordinator", "Stunts",
    "Costume Designer", "Costume Design",
    "Set Decorator", "Set Decoration",
    "Makeup Artist", "Makeup Department Head", "Hair Department Head",
    "Special Effects Makeup Artist", "Key Makeup Artist",
    "Title Designer",
}


def _slugify(name):
    return name.lower().replace(" ", "-").replace("'", "").replace(".", "")


def main():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    if not TMDB_API_KEY:
        print("No TMDB_API_KEY, skipping crew backfill")
        return

    # Load season cache
    cache_path = os.path.join(data_dir, "season_credits.json")
    if not os.path.exists(cache_path):
        print("No season_credits.json, skipping")
        return
    with open(cache_path) as f:
        cache = json.load(f)

    # Load current index.html to find recently-watched shows + slug→tmdb mapping
    index_path = os.path.join(data_dir, "..", "index.html")
    if not os.path.exists(index_path):
        print("No index.html, skipping")
        return
    with open(index_path) as f:
        html = f.read()
    ds = html.find("var D=") + 6
    de = html.find(";\nvar HS=")
    if ds <= 6 or de <= ds:
        print("Can't parse index.html data blob")
        return
    data = json.loads(html[ds:de])

    # Find recently-watched show slugs (last 7 days)
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_titles = set(w["title"] for w in data.get("c", {}).get("r", [])
                        if w.get("watched_at", "") >= cutoff and w["type"] == "episode")
    tl = data.get("tl", [])
    recent_slugs = set()
    slug_to_tmdb = {}
    for t in tl:
        if t["t"] in recent_titles and t["type"] != "movie":
            sl = t.get("sl", "")
            if sl:
                recent_slugs.add(sl)
    # Get slug→tmdb mapping from persisted file
    tmdb_map_path = os.path.join(data_dir, "slug_tmdb.json")
    if os.path.exists(tmdb_map_path):
        with open(tmdb_map_path) as f:
            tmdb_map = json.load(f)
        for sl in recent_slugs:
            if sl in tmdb_map:
                slug_to_tmdb[sl] = tmdb_map[sl]
    print(f"  Slug→TMDB matches: {len(slug_to_tmdb)} of {len(recent_slugs)}")

    print(f"Recently-watched shows: {len(recent_slugs)}")

    # Find cache keys needing crew re-fetch (no crew data OR missing expanded _ac flag)
    refetch = []
    for key, sdata in cache.items():
        has_crew = any(ep.get("crew") for ep in sdata.get("episodes", []))
        has_expanded = sdata.get("_ac", False)
        if not has_crew or not has_expanded:
            tmdb_id = key.split("|")[0]
            # Check if this tmdb_id maps to a recent slug
            for sl, tid in slug_to_tmdb.items():
                if tid == tmdb_id:
                    refetch.append(key)
                    break

    print(f"Seasons to re-fetch for crew: {len(refetch)}")
    if not refetch:
        # Still generate crew_episodes.json from existing data
        _build_crew_episodes(cache, data, cutoff)
        return

    # Re-fetch
    fetched = 0
    for key in refetch:
        tmdb_id, season_num = key.split("|")
        try:
            url = f"{TMDB_BASE}/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}&append_to_response=credits"
            r = retry_request("get", url, timeout=10)
            if r and r.status_code == 200:
                sdata = r.json()
                cache[key] = {
                    "_ac": True,
                    "credits": {"cast": [{"name": c.get("name", ""), "gender": c.get("gender", 0)}
                                         for c in sdata.get("credits", {}).get("cast", [])]},
                    "episodes": [{"episode_number": ep.get("episode_number"),
                                  "guest_stars": [{"name": gs.get("name", ""), "gender": gs.get("gender", 0)}
                                                  for gs in ep.get("guest_stars", [])],
                                  "crew": [{"name": cr.get("name", ""), "job": cr.get("job", "")}
                                           for cr in ep.get("crew", [])
                                           if cr.get("job") in _CACHE_CREW_JOBS]
                                  } for ep in sdata.get("episodes", [])]
                }
                fetched += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"  Error fetching {key}: {e}")

    print(f"  Re-fetched {fetched} seasons with crew data")

    # Save updated cache
    with open(cache_path, "w") as f:
        json.dump(cache, f, separators=(",", ":"))

    # Build crew_episodes.json
    _build_crew_episodes(cache, data, cutoff)


def _build_crew_episodes(cache, data, cutoff):
    """Build crew_episodes.json from season cache."""
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    tl = data.get("tl", [])
    entries = data.get("c", {}).get("r", [])

    # Build show episodes map: slug -> {season_num: set of ep_nums}
    # and ep_watch_year: (slug, season, ep) -> year
    show_eps = defaultdict(lambda: defaultdict(set))
    ep_watch_year = {}
    for w in entries:
        if w["type"] == "episode" and w.get("detail"):
            # Parse "S2E7" format
            detail = w.get("detail", "")
            title = w["title"]
            # Find slug for this title
            slug = ""
            for t in tl:
                if t["t"] == title and t["type"] != "movie":
                    slug = t.get("sl", "")
                    break
            if not slug or not detail:
                continue
            # Parse SxEy
            parts = detail.upper().replace("S", "").split("E")
            if len(parts) == 2:
                try:
                    sn, en = int(parts[0]), int(parts[1])
                    show_eps[slug][sn].add(en)
                    yr = w.get("watched_at", "")[:4]
                    if yr:
                        ep_watch_year[(slug, sn, en)] = yr
                except ValueError:
                    pass

    # Build crew_ep_credits from cache
    tmdb_map_path = os.path.join(data_dir, "slug_tmdb.json")
    tmdb_map = {}
    if os.path.exists(tmdb_map_path):
        with open(tmdb_map_path) as f:
            tmdb_map = json.load(f)
    crew_ep = defaultdict(lambda: defaultdict(list))

    for slug, seasons in show_eps.items():
        tmdb_id = tmdb_map.get(slug, "")
        if not tmdb_id:
            continue
        for season_num, ep_nums in seasons.items():
            cache_key = f"{tmdb_id}|{season_num}"
            sdata = cache.get(cache_key)
            if not sdata:
                continue
            for ep_data in sdata.get("episodes", []):
                ep_num = ep_data.get("episode_number")
                if ep_num not in ep_nums:
                    continue
                wy = ep_watch_year.get((slug, season_num, ep_num), "")
                for cr in ep_data.get("crew", []):
                    cpid = _slugify(cr.get("name", ""))
                    if cpid:
                        crew_ep[cpid][slug].append([season_num, ep_num, wy])

    # Deduplicate and sort
    crew_out = {}
    for cpid, shows in crew_ep.items():
        crew_out[cpid] = {}
        for slug, eps in shows.items():
            seen = set()
            unique = []
            for ep in eps:
                key = (ep[0], ep[1])
                if key not in seen:
                    seen.add(key)
                    unique.append(ep)
            crew_out[cpid][slug] = sorted(unique)

    out_path = os.path.join(data_dir, "crew_episodes.json")
    with open(out_path, "w") as f:
        json.dump(crew_out, f, separators=(",", ":"))

    print(f"  crew_episodes.json: {len(crew_out)} crew members with episode credits")


if __name__ == "__main__":
    main()
