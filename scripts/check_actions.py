#!/usr/bin/env python3
"""Check Trakt history action types to identify scrobbles vs API imports."""
import os, sys, time, requests
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(__file__))
from utils import get_trakt_access_token

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
ACCESS_TOKEN = get_trakt_access_token()
USERNAME = os.environ.get("TRAKT_USERNAME", "jamesgoux")
BASE = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}

all_entries = []
page = 1
print("Fetching episode history with action metadata...")
while True:
    r = requests.get(f"{BASE}/users/{USERNAME}/history/episodes",
        params={"page": page, "limit": 100}, headers=HEADERS)
    if r.status_code == 429:
        time.sleep(int(r.headers.get("Retry-After", 5))); continue
    if r.status_code != 200 or not r.json(): break
    all_entries.extend(r.json())
    tp = int(r.headers.get("X-Pagination-Page-Count", 1))
    if page == 1: print(f"  {r.headers.get('X-Pagination-Item-Count','?')} total")
    if page >= tp: break
    page += 1
    time.sleep(0.3)

print(f"  Fetched: {len(all_entries)}\n")

# Action breakdown by year
by_year_action = defaultdict(Counter)
earliest_scrobble = None
for e in all_entries:
    w = e.get("watched_at", "")
    action = e.get("action", "unknown")
    yr = w[:4] if w else "none"
    by_year_action[yr][action] += 1
    if action == "scrobble" and w:
        if not earliest_scrobble or w < earliest_scrobble:
            earliest_scrobble = w

print("Action types by year:")
print(f"  {'Year':<8} {'scrobble':>10} {'checkin':>10} {'watch':>10} {'other':>10}")
print(f"  {'-'*48}")
for yr in sorted(by_year_action.keys()):
    c = by_year_action[yr]
    print(f"  {yr:<8} {c.get('scrobble',0):>10} {c.get('checkin',0):>10} {c.get('watch',0):>10} {c.get('unknown',0):>10}")

print(f"\nEarliest scrobble: {earliest_scrobble}")

# Also check movies
print("\nFetching movie history...")
movies = []
page = 1
while True:
    r = requests.get(f"{BASE}/users/{USERNAME}/history/movies",
        params={"page": page, "limit": 100}, headers=HEADERS)
    if r.status_code == 429:
        time.sleep(5); continue
    if r.status_code != 200 or not r.json(): break
    movies.extend(r.json())
    tp = int(r.headers.get("X-Pagination-Page-Count", 1))
    if page >= tp: break
    page += 1
    time.sleep(0.3)

print(f"  Fetched: {len(movies)} movies\n")
mv_actions = defaultdict(Counter)
for e in movies:
    w = e.get("watched_at", "")
    action = e.get("action", "unknown")
    yr = w[:4] if w else "none"
    mv_actions[yr][action] += 1

print("Movie action types by year:")
print(f"  {'Year':<8} {'scrobble':>10} {'checkin':>10} {'watch':>10}")
print(f"  {'-'*38}")
for yr in sorted(mv_actions.keys()):
    c = mv_actions[yr]
    print(f"  {yr:<8} {c.get('scrobble',0):>10} {c.get('checkin',0):>10} {c.get('watch',0):>10}")
