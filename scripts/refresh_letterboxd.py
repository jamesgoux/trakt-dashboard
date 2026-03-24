#!/usr/bin/env python3
"""
Fetch Letterboxd diary data via RSS feed.
Extracts: personal ratings, rewatches, likes, TMDB IDs.
Matches to Trakt data via TMDB ID for dashboard integration.
Saves to data/letterboxd.json (merged incrementally).

Note: RSS only returns ~100 most recent entries.
For full history + tags, user can upload a CSV export.
"""

import os, json, requests, xml.etree.ElementTree as ET
from user_config import load_user_config, get_service
_ucfg = load_user_config()


USERNAME = get_service(_ucfg, "letterboxd", "username") or os.environ.get("LETTERBOXD_USERNAME", get_service(_ucfg, "trakt", "username") or os.environ.get("TRAKT_USERNAME", "jamesgoux"))
RSS_URL = f"https://letterboxd.com/{USERNAME}/rss/"

def refresh_letterboxd():
    # Load existing data
    lb = {}
    if os.path.exists("data/letterboxd.json"):
        with open("data/letterboxd.json") as f:
            lb = json.load(f)

    print(f"=== Letterboxd RSS Refresh ({USERNAME}) ===")
    print(f"  Existing entries: {len(lb)}")

    # Fetch RSS
    try:
        r = requests.get(RSS_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            print(f"  RSS fetch failed: {r.status_code}")
            return lb
    except Exception as e:
        print(f"  RSS fetch error: {e}")
        return lb

    # Parse
    ns = {"letterboxd": "https://letterboxd.com", "tmdb": "https://themoviedb.org"}
    root = ET.fromstring(r.text)
    items = root.findall(".//item")
    print(f"  RSS entries: {len(items)}")

    new_count = 0
    for item in items:
        title = item.findtext("letterboxd:filmTitle", "", ns)
        year = item.findtext("letterboxd:filmYear", "", ns)
        watched = item.findtext("letterboxd:watchedDate", "", ns)
        rating = item.findtext("letterboxd:memberRating", "", ns)
        rewatch = item.findtext("letterboxd:rewatch", "", ns) == "Yes"
        liked = item.findtext("letterboxd:memberLike", "", ns) == "Yes"
        tmdb_id = item.findtext("tmdb:movieId", "", ns)
        guid = item.findtext("guid", "")

        if not title or not watched:
            continue

        # Key: tmdb_id if available, else title+year
        key = f"tmdb:{tmdb_id}" if tmdb_id else f"{title}:{year}"

        # Merge: keep highest rating, track all watch dates
        if key in lb:
            entry = lb[key]
            if watched not in entry.get("dates", []):
                entry["dates"].append(watched)
                entry["watches"] = len(entry["dates"])
            # Update rating if newer
            if rating and (not entry.get("rating") or watched > max(entry["dates"][:-1], default="")):
                entry["rating"] = float(rating)
            if liked:
                entry["liked"] = True
        else:
            lb[key] = {
                "title": title,
                "year": int(year) if year else None,
                "tmdb_id": int(tmdb_id) if tmdb_id else None,
                "rating": float(rating) if rating else None,
                "liked": liked,
                "rewatch": rewatch,
                "dates": [watched],
                "watches": 1,
            }
            new_count += 1

    # Import ALL entries from CSV (full history + tags)
    if os.path.exists("data/letterboxd_tags.csv"):
        import csv
        csv_count = 0
        with open("data/letterboxd_tags.csv", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get("Name", "")
                year = row.get("Year", "")
                tags_str = row.get("Tags", "")
                rating = row.get("Rating", "")
                watched = row.get("Watched Date", "") or row.get("Date", "")
                rewatch = row.get("Rewatch", "").lower() == "yes"
                tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

                if not title: continue

                # Find or create entry by title+year
                key = f"{title}:{year}"
                found = False
                for k, entry in lb.items():
                    if entry["title"] == title and str(entry.get("year", "")) == str(year):
                        if tags: entry["tags"] = tags
                        if rating and not entry.get("rating"):
                            entry["rating"] = float(rating)
                        if watched and watched not in entry.get("dates", []):
                            entry.setdefault("dates", []).append(watched)
                            entry["watches"] = len(entry["dates"])
                        found = True; break

                if not found:
                    lb[key] = {
                        "title": title,
                        "year": int(year) if year else None,
                        "tmdb_id": None,
                        "rating": float(rating) if rating else None,
                        "liked": False,
                        "rewatch": rewatch,
                        "dates": [watched] if watched else [],
                        "watches": 1,
                        "tags": tags,
                    }
                    csv_count += 1

        print(f"  CSV import: +{csv_count} new entries from diary.csv")

    os.makedirs("data", exist_ok=True)
    with open("data/letterboxd.json", "w") as f:
        json.dump(lb, f, separators=(",", ":"))

    # Stats
    rated = [e for e in lb.values() if e.get("rating")]
    liked = [e for e in lb.values() if e.get("liked")]
    tagged = [e for e in lb.values() if e.get("tags")]

    print(f"  Total entries: {len(lb)} (+{new_count} new)")
    print(f"  Rated: {len(rated)}, Avg: {sum(e['rating'] for e in rated)/len(rated):.1f}★" if rated else "  No ratings")
    print(f"  Liked: {len(liked)}, Tagged: {len(tagged)}")

    return lb

if __name__ == "__main__":
    refresh_letterboxd()
