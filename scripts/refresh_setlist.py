#!/usr/bin/env python3
"""
Fetch attended concerts from setlist.fm API.
Saves to data/setlist.json (merged incrementally).
"""

import os, json, time, requests

API_KEY = os.environ.get("SETLIST_FM_API_KEY")
USERNAME = os.environ.get("SETLIST_FM_USERNAME", os.environ.get("TRAKT_USERNAME", "jamesgoux"))
BASE = "https://api.setlist.fm/rest/1.0"

if not API_KEY:
    print("No SETLIST_FM_API_KEY set, skipping concert refresh"); exit(0)

HEADERS = {"Accept": "application/json", "x-api-key": API_KEY}

def fetch_attended():
    all_concerts = []
    page = 1
    while True:
        r = requests.get(f"{BASE}/user/{USERNAME}/attended?p={page}", headers=HEADERS, timeout=10)
        if r.status_code == 404:
            break
        if r.status_code != 200:
            print(f"  Error {r.status_code}"); break
        data = r.json()
        setlists = data.get("setlist", [])
        if not setlists:
            break
        all_concerts.extend(setlists)
        total = int(data.get("total", 0))
        print(f"  Page {page}: {len(all_concerts)}/{total}")
        if len(all_concerts) >= total:
            break
        page += 1
        time.sleep(0.5)
    return all_concerts

def normalize(concerts):
    entries = []
    for c in concerts:
        artist = c.get("artist", {}).get("name", "")
        venue = c.get("venue", {}).get("name", "")
        city_data = c.get("venue", {}).get("city", {})
        city = city_data.get("name", "")
        state = city_data.get("state", "")
        country = city_data.get("country", {}).get("name", "")
        coords = city_data.get("coords", {})
        date = c.get("eventDate", "")
        # Convert dd-MM-yyyy to yyyy-MM-dd
        if date and len(date) == 10 and date[2] == "-":
            date = f"{date[6:]}-{date[3:5]}-{date[0:2]}"
        tour = c.get("tour", {}).get("name", "") if c.get("tour") else ""
        songs = []
        for s in c.get("sets", {}).get("set", []):
            for song in s.get("song", []):
                songs.append(song.get("name", ""))
        entries.append({
            "id": c.get("id", ""),
            "artist": artist,
            "venue": venue,
            "city": city,
            "state": state,
            "country": country,
            "lat": coords.get("lat"),
            "lng": coords.get("long"),
            "date": date,
            "year": date[:4] if date else "",
            "tour": tour,
            "songs": songs,
            "song_count": len(songs),
        })
    return entries

print("=== Setlist.fm Concert Refresh ===")

# Load existing
existing = {}
if os.path.exists("data/setlist.json"):
    with open("data/setlist.json") as f:
        for c in json.load(f):
            existing[c["id"]] = c

print(f"  Existing: {len(existing)} concerts")

# Fetch
raw = fetch_attended()
print(f"  Fetched: {len(raw)} concerts from API")

# Normalize and merge
new_count = 0
for entry in normalize(raw):
    if entry["id"] not in existing:
        new_count += 1
    existing[entry["id"]] = entry

concerts = sorted(existing.values(), key=lambda x: x["date"], reverse=True)

os.makedirs("data", exist_ok=True)
with open("data/setlist.json", "w") as f:
    json.dump(concerts, f, separators=(",", ":"))

print(f"  Total: {len(concerts)} concerts (+{new_count} new)")

# Stats
from collections import Counter
artists = Counter(c["artist"] for c in concerts)
venues = Counter(c["venue"] for c in concerts)
years = Counter(c["year"] for c in concerts)
total_songs = sum(c["song_count"] for c in concerts)

print(f"  Artists: {len(artists)}, Venues: {len(venues)}, Songs heard: {total_songs}")
print(f"  Years: {dict(sorted(years.items()))}")
print("Done!")
