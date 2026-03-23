#!/usr/bin/env python3
"""Fetch upcoming episode calendar from Trakt — episodes airing soon for watched shows."""
import os, sys, json, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import retry_request, get_trakt_access_token

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
USERNAME = os.environ.get("TRAKT_USERNAME")
ACCESS_TOKEN = get_trakt_access_token()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
BASE = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}
AUTH_HEADERS = {**HEADERS, "Authorization": f"Bearer {ACCESS_TOKEN}"} if ACCESS_TOKEN else HEADERS

DAYS_AHEAD = 90  # 3 months default
BATCH_SIZE = 33  # Trakt max days per calendar request

if not CLIENT_ID or not USERNAME:
    print("ERROR: Set TRAKT_CLIENT_ID and TRAKT_USERNAME"); sys.exit(1)
if not ACCESS_TOKEN:
    print("WARNING: TRAKT_ACCESS_TOKEN not set — /calendars/my requires OAuth"); sys.exit(1)


def fetch_calendar(start_date, days):
    """Fetch upcoming episodes from Trakt calendar API."""
    url = f"{BASE}/calendars/my/shows/{start_date}/{days}"
    r = retry_request("get", url, headers=AUTH_HEADERS, timeout=15)
    if not r or r.status_code != 200:
        print(f"  Calendar fetch failed for {start_date}+{days}d: {r.status_code if r else 'no response'}")
        return []
    return r.json()


def run():
    print("=== Upcoming Calendar ===")

    # Load existing poster cache
    posters = {}
    if os.path.exists("data/posters.json"):
        with open("data/posters.json") as f:
            posters = json.load(f)

    now = datetime.now(timezone.utc)
    start = now.strftime("%Y-%m-%d")

    # Fetch calendar in batches (Trakt caps at 33 days per request)
    all_episodes = []
    remaining = DAYS_AHEAD
    current_start = start

    while remaining > 0:
        batch = min(remaining, BATCH_SIZE)
        print(f"  Fetching {current_start} +{batch} days...")
        episodes = fetch_calendar(current_start, batch)
        all_episodes.extend(episodes)
        print(f"    → {len(episodes)} episodes")

        # Advance to next batch
        current_dt = datetime.strptime(current_start, "%Y-%m-%d") + timedelta(days=batch)
        current_start = current_dt.strftime("%Y-%m-%d")
        remaining -= batch
        time.sleep(0.5)

    print(f"  Total: {len(all_episodes)} episodes across {DAYS_AHEAD} days")

    # Group by date, then by show within each date
    by_date = defaultdict(lambda: defaultdict(list))

    for entry in all_episodes:
        show = entry.get("show", {})
        episode = entry.get("episode", {})
        first_aired = entry.get("first_aired", "") or episode.get("first_aired", "")

        if not first_aired:
            continue

        # Parse air date
        try:
            aired_dt = datetime.fromisoformat(first_aired.replace("Z", "+00:00"))
        except Exception:
            continue

        # Only include future or today
        date_str = aired_dt.strftime("%Y-%m-%d")

        slug = show.get("ids", {}).get("slug", "")
        if not slug:
            continue

        by_date[date_str][slug].append({
            "show": {
                "title": show.get("title", ""),
                "slug": slug,
                "trakt_id": show.get("ids", {}).get("trakt", ""),
                "tmdb_id": show.get("ids", {}).get("tmdb", ""),
                "year": show.get("year", ""),
            },
            "season": episode.get("season", 0),
            "number": episode.get("number", 0),
            "title": episode.get("title", ""),
            "aired": first_aired,
            "runtime": episode.get("runtime", 0),
        })

    # Build structured output: sorted dates with bundled shows
    days_list = []
    poster_misses = []

    for date_str in sorted(by_date.keys()):
        shows_on_day = []
        for slug, episodes in sorted(by_date[date_str].items(), key=lambda x: x[1][0]["show"]["title"].lower()):
            show_info = episodes[0]["show"]
            poster = posters.get(slug, "")

            if not poster and show_info.get("tmdb_id"):
                poster_misses.append((slug, show_info["tmdb_id"]))

            # Sort episodes by season/number
            eps = sorted(episodes, key=lambda e: (e["season"], e["number"]))
            ep_list = [{
                "s": e["season"],
                "e": e["number"],
                "t": e["title"],
                "aired": e["aired"],
                "rt": e["runtime"],
            } for e in eps]

            shows_on_day.append({
                "slug": slug,
                "title": show_info["title"],
                "trakt_id": show_info["trakt_id"],
                "tmdb_id": show_info["tmdb_id"],
                "year": show_info["year"],
                "poster": poster,
                "eps": ep_list,
            })

        if shows_on_day:
            days_list.append({
                "date": date_str,
                "shows": shows_on_day,
            })

    # Fetch missing posters from TMDB (budget: 50)
    posters_fetched = 0
    for slug, tmdb_id in poster_misses[:50]:
        if posters_fetched >= 50:
            break
        try:
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
            r = retry_request("get", url, timeout=5)
            if r and r.status_code == 200:
                d = r.json()
                pp = d.get("poster_path", "")
                if pp:
                    full_url = f"https://image.tmdb.org/t/p/w342{pp}"
                    posters[slug] = full_url
                    # Update the show entry in days_list
                    for day in days_list:
                        for show in day["shows"]:
                            if show["slug"] == slug:
                                show["poster"] = full_url
                    posters_fetched += 1
            time.sleep(0.15)
        except Exception:
            pass

    if posters_fetched:
        print(f"  Fetched {posters_fetched} new posters from TMDB")
        # Save updated poster cache
        with open("data/posters.json", "w") as f:
            json.dump(posters, f, separators=(',', ':'))

    # Count stats
    total_shows = len(set(slug for day in days_list for show in day["shows"] for slug in [show["slug"]]))
    total_eps = sum(len(show["eps"]) for day in days_list for show in day["shows"])

    output = {
        "fetched": now.isoformat(),
        "days_ahead": DAYS_AHEAD,
        "days": days_list,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/upcoming.json", "w") as f:
        json.dump(output, f, separators=(',', ':'))

    print(f"  Saved: {len(days_list)} days, {total_shows} shows, {total_eps} episodes")
    print(f"  Range: {days_list[0]['date'] if days_list else 'none'} → {days_list[-1]['date'] if days_list else 'none'}")


if __name__ == "__main__":
    run()
