#!/usr/bin/env python3
"""
Re-add June 30 2016 dump episodes as dateless watches.
Reads from entries_cache.json, groups by show, posts to /sync/history.
"""
import os, json, sys, time, requests
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from utils import get_trakt_access_token

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
ACCESS_TOKEN = get_trakt_access_token()
BASE = "https://api.trakt.tv"

HEADERS = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
    "trakt-api-key": CLIENT_ID,
    "Authorization": f"Bearer {ACCESS_TOKEN}",
}

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    is_dry = mode == "--dry-run"
    print(f"=== Restore June 30 Dump Episodes ({'DRY RUN' if is_dry else 'EXECUTE'}) ===\n")

    if not CLIENT_ID or not ACCESS_TOKEN:
        print("ERROR: Need TRAKT_CLIENT_ID and access token"); sys.exit(1)

    # Verify auth
    if not is_dry:
        r = requests.get(f"{BASE}/users/me", headers=HEADERS)
        if r.status_code != 200:
            print(f"ERROR: Auth failed ({r.status_code})"); sys.exit(1)
        print(f"Authenticated as: {r.json().get('username')}\n")

    # Load dump entries from cache
    cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "entries_cache.json")
    with open(cache_path) as f:
        cache = json.load(f)

    dump = [e for e in cache if e.get("watched_at", "")[:10] == "2016-06-30"
            and e.get("type") == "episode" and e.get("season") and e.get("episode_number")]

    print(f"Found {len(dump)} June 30 dump episodes in cache\n")

    # Group by show (tmdb_id) → seasons → episodes
    shows = defaultdict(lambda: defaultdict(set))
    show_meta = {}  # tmdb_id -> (title, slug)
    for e in dump:
        tid = e["tmdb_id"]
        shows[tid][int(e["season"])].add(int(e["episode_number"]))
        if tid not in show_meta:
            show_meta[tid] = (e["show_title"], e["trakt_slug"])

    # Print summary
    for tid in sorted(show_meta, key=lambda t: sum(len(eps) for eps in shows[t].values()), reverse=True):
        title, slug = show_meta[tid]
        total = sum(len(eps) for eps in shows[tid].values())
        seasons = sorted(shows[tid].keys())
        print(f"  {title:45s} {total:4d} eps  S{seasons[0]}-{seasons[-1]}")
    print(f"  {'TOTAL':45s} {len(dump):4d}")

    if is_dry:
        print(f"\nDRY RUN complete. Run with --execute to restore.")
        return

    # Build sync payload grouped by show (Trakt accepts show+season+episode format)
    total_added = 0
    total_failed = 0
    show_list = list(show_meta.keys())

    # Process in batches of shows (each show can have many episodes)
    BATCH_SIZE = 10  # shows per API call
    for i in range(0, len(show_list), BATCH_SIZE):
        batch_tids = show_list[i:i+BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(show_list) + BATCH_SIZE - 1) // BATCH_SIZE

        payload_shows = []
        batch_ep_count = 0
        for tid in batch_tids:
            title, slug = show_meta[tid]
            show_obj = {
                "ids": {"tmdb": tid},
                "seasons": []
            }
            for season_num in sorted(shows[tid].keys()):
                eps = sorted(shows[tid][season_num])
                show_obj["seasons"].append({
                    "number": season_num,
                    "episodes": [{"number": ep} for ep in eps]
                })
                batch_ep_count += len(eps)
            payload_shows.append(show_obj)

        payload = {"shows": payload_shows}

        for attempt in range(3):
            r = requests.post(f"{BASE}/sync/history", json=payload, headers=HEADERS)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                print(f"    Rate limited, waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            break

        if r.status_code == 201:
            result = r.json()
            added = result.get("added", {}).get("episodes", 0)
            nf_shows = len(result.get("not_found", {}).get("shows", []))
            nf_eps = len(result.get("not_found", {}).get("episodes", []))
            total_added += added
            total_failed += nf_shows + nf_eps
            nf_str = f", {nf_shows} shows + {nf_eps} eps not found" if (nf_shows or nf_eps) else ""
            print(f"  Batch {batch_num}/{total_batches}: {added} added ({batch_ep_count} attempted){nf_str}", flush=True)
        else:
            print(f"  Batch {batch_num}/{total_batches}: HTTP {r.status_code} — {r.text[:200]}", flush=True)
            total_failed += batch_ep_count

        time.sleep(0.5)

    print(f"\n{'='*50}")
    print(f"RESTORE COMPLETE")
    print(f"  Added:  {total_added:,}")
    print(f"  Failed: {total_failed:,}")

if __name__ == "__main__":
    main()
