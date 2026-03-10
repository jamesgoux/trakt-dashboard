#!/usr/bin/env python3
"""
Import Letterboxd watched.csv and ratings.csv into letterboxd.json.
These are NOT diary entries — no watch dates. They represent:
- Movies confirmed watched (add to total count on all-time view)
- Personal ratings (add to ratings charts on all-time view)

Dedupes against existing letterboxd.json entries by title+year.
New entries get no dates (empty dates list) so they only show on all-time.
"""

import os, json, csv
from collections import defaultdict

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.path.exists("data/.lb_watched_imported"):
    print("Letterboxd watched/ratings already imported, skipping"); exit(0)

print("=== Importing Letterboxd Watched + Ratings ===")

# Load existing letterboxd data
lb = {}
if os.path.exists("data/letterboxd.json"):
    with open("data/letterboxd.json") as f:
        lb = json.load(f)

# Build lookup by title+year for dedup
existing_keys = set()
for k, v in lb.items():
    key = (v.get("title", "").lower(), str(v.get("year", "")))
    existing_keys.add(key)

print(f"  Existing entries: {len(lb)}, unique title+year: {len(existing_keys)}")

# Load ratings into a map
ratings_map = {}
if os.path.exists("data/ratings.csv"):
    with open("data/ratings.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("Name", "").lower(), row.get("Year", ""))
            rating = row.get("Rating", "")
            if rating:
                try:
                    ratings_map[key] = float(rating)
                except ValueError:
                    pass
    print(f"  Ratings loaded: {len(ratings_map)}")

# Import watched.csv
added = 0
updated_ratings = 0
if os.path.exists("data/watched.csv"):
    with open("data/watched.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            title = row.get("Name", "")
            year = row.get("Year", "")
            if not title:
                continue
            
            key = (title.lower(), year)
            lb_key = f"{title}:{year}"
            
            # Check if already exists
            found = False
            for k, v in lb.items():
                if v.get("title", "").lower() == title.lower() and str(v.get("year", "")) == year:
                    # Update rating if we have one and entry doesn't
                    if key in ratings_map and not v.get("rating"):
                        v["rating"] = ratings_map[key]
                        updated_ratings += 1
                    found = True
                    break
            
            if not found:
                rating = ratings_map.get(key)
                lb[lb_key] = {
                    "title": title,
                    "year": int(year) if year else None,
                    "tmdb_id": None,
                    "rating": rating,
                    "liked": False,
                    "rewatch": False,
                    "dates": [],  # no dates — undated watch
                    "watches": 1,
                    "undated": True,  # flag for special handling
                }
                added += 1

print(f"  Added: {added} new movies")
print(f"  Updated ratings: {updated_ratings}")
print(f"  Total entries: {len(lb)}")

# Save
with open("data/letterboxd.json", "w") as f:
    json.dump(lb, f, separators=(",", ":"))

# Mark as done
from datetime import datetime, timezone
with open("data/.lb_watched_imported", "w") as f:
    f.write(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))

print("Done!")
