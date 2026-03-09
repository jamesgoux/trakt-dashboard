#!/usr/bin/env python3
"""
Fetch Pocket Casts listening data via unofficial API.
Saves to data/pocketcasts.json (stats + top podcasts)
and data/pocketcasts_history.json (listen events with timestamps).

Strategy for listen dates:
1. POLLING (primary): Snapshot playedUpTo each run. When progress changes, log with current timestamp.
2. PUBLISH DATE (fallback): For episodes already fully played before polling started, use episode publish date.

Requires POCKETCASTS_EMAIL and POCKETCASTS_PASSWORD env vars.
"""

import os, json, time, requests
from datetime import datetime, timezone
from utils import retry_request

EMAIL = os.environ.get("POCKETCASTS_EMAIL", "")
PASSWORD = os.environ.get("POCKETCASTS_PASSWORD", "")
BASE = "https://api.pocketcasts.com"

if not EMAIL or not PASSWORD:
    print("No POCKETCASTS_EMAIL/PASSWORD set, skipping podcast refresh")
    exit(0)

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs("data", exist_ok=True)

def login():
    try:
        r = requests.post(f"{BASE}/user/login",
                          data={"email": EMAIL, "password": PASSWORD, "scope": "webplayer"},
                          timeout=15)
        if r.status_code == 200:
            return r.json().get("token")
        print(f"  Login failed: {r.status_code}")
    except Exception as e:
        print(f"  Login error: {e}")
    return None

def api_post(endpoint, token, data=None):
    headers = {"Authorization": f"Bearer {token}"}
    r = retry_request("post", f"{BASE}{endpoint}",
                      json=data or {"v": "1"},
                      headers=headers, timeout=15)
    if r and r.status_code == 200:
        return r.json()
    return None

def load_json(path):
    if os.path.exists(path):
        with open(path) as f: return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, separators=(",", ":"))

print("=== Pocket Casts Refresh ===")

token = login()
if not token:
    print("  Could not authenticate"); exit(0)
print("  Logged in")

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
now_date = now[:10]

# Load previous snapshot for polling comparison
snapshot = load_json("data/pocketcasts_snapshot.json")  # {ep_uuid: playedUpTo}
history = load_json("data/pocketcasts_history.json")    # {ep_uuid: {podcast, title, date, dur, played}}

# Get subscriptions
subs_data = api_post("/user/podcast/list", token)
if not subs_data or "podcasts" not in subs_data:
    print("  Could not fetch subscriptions"); exit(0)

podcasts = subs_data["podcasts"]
print(f"  Subscriptions: {len(podcasts)}")

new_snapshot = {}
new_events = 0
stats = []
total_listened = 0
total_episodes_played = 0

for i, pod in enumerate(podcasts):
    uuid = pod.get("uuid", "")
    title = pod.get("title", "")
    author = pod.get("author", "")
    thumbnail = pod.get("thumbnail_url", "") or pod.get("thumbnailUrl", "")

    ep_data = api_post("/user/podcast/episodes", token, {"uuid": uuid})
    episodes = ep_data.get("episodes", []) if ep_data else []

    played_duration = 0
    played_count = 0
    ep_count = 0

    for ep in episodes:
        ep_uuid = ep.get("uuid", "")
        dur = ep.get("duration", 0) or 0
        played = ep.get("playedUpTo", 0) or 0
        ep_title = ep.get("title", "")
        published = ep.get("published", "") or ""  # ISO date string

        if dur == 0 or not ep_uuid:
            continue
        ep_count += 1

        # Save current state to snapshot
        new_snapshot[ep_uuid] = played

        if played > 0:
            played_count += 1
            played_duration += min(played, dur)

            # POLLING: Check if progress changed since last snapshot
            old_played = snapshot.get(ep_uuid, -1)

            if ep_uuid not in history:
                if old_played >= 0 and played > old_played:
                    # Progress changed since last run — log with current timestamp
                    listen_date = now_date
                    history[ep_uuid] = {
                        "p": title,        # podcast name
                        "t": ep_title,     # episode title
                        "d": listen_date,  # when we detected the listen
                        "dur": dur,
                        "played": min(played, dur),
                        "src": "poll"
                    }
                    new_events += 1
                elif old_played == -1:
                    # First time seeing this episode (no previous snapshot)
                    # FALLBACK: Use publish date if available
                    if published:
                        try:
                            pub_date = published[:10]  # "2025-03-01T..."
                            if len(pub_date) == 10:
                                listen_date = pub_date
                            else:
                                listen_date = now_date
                        except Exception:
                            listen_date = now_date
                    else:
                        listen_date = now_date

                    history[ep_uuid] = {
                        "p": title,
                        "t": ep_title,
                        "d": listen_date,
                        "dur": dur,
                        "played": min(played, dur),
                        "src": "pub" if published else "init"
                    }
                    new_events += 1

    if played_count > 0:
        stats.append({
            "uuid": uuid,
            "title": title,
            "author": author,
            "img": thumbnail,
            "played": played_count,
            "total_eps": ep_count,
            "listened_sec": played_duration,
            "listened_hrs": round(played_duration / 3600, 1),
        })
        total_listened += played_duration
        total_episodes_played += played_count

    if (i + 1) % 10 == 0:
        print(f"  Processed {i+1}/{len(podcasts)} podcasts...")
    time.sleep(0.1)

stats.sort(key=lambda x: x["listened_sec"], reverse=True)

# Build yearly/monthly aggregates from history
yearly = {}   # year -> {hrs, eps}
monthly = {}  # YYYY-MM -> {hrs, eps}
for ev in history.values():
    d = ev.get("d", "")
    if len(d) < 7:
        continue
    yr = d[:4]
    mo = d[:7]
    dur_hrs = (ev.get("played", 0) or ev.get("dur", 0)) / 3600

    if yr not in yearly:
        yearly[yr] = {"hrs": 0, "eps": 0}
    yearly[yr]["hrs"] = round(yearly[yr]["hrs"] + dur_hrs, 1)
    yearly[yr]["eps"] += 1

    if mo not in monthly:
        monthly[mo] = {"hrs": 0, "eps": 0}
    monthly[mo]["hrs"] = round(monthly[mo]["hrs"] + dur_hrs, 1)
    monthly[mo]["eps"] += 1

# Build output
pc = {
    "total_listened_hrs": round(total_listened / 3600, 1),
    "total_episodes": total_episodes_played,
    "total_podcasts": len(stats),
    "top": stats[:25],
    "yearly": [{"yr": y, **d} for y, d in sorted(yearly.items())],
    "monthly": [{"month": m, **d} for m, d in sorted(monthly.items())],
}

# Save everything
save_json("data/pocketcasts.json", pc)
save_json("data/pocketcasts_snapshot.json", new_snapshot)
save_json("data/pocketcasts_history.json", history)

print(f"  Total: {pc['total_listened_hrs']}h across {pc['total_episodes']} episodes, {pc['total_podcasts']} podcasts")
print(f"  History: {len(history)} episodes tracked, {new_events} new events this run")
print(f"  Sources: {sum(1 for v in history.values() if v.get('src')=='poll')} polled, "
      f"{sum(1 for v in history.values() if v.get('src')=='pub')} from publish date, "
      f"{sum(1 for v in history.values() if v.get('src')=='init')} initial")
print("  Done")
