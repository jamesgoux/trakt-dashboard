#!/usr/bin/env python3
"""
Fetch Pocket Casts listening data via unofficial API.
Saves to data/pocketcasts.json (merged incrementally).

Requires POCKETCASTS_EMAIL and POCKETCASTS_PASSWORD env vars.
"""

import os, json, time, requests

EMAIL = os.environ.get("POCKETCASTS_EMAIL", "")
PASSWORD = os.environ.get("POCKETCASTS_PASSWORD", "")
BASE = "https://api.pocketcasts.com"

if not EMAIL or not PASSWORD:
    print("No POCKETCASTS_EMAIL/PASSWORD set, skipping podcast refresh")
    exit(0)

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def login():
    r = requests.post(f"{BASE}/user/login",
                      data={"email": EMAIL, "password": PASSWORD, "scope": "webplayer"},
                      timeout=15)
    if r.status_code != 200:
        print(f"  Login failed: {r.status_code}")
        return None
    return r.json().get("token")

def api_post(endpoint, token, data=None):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.post(f"{BASE}{endpoint}",
                          json=data or {"v": "1"},
                          headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"  API error {endpoint}: {e}")
    return None

print("=== Pocket Casts Refresh ===")

token = login()
if not token:
    print("  Could not authenticate"); exit(0)
print("  Logged in")

# Load existing data
pc = {}
if os.path.exists("data/pocketcasts.json"):
    with open("data/pocketcasts.json") as f:
        pc = json.load(f)

# Get subscriptions
subs_data = api_post("/user/podcast/list", token)
if not subs_data or "podcasts" not in subs_data:
    print("  Could not fetch subscriptions"); exit(0)

podcasts = subs_data["podcasts"]
print(f"  Subscriptions: {len(podcasts)}")

# Get listening history
history = api_post("/user/history", token)
history_eps = history.get("episodes", []) if history else []
print(f"  History episodes: {len(history_eps)}")

# Get stats for each podcast
stats = []
total_listened = 0
total_episodes_played = 0
total_episodes = 0

for i, pod in enumerate(podcasts):
    uuid = pod.get("uuid", "")
    title = pod.get("title", "")
    author = pod.get("author", "")
    thumbnail = pod.get("thumbnail_url", "") or pod.get("thumbnailUrl", "")

    # Get episodes for this podcast
    ep_data = api_post("/user/podcast/episodes", token, {"uuid": uuid})
    episodes = ep_data.get("episodes", []) if ep_data else []

    played_duration = 0
    played_count = 0
    ep_count = 0

    for ep in episodes:
        dur = ep.get("duration", 0) or 0
        played = ep.get("playedUpTo", 0) or 0
        if dur == 0:
            continue
        ep_count += 1
        if played > 0:
            played_count += 1
            played_duration += min(played, dur)  # cap at episode duration

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
        total_episodes += ep_count

    if (i + 1) % 10 == 0:
        print(f"  Processed {i+1}/{len(podcasts)} podcasts...")
    time.sleep(0.1)

# Sort by listen time
stats.sort(key=lambda x: x["listened_sec"], reverse=True)

# Build output
pc = {
    "total_listened_hrs": round(total_listened / 3600, 1),
    "total_episodes": total_episodes_played,
    "total_podcasts": len(stats),
    "top": stats[:25],
    "all": stats,
}

# Save
os.makedirs("data", exist_ok=True)
with open("data/pocketcasts.json", "w") as f:
    json.dump(pc, f, separators=(",", ":"))

print(f"  Total: {pc['total_listened_hrs']}h across {pc['total_episodes']} episodes, {pc['total_podcasts']} podcasts")
print("  Saved data/pocketcasts.json")
