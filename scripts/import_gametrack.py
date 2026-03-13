#!/usr/bin/env python3
"""
Import GameTrack export data into Iris.

Usage: python scripts/import_gametrack.py <export_directory>
  Where <export_directory> contains games.csv, playthroughs.csv,
  playstation_games.csv, steam_achievements.csv, genres.csv, manifest.json

Output: data/gametrack.json
"""

import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime

# game_state mapping (from GameTrack internals)
GAME_STATE = {
    "1": "playing",
    "2": "play_later",
    "3": "collection",
    "4": "finished",
    "5": "abandoned",
    "6": "wanted",
}

# completion_state mapping
COMPLETION_STATE = {
    "0": None,
    "1": "story",       # Completed story
    "3": "completionist",  # 100% completion
}


def parse_date(d):
    """Extract YYYY-MM-DD from ISO datetime string."""
    if not d:
        return ""
    return d[:10]


def parse_year(d):
    """Extract year from date string."""
    if not d or len(d) < 4:
        return ""
    return d[:4]


def safe_float(v, default=0.0):
    try:
        return float(v) if v else default
    except (ValueError, TypeError):
        return default


def main():
    if len(sys.argv) < 2:
        print("Usage: python import_gametrack.py <export_directory>")
        print("  e.g. python import_gametrack.py /uploads")
        sys.exit(1)

    export_dir = sys.argv[1]
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")

    print("=== GameTrack Import ===")
    print(f"Source: {export_dir}")

    # --- Load manifest ---
    manifest_file = os.path.join(export_dir, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_file):
        with open(manifest_file) as f:
            manifest = json.load(f)
        print(f"Export date: {manifest.get('exportDate', '?')}")
        print(f"App version: {manifest.get('appVersion', '?')}")
        counts = manifest.get("counts", {})
        print(f"Counts: {counts.get('games', 0)} games, {counts.get('steamGames', 0)} Steam, "
              f"{counts.get('playStationGames', 0)} PS, {counts.get('xboxGames', 0)} Xbox")

    # --- Load games.csv ---
    games_file = os.path.join(export_dir, "games.csv")
    if not os.path.exists(games_file):
        print(f"ERROR: {games_file} not found")
        sys.exit(1)

    with open(games_file, encoding="utf-8") as f:
        games_raw = list(csv.DictReader(f))
    print(f"\nLoaded {len(games_raw)} games from games.csv")

    # --- Load playthroughs ---
    playthroughs = {}  # game_uuid -> list of playthroughs
    pt_file = os.path.join(export_dir, "playthroughs.csv")
    if os.path.exists(pt_file):
        with open(pt_file, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gid = row.get("game_uuid", "")
                if gid:
                    playthroughs.setdefault(gid, []).append(row)
        print(f"Loaded {sum(len(v) for v in playthroughs.values())} playthroughs")

    # --- Load PSN data ---
    psn_by_uuid = {}
    psn_file = os.path.join(export_dir, "playstation_games.csv")
    if os.path.exists(psn_file):
        with open(psn_file, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gid = row.get("game_uuid", "")
                if gid:
                    psn_by_uuid[gid] = row
        print(f"Loaded {len(psn_by_uuid)} PlayStation games")

    # --- Load genres ---
    genre_map = {}
    genre_file = os.path.join(export_dir, "genres.csv")
    if os.path.exists(genre_file):
        with open(genre_file, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                genre_map[row["id"]] = row["name"]
        print(f"Loaded {len(genre_map)} genres")

    # --- Process games ---
    games = []
    total_hours = 0
    platform_counts = Counter()
    status_counts = Counter()
    genre_counts = Counter()
    yearly_counts = Counter()
    by_year = {}  # year -> {games: N, hours: N, finished: N}

    for g in games_raw:
        uuid = g.get("uuid", "")
        state = GAME_STATE.get(g.get("game_state", ""), "collection")
        completion = COMPLETION_STATE.get(g.get("completion_state", ""), None)

        # Merge playtime: games.csv hours → PSN play_duration as fallback
        hours = safe_float(g.get("hours_played"))
        additional = safe_float(g.get("additional_playtime"))
        if hours == 0 and uuid in psn_by_uuid:
            psn_hours = safe_float(psn_by_uuid[uuid].get("play_duration"))
            if psn_hours > 0:
                hours = psn_hours

        # PSN extras
        psn = psn_by_uuid.get(uuid, {})
        trophy_progress = int(psn.get("progress", 0) or 0)
        play_count = int(psn.get("play_count", 0) or 0)
        trophy_name = psn.get("trophy_title_name", "")

        # Playthrough data
        pts = playthroughs.get(uuid, [])
        # Find best finish date: from game or from playthroughs
        finish_date = parse_date(g.get("finish_date"))
        start_date = parse_date(g.get("start_date"))
        if not finish_date:
            for pt in pts:
                fd = parse_date(pt.get("date_finished"))
                if fd:
                    finish_date = fd
                    break
        if not start_date:
            for pt in pts:
                sd = parse_date(pt.get("date_started"))
                if sd:
                    start_date = sd
                    break

        # Genres
        genres_raw = g.get("genres", "")
        genres = [gn.strip() for gn in genres_raw.split("|") if gn.strip()] if genres_raw else []

        # Platform
        platform = g.get("owned_platform", "")

        # Determine year (finish year > start year > added year)
        year = parse_year(finish_date) or parse_year(start_date) or parse_year(g.get("added_date", ""))

        game = {
            "id": uuid,
            "title": g.get("title", ""),
            "developer": g.get("developer", ""),
            "publisher": g.get("publisher", ""),
            "poster": g.get("poster_url", ""),
            "banner": g.get("banner_url", ""),
            "platform": platform,
            "platforms_available": g.get("platforms", ""),
            "state": state,
            "completion": completion,
            "user_rating": safe_float(g.get("user_rating")),
            "critic_rating": safe_float(g.get("critic_rating")),
            "hours": round(hours + additional, 1),
            "start_date": start_date,
            "finish_date": finish_date,
            "added_date": parse_date(g.get("added_date")),
            "release_date": parse_date(g.get("release_date")),
            "release_year": g.get("release_year", ""),
            "genres": genres,
            "ttb_story": safe_float(g.get("time_to_beat_story")),
            "ttb_extras": safe_float(g.get("time_to_beat_extras")),
            "ttb_complete": safe_float(g.get("time_to_beat_complete")),
            "trophy_progress": trophy_progress,
            "play_count": play_count,
            "notes": g.get("notes", ""),
            "yr": year,
        }
        games.append(game)

        # Aggregates
        total_hours += game["hours"]
        if platform:
            platform_counts[platform] += 1
        status_counts[state] += 1
        for genre in genres:
            genre_counts[genre] += 1
        if year:
            yearly_counts[year] += 1
            if year not in by_year:
                by_year[year] = {"games": 0, "hours": 0, "finished": 0}
            by_year[year]["games"] += 1
            by_year[year]["hours"] += game["hours"]
            if state == "finished":
                by_year[year]["finished"] += 1

    # Sort games: finished/playing first (by date desc), then collection
    state_order = {"playing": 0, "finished": 1, "abandoned": 2, "play_later": 3, "collection": 4, "wanted": 5}
    def sort_key(g):
        date = g.get("finish_date") or g.get("start_date") or g.get("added_date") or "0000"
        return (state_order.get(g["state"], 9), date == "0000", date, -g["hours"])
    games.sort(key=sort_key)

    # Build aggregates
    finished = [g for g in games if g["state"] == "finished"]
    playing = [g for g in games if g["state"] == "playing"]
    rated = [g for g in games if g["user_rating"] > 0]
    with_hours = [g for g in games if g["hours"] > 0]

    # Top games by playtime
    top_by_hours = sorted(with_hours, key=lambda g: -g["hours"])[:30]

    # Platform breakdown
    platforms = [{"name": p, "count": c} for p, c in platform_counts.most_common()]

    # Status breakdown
    statuses = [{"name": s, "count": c} for s, c in status_counts.most_common()]

    # Genre breakdown
    genres_agg = [{"name": gn, "count": c} for gn, c in genre_counts.most_common(20)]

    # Rating distribution
    rating_dist = Counter()
    for g in rated:
        rating_dist[int(g["user_rating"])] += 1

    output = {
        "total": len(games),
        "total_hours": round(total_hours, 1),
        "total_finished": len(finished),
        "total_playing": len(playing),
        "total_rated": len(rated),
        "total_platforms": len(platform_counts),
        "all": games,
        "top_by_hours": [{"title": g["title"], "hours": g["hours"], "platform": g["platform"],
                          "poster": g["poster"], "state": g["state"]} for g in top_by_hours],
        "platforms": platforms,
        "statuses": statuses,
        "genres": genres_agg,
        "rating_dist": [{"rating": r, "count": c} for r, c in sorted(rating_dist.items())],
        "by_year": {y: v for y, v in sorted(by_year.items())},
        "export_date": manifest.get("exportDate", ""),
    }

    # Write output
    out_file = os.path.join(data_dir, "gametrack.json")
    with open(out_file, "w") as f:
        json.dump(output, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(out_file) / 1024
    print(f"\n=== Results ===")
    print(f"  Games: {len(games)} ({len(finished)} finished, {len(playing)} playing)")
    print(f"  Hours: {total_hours:.0f}")
    print(f"  Platforms: {', '.join(f'{p}({c})' for p, c in platform_counts.most_common())}")
    print(f"  Rated: {len(rated)}")
    print(f"  Output: {out_file} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
