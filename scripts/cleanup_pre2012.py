#!/usr/bin/env python3
"""
Remove pre-2012 dated episodes and re-add with epoch timestamp (truly dateless).
These are leftovers from bulk imports where Trakt assigned release dates.
"""
import os, json, sys, time, requests
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from utils import get_trakt_access_token

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
ACCESS_TOKEN = get_trakt_access_token()
USERNAME = os.environ.get("TRAKT_USERNAME", "jamesgoux")
BASE = "https://api.trakt.tv"
EPOCH = "1970-01-01T00:00:00.000Z"
CUTOFF = "2012-01-01"

HEADERS_READ = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
    "trakt-api-key": CLIENT_ID,
}
HEADERS_WRITE = {**HEADERS_READ, "Authorization": f"Bearer {ACCESS_TOKEN}"}

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    is_dry = mode == "--dry-run"
    print(f"=== Pre-2012 Cleanup ({'DRY RUN' if is_dry else 'EXECUTE'}) ===\n")

    if not CLIENT_ID or not ACCESS_TOKEN:
        print("ERROR: Need TRAKT_CLIENT_ID and access token"); sys.exit(1)

    if not is_dry:
        r = requests.get(f"{BASE}/users/me", headers=HEADERS_WRITE)
        if r.status_code != 200:
            print(f"ERROR: Auth failed ({r.status_code})"); sys.exit(1)
        print(f"Authenticated as: {r.json().get('username')}\n")

    # Fetch all episode history
    print("Fetching episode history...")
    all_entries = []
    page = 1
    while True:
        r = requests.get(f"{BASE}/users/{USERNAME}/history/episodes",
            params={"page": page, "limit": 100, "extended": "full"}, headers=HEADERS_READ)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 5))); continue
        if r.status_code != 200 or not r.json(): break
        all_entries.extend(r.json())
        total_pages = int(r.headers.get("X-Pagination-Page-Count", 1))
        if page == 1:
            print(f"  {r.headers.get('X-Pagination-Item-Count', '?')} total across {total_pages} pages")
        if page >= total_pages: break
        page += 1
        time.sleep(0.3)
    print(f"  Fetched: {len(all_entries)}")

    # Find pre-2012 dated entries
    candidates = []
    for e in all_entries:
        w = e.get("watched_at", "")
        if not w or w[:10] >= CUTOFF or w[:4] <= "1970":
            continue
        ep = e.get("episode", {})
        show = e.get("show", {})
        candidates.append({
            "history_id": e.get("id"),
            "trakt_ep_id": ep.get("ids", {}).get("trakt"),
            "show": show.get("title", ""),
            "season": ep.get("season"),
            "episode": ep.get("number"),
            "watched_at": w[:10],
            "type": e.get("type", "episode"),
        })

    # Also check movies
    print("Fetching movie history...")
    page = 1
    while True:
        r = requests.get(f"{BASE}/users/{USERNAME}/history/movies",
            params={"page": page, "limit": 100}, headers=HEADERS_READ)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 5))); continue
        if r.status_code != 200 or not r.json(): break
        for e in r.json():
            w = e.get("watched_at", "")
            if w and w[:10] < CUTOFF and w[:4] > "1970":
                mv = e.get("movie", {})
                candidates.append({
                    "history_id": e.get("id"),
                    "trakt_movie_id": mv.get("ids", {}).get("trakt"),
                    "show": mv.get("title", ""),
                    "season": None,
                    "episode": None,
                    "watched_at": w[:10],
                    "type": "movie",
                })
        total_pages = int(r.headers.get("X-Pagination-Page-Count", 1))
        if page >= total_pages: break
        page += 1
        time.sleep(0.3)

    print(f"\nPre-2012 entries found: {len(candidates)}")

    by_show = defaultdict(list)
    for c in candidates:
        by_show[c["show"]].append(c)

    for show in sorted(by_show, key=lambda x: len(by_show[x]), reverse=True):
        eps = by_show[show]
        dates = sorted(set(e["watched_at"] for e in eps))
        yr_range = f"{dates[0][:4]}-{dates[-1][:4]}" if dates[0][:4] != dates[-1][:4] else dates[0][:4]
        t = eps[0]["type"]
        print(f"  {show:45s} {len(eps):3d} {'eps' if t=='episode' else 'mov'}  {yr_range}")

    if is_dry:
        print(f"\nDRY RUN complete. Run with --execute to clean up.")
        return

    # Step 1: Remove
    history_ids = [c["history_id"] for c in candidates]
    print(f"\nStep 1: Removing {len(history_ids)} history entries...")
    for i in range(0, len(history_ids), 200):
        batch = history_ids[i:i+200]
        for attempt in range(3):
            r = requests.post(f"{BASE}/sync/history/remove",
                json={"ids": batch}, headers=HEADERS_WRITE)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 10))); continue
            break
        if r.status_code == 200:
            d = r.json().get("deleted", {})
            print(f"  Batch: {d.get('episodes',0)} eps + {d.get('movies',0)} movies removed")
        else:
            print(f"  Batch: HTTP {r.status_code}")
        time.sleep(0.3)

    # Step 2: Re-add episodes with epoch
    ep_ids = list(set(c["trakt_ep_id"] for c in candidates if c["type"] == "episode" and c.get("trakt_ep_id")))
    movie_ids = list(set(c["trakt_movie_id"] for c in candidates if c["type"] == "movie" and c.get("trakt_movie_id")))

    if ep_ids:
        print(f"\nStep 2a: Re-adding {len(ep_ids)} episodes with epoch timestamp...")
        for i in range(0, len(ep_ids), 200):
            batch = ep_ids[i:i+200]
            body = {"episodes": [{"ids": {"trakt": tid}, "watched_at": EPOCH} for tid in batch]}
            for attempt in range(3):
                r = requests.post(f"{BASE}/sync/history", json=body, headers=HEADERS_WRITE)
                if r.status_code == 429:
                    time.sleep(int(r.headers.get("Retry-After", 10))); continue
                break
            if r.status_code == 201:
                print(f"  {r.json().get('added',{}).get('episodes',0)} episodes added")
            else:
                print(f"  HTTP {r.status_code}")
            time.sleep(0.3)

    if movie_ids:
        print(f"\nStep 2b: Re-adding {len(movie_ids)} movies with epoch timestamp...")
        body = {"movies": [{"ids": {"trakt": tid}, "watched_at": EPOCH} for tid in movie_ids]}
        r = requests.post(f"{BASE}/sync/history", json=body, headers=HEADERS_WRITE)
        if r.status_code == 201:
            print(f"  {r.json().get('added',{}).get('movies',0)} movies added")
        else:
            print(f"  HTTP {r.status_code}")

    print(f"\nDone! All pre-2012 entries moved to dateless (epoch).")

if __name__ == "__main__":
    main()
