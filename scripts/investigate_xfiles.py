#!/usr/bin/env python3
"""Quick investigation: check X-Files episodes in Trakt API and diagnose airdate matching."""
import os, json, time, requests
from datetime import datetime, timedelta

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
USERNAME = os.environ.get("TRAKT_USERNAME", "jamesgoux")
HEADERS = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
    "trakt-api-key": CLIENT_ID,
}

# Fetch X-Files show info
slug = "the-x-files"
print(f"=== Investigating {slug} ===\n")

# Get show progress (which seasons/episodes are watched)
url = f"https://api.trakt.tv/users/{USERNAME}/history/episodes"
params = {"limit": 100, "extended": "full"}

# Fetch all X-Files history
all_xf = []
page = 1
while True:
    params["page"] = page
    r = requests.get(url, headers=HEADERS, params=params)
    if r.status_code != 200:
        print(f"Error: {r.status_code}")
        break
    entries = r.json()
    if not entries:
        break
    xf = [e for e in entries if e.get("show", {}).get("ids", {}).get("slug") == slug]
    all_xf.extend(xf)
    total_pages = int(r.headers.get("X-Pagination-Page-Count", 1))
    if page >= total_pages:
        break
    page += 1
    time.sleep(0.3)

print(f"Total X-Files episodes in history: {len(all_xf)}\n")

# Analyze each
from collections import defaultdict
by_season = defaultdict(list)

for e in all_xf:
    ep = e.get("episode", {})
    season = ep.get("season")
    number = ep.get("number")
    watched_raw = e.get("watched_at", "")
    aired_raw = ep.get("first_aired", "")
    history_id = e.get("id")
    
    watched_date = watched_raw[:10] if watched_raw else "?"
    aired_date = aired_raw[:10] if aired_raw else "?"
    
    # Also compare with timezone awareness
    match_utc = watched_date == aired_date
    
    # Check ±1 day match
    near_miss = False
    if watched_raw and aired_raw:
        try:
            w = datetime.fromisoformat(watched_raw.replace("Z", "+00:00")).date()
            a = datetime.fromisoformat(aired_raw.replace("Z", "+00:00")).date()
            diff = abs((w - a).days)
            near_miss = diff <= 1 and not match_utc
        except:
            pass
    
    by_season[season].append({
        "ep": number,
        "watched_raw": watched_raw,
        "aired_raw": aired_raw,
        "watched_date": watched_date,
        "aired_date": aired_date,
        "match": match_utc,
        "near_miss": near_miss,
        "history_id": history_id,
    })

for season in sorted(by_season.keys()):
    eps = sorted(by_season[season], key=lambda x: x["ep"])
    matches = sum(1 for e in eps if e["match"])
    near = sum(1 for e in eps if e["near_miss"])
    print(f"\n--- Season {season} ({len(eps)} episodes, {matches} airdate matches, {near} near-misses ±1 day) ---")
    for ep in eps:
        flag = "✓ MATCH" if ep["match"] else ("⚠ NEAR" if ep["near_miss"] else "")
        print(f"  S{season:02d}E{ep['ep']:02d}: watched={ep['watched_date']}  aired={ep['aired_date']}  {flag}")
        if ep["near_miss"] or ep["match"]:
            print(f"          raw: watched={ep['watched_raw']}")
            print(f"               aired  ={ep['aired_raw']}")

# Also check for near-miss airdate matches across ALL shows
print(f"\n\n=== Near-miss check (±1 day) across all shows ===")
near_miss_total = 0
page = 1
near_miss_shows = defaultdict(int)
while True:
    params["page"] = page
    r = requests.get(url, headers=HEADERS, params=params)
    if r.status_code != 200:
        break
    entries = r.json()
    if not entries:
        break
    total_pages = int(r.headers.get("X-Pagination-Page-Count", 1))
    
    for e in entries:
        ep = e.get("episode", {})
        w_str = e.get("watched_at", "")
        a_str = ep.get("first_aired", "")
        if not w_str or not a_str:
            continue
        w_date = w_str[:10]
        a_date = a_str[:10]
        if w_date == a_date:
            continue  # exact match already handled
        try:
            w = datetime.fromisoformat(w_str.replace("Z", "+00:00")).date()
            a = datetime.fromisoformat(a_str.replace("Z", "+00:00")).date()
            if abs((w - a).days) == 1:
                near_miss_total += 1
                show = e.get("show", {}).get("title", "?")
                near_miss_shows[show] += 1
        except:
            pass
    
    if page >= total_pages:
        break
    page += 1
    time.sleep(0.3)

print(f"Total near-miss (±1 day, not exact match): {near_miss_total}")
if near_miss_shows:
    print(f"\nShows with near-misses:")
    for show in sorted(near_miss_shows, key=lambda x: near_miss_shows[x], reverse=True)[:30]:
        print(f"  {show:45s} {near_miss_shows[show]:4d}")
