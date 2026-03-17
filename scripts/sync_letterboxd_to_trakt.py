#!/usr/bin/env python3
"""
One-time sync: Post Letterboxd backfill watches to Trakt.
Uses the slug cache from refresh_data.py to find Trakt movie IDs.
After successful sync, marks entries so they aren't synced again.

Requires: TRAKT_CLIENT_ID, TRAKT_ACCESS_TOKEN
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, time, requests
from utils import retry_request, get_trakt_access_token

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID", "")
ACCESS_TOKEN = get_trakt_access_token()

if not CLIENT_ID or not ACCESS_TOKEN:
    print("Need TRAKT_CLIENT_ID and TRAKT_ACCESS_TOKEN, skipping sync")
    exit(0)

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "https://api.trakt.tv"
HEADERS = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
    "trakt-api-key": CLIENT_ID,
    "Authorization": f"Bearer {ACCESS_TOKEN}",
}

# Skip if already done
if os.path.exists("data/.lb_trakt_sync_done"):
    print("Letterboxd→Trakt sync already completed, skipping")
    exit(0)

print("=== Letterboxd → Trakt Sync ===")

# Load slug cache (title|year -> trakt_slug)
slug_cache = {}
if os.path.exists("data/lb_slug_cache.json"):
    with open("data/lb_slug_cache.json") as f:
        slug_cache = json.load(f)

# Load Letterboxd data
if not os.path.exists("data/letterboxd.json"):
    print("No letterboxd.json found"); exit(0)
with open("data/letterboxd.json") as f:
    lb = json.load(f)

# Load existing Trakt history to avoid duplicates
# We'll fetch current history and check against it
print("  Fetching current Trakt movie history...")
trakt_history = set()  # (slug, date) pairs
page = 1
while True:
    r = retry_request("get", f"{BASE}/users/me/history/movies",
                      params={"page": page, "limit": 100},
                      headers=HEADERS, timeout=15)
    if not r or r.status_code != 200:
        break
    batch = r.json()
    if not batch:
        break
    for e in batch:
        slug = e.get("movie", {}).get("ids", {}).get("slug", "")
        wa = e.get("watched_at", "")[:10]
        if slug and wa:
            trakt_history.add((slug, wa))
    if page >= int(r.headers.get("X-Pagination-Page-Count", 1)):
        break
    page += 1
    time.sleep(0.3)
print(f"  Trakt has {len(trakt_history)} movie watches")

# Build list of watches to sync
to_sync = []
for lb_key, entry in lb.items():
    title = entry.get("title", "")
    year = str(entry.get("year", ""))
    cache_key = f"{title}|{year}"
    slug = slug_cache.get(cache_key, "")
    
    if not slug:
        continue
    
    for date in entry.get("dates", []):
        if not date or date[:4] < "2015" or date[:4] > "2022":
            continue
        # Check if already in Trakt (within same day)
        if (slug, date) in trakt_history:
            continue
        to_sync.append({
            "title": title,
            "year": year,
            "slug": slug,
            "date": date,
        })

print(f"  Watches to sync: {to_sync.__len__()} (2015-2022, not already in Trakt)")

if not to_sync:
    print("  Nothing to sync!")
    with open("data/.lb_trakt_sync_done", "w") as f:
        f.write("no watches needed")
    exit(0)

# Trakt's sync/history endpoint accepts batches of up to 100
synced = 0
failed = 0
for i in range(0, len(to_sync), 50):
    batch = to_sync[i:i+50]
    movies = []
    for w in batch:
        movies.append({
            "watched_at": w["date"] + "T20:00:00.000Z",
            "ids": {"slug": w["slug"]},
        })
    
    r = retry_request("post", f"{BASE}/sync/history",
                      json={"movies": movies},
                      headers=HEADERS, timeout=30)
    
    if r and r.status_code in (200, 201):
        result = r.json()
        added = result.get("added", {}).get("movies", 0)
        synced += added
        print(f"  Batch {i//50+1}: +{added} movies synced")
    else:
        status = r.status_code if r else "no response"
        print(f"  Batch {i//50+1}: failed ({status})")
        failed += len(batch)
    
    time.sleep(1)  # be nice to the API

print(f"\n  Synced: {synced}, Failed: {failed}")

# Mark as done
if failed == 0:
    with open("data/.lb_trakt_sync_done", "w") as f:
        from datetime import datetime
        f.write(f"Synced {synced} watches on {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("  Marked as complete — won't run again")
else:
    print("  Some failures — will retry next run")

print("Done!")
