#!/usr/bin/env python3
"""
Fetch Serializd TV show ratings via their internal API.
Saves to data/serializd.json with show name, rating (1-10), date, TMDB IDs.
"""
import os, json, time, requests
from user_config import load_user_config, get_service
_ucfg = load_user_config()


BASE = "https://www.serializd.com/api"
HEADERS = {
    "Origin": "https://www.serializd.com",
    "Referer": "https://www.serializd.com",
    "X-Requested-With": "serializd_vercel",
    "Content-Type": "application/json",
}

email = get_service(_ucfg, "serializd", "email") or os.environ.get("SERIALIZD_EMAIL")
password = get_service(_ucfg, "serializd", "password") or os.environ.get("SERIALIZD_PASSWORD")
if not email or not password:
    print("SERIALIZD: No credentials, skipping"); exit(0)

# Login
print("Serializd: logging in...")
r = requests.post(f"{BASE}/login", headers=HEADERS, json={"email": email, "password": password}, timeout=10)
if r.status_code != 200:
    print(f"Serializd: login failed ({r.status_code})"); exit(1)

login_data = r.json()
username = login_data.get("username", "")
token = login_data.get("token", "")
if not token:
    print("Serializd: no token in login response"); exit(1)

session = requests.Session()
session.headers.update(HEADERS)
session.cookies.set("tvproject_credentials", token, domain=".serializd.com")

# Load existing data
os.makedirs("data", exist_ok=True)
existing = {}
if os.path.exists("data/serializd.json"):
    with open("data/serializd.json") as f:
        existing = json.load(f)

# Fetch all diary pages (ratings)
all_reviews = []
page = 1
total_pages = 1

while page <= total_pages:
    url = f"{BASE}/user/{username}/diary?page={page}"
    r = session.get(url, timeout=10)
    if r.status_code != 200:
        print(f"  Page {page}: HTTP {r.status_code}, stopping")
        break
    data = r.json()
    reviews = data.get("reviews", [])
    total_pages = data.get("totalPages", 1)
    all_reviews.extend(reviews)
    print(f"  Page {page}/{total_pages}: {len(reviews)} entries")
    page += 1
    time.sleep(0.3)

print(f"Serializd: {len(all_reviews)} total diary entries")

# Resolve show names from TMDB IDs (use Serializd's show endpoint)
show_cache = {}
for rev in all_reviews:
    sid = rev.get("showId")
    if sid and sid not in show_cache:
        show_cache[sid] = None  # placeholder

# Fetch show names and season mappings
print(f"Resolving {len(show_cache)} show names...")
season_map = {}  # season_id -> season_number
for i, sid in enumerate(list(show_cache.keys())):
    # Check if we already have this show cached with seasons
    if existing.get(str(sid), {}).get("name") and existing.get(str(sid), {}).get("seasons"):
        show_cache[sid] = existing[str(sid)]["name"]
        for sn_id, sn_num in existing[str(sid)]["seasons"].items():
            season_map[int(sn_id)] = sn_num
        continue
    try:
        r2 = session.get(f"{BASE}/show/{sid}", timeout=8)
        if r2.status_code == 200:
            show_data = r2.json()
            show_cache[sid] = show_data.get("name", f"Show {sid}")
            for s in show_data.get("seasons", []):
                season_map[s["id"]] = s["seasonNumber"]
        else:
            show_cache[sid] = f"Show {sid}"
    except Exception:
        show_cache[sid] = f"Show {sid}"
    if (i + 1) % 20 == 0:
        print(f"  {i+1}/{len(show_cache)} shows resolved")
    time.sleep(0.2)

# Build output: keyed by TMDB show ID, only season-level ratings
output = {}
skipped_show_level = 0
for rev in all_reviews:
    sid = str(rev.get("showId", ""))
    if not sid:
        continue
    season_id = rev.get("seasonId")
    # Skip show-level ratings (no season_id) and episode-level
    if not season_id:
        skipped_show_level += 1
        continue
    season_num = season_map.get(season_id)
    if season_num is None or season_num == 0:
        skipped_show_level += 1
        continue

    date = rev.get("dateAdded", "")[:10]
    rating = rev.get("rating")  # 1-10
    like = rev.get("like", False)
    name = show_cache.get(int(sid), f"Show {sid}")

    if sid not in output:
        output[sid] = {
            "name": name,
            "tmdb_id": int(sid),
            "seasons": {str(s_id): s_num for s_id, s_num in season_map.items()
                        if any(r2.get("seasonId") == s_id for r2 in all_reviews if str(r2.get("showId")) == sid)},
            "ratings": [],
        }

    output[sid]["ratings"].append({
        "r": rating / 2,  # convert 1-10 to 0.5-5.0 stars
        "date": date,
        "season_id": season_id,
        "sn": season_num,
        "like": like,
    })

# Save
with open("data/serializd.json", "w") as f:
    json.dump(output, f, separators=(',', ':'))

print(f"Serializd: saved {len(output)} shows, {sum(len(s['ratings']) for s in output.values())} season ratings (skipped {skipped_show_level} show-level)")
