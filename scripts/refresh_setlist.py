#!/usr/bin/env python3
"""
Fetch attended concerts from setlist.fm API.
Saves to data/setlist.json (merged incrementally).
"""

import os, json, time, requests

API_KEY = get_service(_ucfg, "setlistfm", "api_key") or os.environ.get("SETLIST_FM_API_KEY")
USERNAME = get_service(_ucfg, "setlistfm", "username") or os.environ.get("SETLIST_FM_USERNAME", get_service(_ucfg, "trakt", "username") or os.environ.get("TRAKT_USERNAME", "jamesgoux"))
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

def lookup_albums(concerts):
    """Use MusicBrainz to find album for each song. Cached in data/song_albums.json."""
    MB_HEADERS = {"User-Agent": "Iris/1.0 (github.com/jamesgoux/iris-stats)", "Accept": "application/json"}
    cache = {}
    if os.path.exists("data/song_albums.json"):
        with open("data/song_albums.json") as f:
            cache = json.load(f)

    need = []
    for c in concerts:
        artist = c["artist"]
        for song in c.get("songs", []):
            key = f"{artist}||{song}"
            if song and key not in cache:
                need.append((artist, song, key))

    if not need:
        print(f"  Albums: all {len(cache)} cached")
        return cache

    print(f"  Albums: {len(cache)} cached, {len(need)} to look up")
    count = 0
    for i, (artist, song, key) in enumerate(need[:100]):  # cap at 100 per run
        try:
            r = requests.get("https://musicbrainz.org/ws/2/recording",
                params={"query": f'recording:"{song}" AND artist:"{artist}"', "fmt": "json", "limit": 5},
                headers=MB_HEADERS, timeout=10)
            if r.status_code == 200:
                best_album = None
                for rec in r.json().get("recordings", []):
                    if rec.get("score", 0) < 80:
                        continue
                    for rel in rec.get("releases", []):
                        rg = rel.get("release-group", {})
                        if rg.get("primary-type") == "Album" and not rg.get("secondary-types"):
                            best_album = rel.get("title", "")
                            break
                    if best_album:
                        break
                cache[key] = best_album or "Unknown"
                if best_album:
                    count += 1
            elif r.status_code == 503:
                time.sleep(2)
        except Exception:
            pass
        if (i + 1) % 20 == 0:
            print(f"    {i+1}/{min(len(need),100)}, {count} found")
            os.makedirs("data", exist_ok=True)
            with open("data/song_albums.json", "w") as f:
                json.dump(cache, f, separators=(",", ":"))
        time.sleep(1.1)  # MusicBrainz rate limit: 1 req/sec

    os.makedirs("data", exist_ok=True)
    with open("data/song_albums.json", "w") as f:
        json.dump(cache, f, separators=(",", ":"))
    print(f"  +{count} albums found, {len(cache)} total")
    return cache

def search_setlist(artist, date):
    """Search setlist.fm for a specific artist+date to find songs."""
    try:
        # date is YYYY-MM-DD, API wants dd-MM-yyyy
        api_date = f"{date[8:10]}-{date[5:7]}-{date[0:4]}"
        r = requests.get(f"{BASE}/search/setlists",
            params={"artistName": artist, "date": api_date},
            headers=HEADERS, timeout=10)
        if r.status_code == 200:
            setlists = r.json().get("setlist", [])
            for s in setlists:
                songs = []
                for st in s.get("sets", {}).get("set", []):
                    for song in st.get("song", []):
                        if song.get("name"):
                            songs.append(song["name"])
                if songs:
                    return songs
    except Exception:
        pass
    return []

print("=== Setlist.fm Concert Refresh ===")

# Load existing — use date|artist as key for Concert Archives entries
existing_by_id = {}
existing_by_key = {}
if os.path.exists("data/setlist.json"):
    with open("data/setlist.json") as f:
        for c in json.load(f):
            if c.get("id"):
                existing_by_id[c["id"]] = c
            key = c["date"] + "|" + c["artist"]
            existing_by_key[key] = c

print(f"  Existing: {len(existing_by_key)} entries")

# Fetch attended from setlist.fm
raw = fetch_attended()
print(f"  Fetched: {len(raw)} concerts from API")

# Normalize and merge — setlist.fm always wins over Concert Archives
new_count = 0
for entry in normalize(raw):
    key = entry["date"] + "|" + entry["artist"]
    if key not in existing_by_key or entry.get("song_count", 0) > existing_by_key.get(key, {}).get("song_count", 0):
        if key not in existing_by_key:
            new_count += 1
        existing_by_key[key] = entry

# Try to find songs for Concert Archives entries that have no songs (budget: 50 per run)
no_songs = [(k, c) for k, c in existing_by_key.items() if c.get("song_count", 0) == 0 and not c.get("_searched")]
print(f"  Searching setlist.fm for songs on {min(len(no_songs), 50)} of {len(no_songs)} events without songs...")
found = 0
for i, (key, c) in enumerate(no_songs[:50]):
    songs = search_setlist(c["artist"], c["date"])
    if songs:
        c["songs"] = songs
        c["song_count"] = len(songs)
        found += 1
    c["_searched"] = True
    time.sleep(0.5)
    if (i + 1) % 10 == 0:
        print(f"    {i+1}/{min(len(no_songs),50)}, found songs for {found}")
print(f"  Found songs for {found} events")

concerts = sorted(existing_by_key.values(), key=lambda x: x["date"], reverse=True)
# Clean internal flags before saving
for c in concerts:
    c.pop("_searched", None)

# Look up albums for songs
album_cache = lookup_albums(concerts)

# Add album info to concert songs
for c in concerts:
    c["song_albums"] = {}
    for song in c.get("songs", []):
        key = f"{c['artist']}||{song}"
        album = album_cache.get(key)
        if album and album != "Unknown":
            c["song_albums"][song] = album

os.makedirs("data", exist_ok=True)
with open("data/setlist.json", "w") as f:
    json.dump(concerts, f, separators=(",", ":"))

print(f"  Total: {len(concerts)} concerts (+{new_count} new)")

# Stats
from collections import Counter
from user_config import load_user_config, get_service
_ucfg = load_user_config()

artists = Counter(c["artist"] for c in concerts)
venues = Counter(c["venue"] for c in concerts)
years = Counter(c["year"] for c in concerts)
total_songs = sum(c["song_count"] for c in concerts)

print(f"  Artists: {len(artists)}, Venues: {len(venues)}, Songs heard: {total_songs}")
print(f"  Years: {dict(sorted(years.items()))}")
print("Done!")
