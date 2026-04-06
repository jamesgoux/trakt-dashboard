#!/usr/bin/env python3
"""
Backfill daily Last.fm scrobble counts.
Builds data/lastfm_daily.json incrementally — fetches ~100 days per run
working backwards from the oldest day we have, until we reach the account creation date.

Uses user.getrecenttracks with from/to timestamps to count scrobbles per day.
Designed to run on the daily schedule alongside headshot backfill.
"""

import json, os, sys, time
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_tz_pac = ZoneInfo("America/Los_Angeles")
_utc = ZoneInfo("UTC")

LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")
LASTFM_USER = os.environ.get("LASTFM_USER", "")
BUDGET = int(os.environ.get("LASTFM_DAILY_BUDGET", "100"))  # days per run

if not LASTFM_API_KEY or not LASTFM_USER:
    print("No LASTFM_API_KEY/LASTFM_USER set, skipping daily backfill")
    sys.exit(0)

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "https://ws.audioscrobbler.com/2.0/"

def api(method, **params):
    params["api_key"] = LASTFM_API_KEY
    params["user"] = LASTFM_USER
    params["format"] = "json"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}?method={method}&{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "Iris/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  API error: {e}")
        return None

def load_json(path):
    if os.path.exists(path):
        with open(path) as f: return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, separators=(",", ":"))

print("=== Last.fm Daily Scrobble Backfill ===")

# Load existing daily data: {"2025-03-01": 42, "2025-03-02": 15, ...}
daily = load_json("data/lastfm_daily.json")
print(f"  Existing days: {len(daily)}")

# Get account registration date
info = api("user.getinfo")
if not info:
    print("  Could not fetch user info"); sys.exit(0)
reg_ts = int(info["user"].get("registered", {}).get("unixtime", 0))
if reg_ts:
    reg_date = datetime.fromtimestamp(reg_ts, tz=_utc).astimezone(_tz_pac).date()
    print(f"  Account registered: {reg_date}")
else:
    reg_date = datetime(2004, 1, 1).date()
    print(f"  No registration date, assuming {reg_date}")

today = datetime.now(_tz_pac).date()

# Strategy: work backwards from the oldest day we have (or today if empty)
if daily:
    existing_dates = sorted(daily.keys())
    oldest_existing = datetime.strptime(existing_dates[0], "%Y-%m-%d").date()
    newest_existing = datetime.strptime(existing_dates[-1], "%Y-%m-%d").date()
    print(f"  Range: {oldest_existing} to {newest_existing}")
    
    # Also fill forward from newest to today
    forward_start = newest_existing + timedelta(days=1)
    backward_end = oldest_existing - timedelta(days=1)
else:
    forward_start = today - timedelta(days=30)  # start with last 30 days
    backward_end = forward_start - timedelta(days=1)
    print("  No existing data, starting fresh")

# Phase 1: Fill forward (recent days we're missing)
forward_days = []
d = forward_start
while d <= today:
    ds = d.strftime("%Y-%m-%d")
    if ds not in daily:
        forward_days.append(d)
    d += timedelta(days=1)

# Phase 2: Fill backward (historical days)
backward_days = []
d = backward_end
while d >= reg_date and len(backward_days) < BUDGET:
    ds = d.strftime("%Y-%m-%d")
    if ds not in daily:
        backward_days.append(d)
    d -= timedelta(days=1)

# Prioritize forward (recent) then backward (historical)
to_fetch = forward_days + backward_days
to_fetch = to_fetch[:BUDGET]

if not to_fetch:
    print("  All days already fetched!")
    save_json("data/lastfm_daily.json", daily)
    sys.exit(0)

print(f"  Fetching {len(to_fetch)} days ({to_fetch[0]} to {to_fetch[-1]})")

fetched = 0
for i, d in enumerate(to_fetch):
    ds = d.strftime("%Y-%m-%d")
    day_start = datetime(d.year, d.month, d.day, tzinfo=_tz_pac)
    start_ts = int(day_start.timestamp())
    end_ts = int((day_start + timedelta(days=1)).timestamp())
    
    data = api("user.getrecenttracks", limit=1, **{"from": str(start_ts), "to": str(end_ts)})
    if data:
        attrs = data.get("recenttracks", {}).get("@attr", {})
        count = int(attrs.get("total", 0))
        daily[ds] = count
        fetched += 1
    
    if (i + 1) % 25 == 0:
        print(f"    {i+1}/{len(to_fetch)} days fetched...")
        save_json("data/lastfm_daily.json", daily)
    
    time.sleep(0.2)

save_json("data/lastfm_daily.json", daily)

total_days = len(daily)
total_range = (today - reg_date).days
pct = round(total_days / total_range * 100, 1) if total_range > 0 else 0
print(f"  Fetched {fetched} new days. Total: {total_days}/{total_range} days ({pct}% complete)")
print("Done!")
