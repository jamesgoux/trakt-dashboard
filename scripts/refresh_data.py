#!/usr/bin/env python3
"""
Refresh Trakt watch history and rebuild the dashboard HTML.
Reads headshots from data/headshots.json and posters from data/posters.json.
Outputs index.html for GitHub Pages.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, time, requests
from collections import defaultdict, Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from utils import retry_request, get_trakt_access_token
from user_config import load_user_config, get_service, upload_user_data

# Load per-user config (Supabase â†’ env var fallback)
_ucfg = load_user_config()
_tz_name = _ucfg.get("_timezone", "America/Los_Angeles")
LOCAL_TZ = ZoneInfo(_tz_name)

def to_local(utc_str):
    """Convert UTC ISO timestamp to local timezone, preserving ISO format with tz info.
    Returns empty string for epoch dates (1970-01-01) which represent dateless watches."""
    if not utc_str:
        return ""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        # Epoch dates (1970-01-01) = dateless watches in Trakt, treat as no date
        if dt.year <= 1970:
            return ""
        return dt.astimezone(LOCAL_TZ).isoformat()
    except Exception:
        return utc_str

CLIENT_ID = get_service(_ucfg, "trakt", "client_id") or os.environ.get("TRAKT_CLIENT_ID")
USERNAME = _ucfg.get("_username") or os.environ.get("TRAKT_USERNAME")
BASE_URL = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2"}

def get_ratings(headers):
    ratings = {}
    url = f"{BASE_URL}/users/{USEP®AME}/ratings/movies"
    try:
        resp = retry_request(url, headers=headers)
        for item in resp.json():
            if item["type"] == "movie":
                ratings[item["movie"]["ids"]["trakt"]] = item["rating"]
    except Exception as e:
        print(f"Warning: could not fetch movie ratings: {e}")
    url = f"{BASE_URL}/users/{USERNAME}/ratings/shows"
    try:
        resp = retry_request(url, headers=headers)
        for item in resp.json():
            if item["type"] == "show":
                ratings[item["show"]["ids"]["trakt"]] = item["rating"]
    except Exception as e:
        print(f"Warning: could not fetch show ratings: {e}")
    return ratings

def get_letterboxd_ratings(lb_data):
    """Extract movie ratings from Letterboxd export data."""
    ratings = {}
    for film in lb_data.get("ratings", []):
        if film.get("Name") and film.get("Rating"):
            ratings[film["Name"]] = float(film["Rating"])
    return ratings

def process_letterboxd_watches(lb_data):
    """Process Letterboxd export data into watch history format."""
    watches = []
    lb_ratings = get_letterboxd_ratings(lb_data)
    for film in lb_data.get("watched", []):
        title = film.get("Name", "")
        watched_date = film.get("Watched Date", "")
        year = int(film.get("Year", 0)) if film.get("Year") else 0
        rating = lb_ratings.get(title)
        lb_id = film.get("Letterboxd URI, "").rsplit("/", 1)[-1] if film.get("Letterboxd URI") else ""
        watches.append({
            "title": title,
            "watched_at": watched_date,
            "year": film.get("Year"),
            "type": "movie",
            "rating": rating,
            "source": "letterboxd",
            "lb_id": lb_id,
        })
    return watches

def get_letterboxd_watches(lb_data, existing_trakt_ids):
    """Get Letterboxd watches not already in Trakt, preserving older lb-only entries from the existing history."""
    return process_letterboxd_watches(lb_data)

def process_serializd_watches(serializd_data):
    """Process Serializd export data into watch history format."""
    watches = []
    for season in serializd_data.get("seasons", []):
        title = season.get("showTitle") or season.get("title", "")
        watched_date = season.get("watchedDate", "") or season.get("lastWatchedDate", "")
        if watched_date:
            watched_date = watched_date[:10]
        year = season.get("year") or season.get("seasonYear")
        rating = season.get("rating")
        if isinstance(rating, str):
            try: rating = float(rating)
            except: rating = None
        watches.append({
            "title": title,
            "watched_at": watched_date,
            "year": year,
            "type": "show",
            "rating": rating,
            "source": "serializd",
        })
    return watches

def get_serializd_watches(serializd_data):
    return process_serializd_watches(serializd_data)

def get_watch_history(headers, limit=None, start_date=None, end_date=None):
    """Fetch watch history from Trakt API."""
    watches = []
    page = 1
    while True:
        params = {"page": page, "limit": 1000}
        if start_date:
            params["start_at"] = start_date
        if end_date:
            params["end_at"] = end_date
        url = f"{BASE_URL}/users/{USERNAME}/history"
        resp = retry_request(url, headers=headers, params=params)
        data = resp.json()
        if not data:
            break
        watches.extend(data)
        if limit and len(watches) >= limit:
            break
        page += 1
    return watches

def get_movie_details(trakt_id, headers):
    """Get movie details including year from Trakt."""
    url = f"{BASE_URL}/movies/{trakt_id}"
    resp = retry_request(url, headers=headers)
    return resp.json() if resp else {}

def process_watches(raw_watches, ratings, headers):
    """Process raw watch history from Trakt into unified format."""
    watches = []
    for item in raw_watches:
        watched_at = to_local(item.get("watched_at"))
        media_type = item.get("type")
        if media_type == "movie":
            movie = item.get("movie", {})
            trakt_id = movie.get("ids", {}).get("trakt")
            watches.append({
                "title": movie.get("title"),
                "watched_at": watched_at,
                "year": movie.get("year"),
                "type": "movie",
                "rating": ratings.get(trakt_id),
                "source": "trakt",
            })
        elif media_type == "episode":
            show = item.get("show", {})
            episode = item.get("episode", {})
            trakt_id = show.get("ids", {}).get("trakt")
            watches.append({
                "title": show.get("title"),
                "watched_at": watched_at,
                "year": show.get("year"),
                "type": "episode",
                "rating": ratings.get(trakt_id),
                "source": "trakt",
            })
    return watches

def build_stats(lb_watches, trakt_watches, serializd_watches):
    """Build statistics from all watch sources."""
    all_watches = lb_watches + trakt_watches + serializd_watches
    total = len(all_watches)
    movies = sum(1 for w in all_watches if w.get("type") == "movie")
    episodes = sum(1 for w in all_watches if w.get("type") == "episode")
    return {"total": total, "movies": movies, "episodes": episodes}

def main():
    ucfg = load_user_config()
    access_token = get_trakt_access_token(ucfg)
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": CLIENT_ID,
        "Authorization": f"Bearer {access_token}",
    }
    print("Fetching ratings...")
    ratings = get_ratings(headers)
    print(f"Fetched {len(ratings)} ratings")
    print("Fetching watch history...")
    raw_watches = get_watch_history(headers)
    trakt_watches = process_watches(raw_watches, ratings, headers)
    print(f"Fetched {len(trakt_watches)} Trakt watches")
    lb_data = ucfg.get("letterboxd", {})
    lb_watches = get_letterboxd_watches(lb_data, set())
    print(f"Processed {len(lb_watches)} Letterboxd watches")
    serializd_data = ucfg.get("serializd", {})
    serializd_watches = get_serializd_watches(serializd_data)
    print(f"Processed {len(serializd_watches)} Serializd watches")
    stats = build_stats(lb_watches, trakt_watches, serializd_watches)
    print(f"Stats: {stats}")
    print("Uploading data...")
    try:
        upload_user_data(ucfg, {
            "trakt_watches": trakt_watches,
            "lb_watches": lb_watches,
            "serializd_watches": serializd_watches,
            "stats": stats,
        })
    except Exception as e:
        print(f"  Supabase not configured, skipping upload")

print("Done!")
