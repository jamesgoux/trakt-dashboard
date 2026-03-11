#!/usr/bin/env python3
"""Fetch Up Next data from Trakt — next unwatched episode for each in-progress show."""
import os, sys, json, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import retry_request

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
USERNAME = os.environ.get("TRAKT_USERNAME")
ACCESS_TOKEN = os.environ.get("TRAKT_ACCESS_TOKEN", "")
BASE = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}
AUTH_HEADERS = {**HEADERS, "Authorization": f"Bearer {ACCESS_TOKEN}"} if ACCESS_TOKEN else HEADERS

if not CLIENT_ID or not USERNAME:
    print("ERROR: Set TRAKT_CLIENT_ID and TRAKT_USERNAME"); sys.exit(1)
if not ACCESS_TOKEN:
    print("WARNING: TRAKT_ACCESS_TOKEN not set — progress endpoint requires OAuth")

# How many days a "new" episode stays pinned
NEW_PIN_DAYS = 30

def run():
    print("Fetching watched shows...")
    r = retry_request("get", f"{BASE}/users/{USERNAME}/watched/shows?extended=full",
                      headers=AUTH_HEADERS, timeout=15)
    if not r or r.status_code != 200:
        print(f"Failed to fetch watched shows: {r.status_code if r else 'no response'}")
        return
    watched = r.json()
    print(f"  {len(watched)} shows in watch history")

    # Load existing up_next data for incremental updates
    existing = {}
    if os.path.exists("data/up_next.json"):
        with open("data/up_next.json") as f:
            for item in json.load(f):
                existing[item["slug"]] = item

    # Load posters for show images
    posters = {}
    if os.path.exists("data/posters.json"):
        with open("data/posters.json") as f:
            posters = json.load(f)

    now = datetime.now(timezone.utc)
    results = []
    total = len(watched)

    for i, show_data in enumerate(watched):
        show = show_data.get("show", {})
        slug = show.get("ids", {}).get("slug", "")
        if not slug:
            continue

        # Get last watched timestamp from the history
        last_watched = show_data.get("last_watched_at", "")

        # Fetch progress for this show
        r2 = retry_request("get", f"{BASE}/shows/{slug}/progress/watched?extended=full",
                           headers=AUTH_HEADERS, timeout=10)
        if not r2 or r2.status_code != 200:
            time.sleep(0.3)
            continue

        prog = r2.json()
        next_ep = prog.get("next_episode")
        if not next_ep:
            # Show is fully caught up or completed
            # Check if there are aired episodes we haven't watched (show might have ended)
            aired = prog.get("aired", 0)
            completed = prog.get("completed", 0)
            if aired <= completed:
                continue  # Fully caught up, skip
            # Otherwise the progress endpoint didn't return next_episode for some reason
            continue

        # Build the entry
        ep_aired = next_ep.get("first_aired", "")
        is_aired = False
        aired_days_ago = None
        if ep_aired:
            try:
                aired_dt = datetime.fromisoformat(ep_aired.replace("Z", "+00:00"))
                is_aired = aired_dt <= now
                aired_days_ago = (now - aired_dt).days
            except Exception:
                pass

        # "New" pin: episode aired within the last NEW_PIN_DAYS days
        is_new = is_aired and aired_days_ago is not None and aired_days_ago <= NEW_PIN_DAYS

        # Find poster
        poster = posters.get(slug, "")

        # Compute remaining unwatched runtime from season data
        remaining_min = 0
        ep_runtime = next_ep.get("runtime", 0) or show.get("runtime", 0) or 0
        seasons_data = prog.get("seasons", [])
        next_s = next_ep.get("season", 0)
        next_n = next_ep.get("number", 0)
        for sn in seasons_data:
            sn_num = sn.get("number", 0)
            for ep in sn.get("episodes", []):
                ep_num = ep.get("number", 0)
                if not ep.get("completed", False):
                    # Use episode runtime if available, else show default
                    rt = ep.get("runtime") or ep_runtime
                    remaining_min += rt

        entry = {
            "slug": slug,
            "show": show.get("title", ""),
            "network": show.get("network", ""),
            "trakt_id": show.get("ids", {}).get("trakt", ""),
            "season": next_s,
            "episode": next_n,
            "ep_title": next_ep.get("title", ""),
            "ep_runtime": ep_runtime,
            "ep_aired": ep_aired[:10] if ep_aired else "",
            "ep_trakt_id": next_ep.get("ids", {}).get("trakt", ""),
            "is_aired": is_aired,
            "aired_days_ago": aired_days_ago,
            "is_new": is_new,
            "last_watched": last_watched,
            "poster": poster,
            "aired_total": prog.get("aired", 0),
            "completed": prog.get("completed", 0),
            "remaining_min": remaining_min,
        }
        results.append(entry)

        if (i + 1) % 50 == 0:
            print(f"  progress: {i+1}/{total}")
        time.sleep(0.8)

    # Sort: new-pinned first (by aired date desc), then by last_watched desc
    results.sort(key=lambda x: (
        not x["is_new"],           # new items first
        x.get("ep_aired", "") if x["is_new"] else "",  # newest aired first among new
        "" if not x["last_watched"] else x["last_watched"]
    ))
    # Re-sort: within non-new, sort by last_watched descending
    new_items = [r for r in results if r["is_new"]]
    new_items.sort(key=lambda x: x.get("ep_aired", ""), reverse=True)
    rest = [r for r in results if not r["is_new"]]
    rest.sort(key=lambda x: x.get("last_watched", ""), reverse=True)
    results = new_items + rest

    os.makedirs("data", exist_ok=True)
    with open("data/up_next.json", "w") as f:
        json.dump(results, f, separators=(',', ':'))
    print(f"  Saved {len(results)} shows to up_next.json ({len(new_items)} new)")

if __name__ == "__main__":
    run()
