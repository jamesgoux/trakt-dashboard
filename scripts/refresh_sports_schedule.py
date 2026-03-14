#!/usr/bin/env python3
"""
Refresh sports schedule cache for tracked teams.
Fetches game schedules from TheSportsDB for NBA, NFL, MLB, NHL.

Strategy per league:
  NFL: Round-based (rounds 1-18 + playoff rounds) — complete schedules
  NHL: Round-based (rounds 1-29 + playoff rounds) — complete schedules
  MLB: Round-based (rounds 1-50 + playoff rounds) — complete schedules
  NBA: Search-based (home games) + opponent backfill (away games)

Output: data/sports_schedule.json
  { "teams": {...}, "events": { "Team Name": [...events...] }, "updated": "ISO" }
"""

import json
import os
import sys
import time
from datetime import datetime

# Add scripts dir to path for utils
sys.path.insert(0, os.path.dirname(__file__))
from utils import retry_request

API_BASE = "https://www.thesportsdb.com/api/v1/json/3"
REQUEST_DELAY = 2.0  # seconds between API calls (free tier rate limit)

# League configurations
LEAGUES = {
    "NFL": {
        "id": "4391",
        "method": "rounds",
        "regular_rounds": list(range(1, 19)),  # weeks 1-18
        "playoff_rounds": [125, 150, 160, 175, 200, 500],
        "season_format": "single",  # "2024"
    },
    "NHL": {
        "id": "4380",
        "method": "rounds",
        "regular_rounds": list(range(1, 30)),  # rounds 1-29
        "playoff_rounds": [125, 150, 175, 200, 500],
        "season_format": "split",  # "2024-2025"
    },
    "MLB": {
        "id": "4424",
        "method": "rounds",
        "regular_rounds": list(range(1, 51)),  # rounds 1-50 (weeks/series)
        "playoff_rounds": [125, 150, 175, 200, 500],
        "season_format": "single",  # "2025"
    },
    "NBA": {
        "id": "4387",
        "method": "search",  # no round data available
        "season_format": "split",  # "2024-2025"
    },
}

# How many seasons back to fetch
SEASONS_BACK = 5


def get_seasons(league_key, seasons_back=SEASONS_BACK):
    """Generate season strings for a league."""
    cfg = LEAGUES[league_key]
    current_year = datetime.now().year
    seasons = []
    for i in range(seasons_back):
        y = current_year - i
        if cfg["season_format"] == "split":
            seasons.append(f"{y}-{y+1}")
            seasons.append(f"{y-1}-{y}")
        else:
            seasons.append(str(y))
            seasons.append(str(y - 1))
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in seasons:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def api_get(endpoint, params=None):
    """Make a rate-limited API request."""
    time.sleep(REQUEST_DELAY)
    url = f"{API_BASE}/{endpoint}"
    try:
        resp = retry_request("get", url, params=params, timeout=15)
        if resp and resp.status_code == 200:
            return resp.json()
        elif resp and resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            print(f"  Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after + 2)
            resp = retry_request("get", url, params=params, timeout=15)
            if resp and resp.status_code == 200:
                return resp.json()
        return None
    except Exception as e:
        print(f"  API error: {e}")
        return None


def normalize_event(ev, my_team):
    """Normalize a TheSportsDB event to our cache format."""
    return {
        "id": ev.get("idEvent", ""),
        "date": ev.get("dateEvent", ""),
        "time": ev.get("strTime", ""),
        "sport": ev.get("strSport", ""),
        "league": ev.get("strLeague", ""),
        "round": ev.get("intRound", ""),
        "home_team": ev.get("strHomeTeam", ""),
        "away_team": ev.get("strAwayTeam", ""),
        "home_score": ev.get("intHomeScore"),
        "away_score": ev.get("intAwayScore"),
        "venue": ev.get("strVenue", ""),
        "home_badge": ev.get("strHomeTeamBadge", ""),
        "away_badge": ev.get("strAwayTeamBadge", ""),
        "season": ev.get("strSeason", ""),
        "status": ev.get("strStatus", ""),
    }


def fetch_round_events(league_id, round_num, season):
    """Fetch all events for a specific round."""
    data = api_get("eventsround.php", {"id": league_id, "r": round_num, "s": season})
    if data:
        return data.get("events") or []
    return []


def fetch_search_events(team_name, season):
    """Fetch events via search (25 home games max)."""
    data = api_get("searchevents.php", {"e": team_name, "s": season})
    if data:
        return data.get("event") or []
    return []


def fetch_rounds_for_league(league_key, team_names, seasons, existing_events=None):
    """Fetch games for tracked teams via round-based approach.
    For seasons with existing cached data, only fetch recent rounds."""
    cfg = LEAGUES[league_key]
    league_id = cfg["id"]
    regular_rounds = cfg["regular_rounds"]
    playoff_rounds = cfg["playoff_rounds"]

    events_by_team = {name: {} for name in team_names}  # name -> {event_id: event}
    team_set = set(team_names)

    for season in seasons:
        season_count = 0
        empty_streak = 0

        # If we have cached data for this season, find the highest round and
        # only fetch from there (+ playoffs). Saves ~80% of API calls.
        max_cached_round = 0
        if existing_events:
            for name in team_names:
                for ev in existing_events.get(name, []):
                    if ev.get("season", "") == season:
                        r = int(ev.get("round", 0) or 0)
                        if r > max_cached_round and r < 100:
                            max_cached_round = r

        if max_cached_round > 0:
            # Only fetch from max_cached_round-1 onward (overlap by 1 for score updates)
            start_round = max(1, max_cached_round - 1)
            rounds_to_fetch = [r for r in regular_rounds if r >= start_round] + playoff_rounds
            print(f"    {league_key} {season}: cached through round {max_cached_round}, fetching from {start_round}")
        else:
            rounds_to_fetch = regular_rounds + playoff_rounds

        for round_num in rounds_to_fetch:
            raw_events = fetch_round_events(league_id, round_num, season)

            if not raw_events:
                empty_streak += 1
                if round_num in regular_rounds and empty_streak >= 5:
                    print(f"    Stopping {league_key} {season} at round {round_num} (5 empty)")
                    break
                continue

            empty_streak = 0

            for ev in raw_events:
                home = ev.get("strHomeTeam", "")
                away = ev.get("strAwayTeam", "")
                event_id = ev.get("idEvent", "")

                for team_name in team_set:
                    if team_name in home or team_name in away:
                        if event_id not in events_by_team[team_name]:
                            events_by_team[team_name][event_id] = normalize_event(ev, team_name)
                            season_count += 1

        print(f"    {league_key} {season}: {season_count} new games for tracked teams")

    return events_by_team


def fetch_search_for_team(team_name, seasons):
    """Fetch games via search-based approach (for NBA)."""
    events = {}  # event_id -> event
    opponents = set()

    # Step 1: Get home games
    for season in seasons:
        raw = fetch_search_events(team_name, season)
        for ev in raw:
            event_id = ev.get("idEvent", "")
            if event_id not in events:
                events[event_id] = normalize_event(ev, team_name)
                # Track opponents for away game search
                home = ev.get("strHomeTeam", "")
                away = ev.get("strAwayTeam", "")
                if home == team_name and away:
                    opponents.add(away)
                elif away == team_name and home:
                    opponents.add(home)
        print(f"    Search {team_name} {season}: {len(raw)} home games, {len(opponents)} opponents so far")

    # Step 2: Search opponents to find away games
    print(f"    Backfilling away games from {len(opponents)} opponents...")
    for opp in sorted(opponents):
        for season in seasons:
            raw = fetch_search_events(opp, season)
            for ev in raw:
                event_id = ev.get("idEvent", "")
                home = ev.get("strHomeTeam", "")
                away = ev.get("strAwayTeam", "")
                if event_id not in events and (team_name in home or team_name in away):
                    events[event_id] = normalize_event(ev, team_name)

    print(f"    Total for {team_name}: {len(events)} games (home + away)")
    return events


def load_teams():
    """Load tracked teams from sports_teams.json + sports.json."""
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")

    # Load explicit tracked teams
    teams_file = os.path.join(data_dir, "sports_teams.json")
    if os.path.exists(teams_file):
        with open(teams_file) as f:
            teams = json.load(f)
    else:
        teams = []

    tracked_names = {t["name"] for t in teams}

    # Add teams from sports.json (user's logged events)
    sports_file = os.path.join(data_dir, "sports.json")
    if os.path.exists(sports_file):
        with open(sports_file) as f:
            events = json.load(f)
        for ev in events:
            my_team = ev.get("my_team", "")
            if my_team and my_team not in tracked_names:
                # Look up team info
                league = ev.get("league", "")
                sport = ev.get("sport", "")
                league_id = ""
                team_id = ""
                for lk, lv in LEAGUES.items():
                    if lk == league:
                        league_id = lv["id"]
                        break
                teams.append({
                    "name": my_team,
                    "league": league,
                    "league_id": league_id,
                    "team_id": team_id,
                    "sport": sport,
                    "source": "logged_event",
                })
                tracked_names.add(my_team)
                print(f"  Added {my_team} from logged events")

    return teams


def resolve_team_ids(teams):
    """Look up TheSportsDB team IDs for any teams missing them."""
    for team in teams:
        if not team.get("team_id"):
            print(f"  Looking up team ID for {team['name']}...")
            data = api_get("searchteams.php", {"t": team["name"]})
            if data and data.get("teams"):
                match = None
                for t in data["teams"]:
                    if t["strTeam"] == team["name"]:
                        match = t
                        break
                if not match:
                    match = data["teams"][0]
                team["team_id"] = match["idTeam"]
                team["league_id"] = match.get("idLeague", team.get("league_id", ""))
                team["sport"] = match.get("strSport", team.get("sport", ""))
                # Map league name to our key
                league_name = match.get("strLeague", "")
                for lk in LEAGUES:
                    if lk in league_name or league_name.startswith(lk):
                        team["league"] = lk
                        team["league_id"] = LEAGUES[lk]["id"]
                        break
                print(f"    Found: ID={team['team_id']}, League={team['league']}")
    return teams


def main():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")

    print("=== Sports Schedule Pre-Cache ===")
    print(f"Time: {datetime.now().isoformat()}")

    # Load and resolve teams
    teams = load_teams()
    teams = resolve_team_ids(teams)
    print(f"\nTracked teams ({len(teams)}):")
    for t in teams:
        print(f"  {t['name']} ({t['league']}) — ID: {t.get('team_id', '?')}")

    # Group teams by league
    teams_by_league = {}
    for t in teams:
        league = t.get("league", "")
        if league in LEAGUES:
            teams_by_league.setdefault(league, []).append(t["name"])

    # Load existing cache for merging
    cache_file = os.path.join(data_dir, "sports_schedule.json")
    existing = {}
    existing_seasons = set()  # track which seasons we already have data for
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            old = json.load(f)
            existing = old.get("events", {})
            # Build set of seasons that have cached data
            for team_events in existing.values():
                for ev in team_events:
                    s = ev.get("season", "")
                    if s:
                        existing_seasons.add(s)

    all_events = {}  # team_name -> {event_id: event}

    # Determine current seasons (scores still updating) vs past (final)
    current_year = datetime.now().year
    current_month = datetime.now().month
    # Current seasons by league (the season that's actively being played)
    def is_current_season(season_str, league_key):
        """Check if a season is the ACTIVE season (not last year's)."""
        cfg = LEAGUES[league_key]
        if cfg["season_format"] == "split":
            # e.g. "2025-2026" is current only if end year >= current year
            parts = season_str.split("-")
            if len(parts) == 2:
                return int(parts[1]) >= current_year
        else:
            # e.g. "2026" is current only if it's this year
            try:
                return int(season_str) >= current_year
            except ValueError:
                return True
        return False

    # Quick check: use eventslast to see which teams have new games
    # This costs only 1 API call per team instead of 50+ round calls
    existing_ids = set()
    for team_events in existing.values():
        for ev in team_events:
            existing_ids.add(ev.get("id", ""))

    teams_needing_update = set()
    teams_with_ids = {t["name"]: t.get("team_id", "") for t in teams if t.get("team_id")}
    if existing_ids:  # only check if we have existing cache
        print("\nQuick check for new games (eventslast)...")
        for name, tid in teams_with_ids.items():
            if not tid:
                teams_needing_update.add(name)
                continue
            data = api_get("eventslast.php", {"id": tid})
            if data and data.get("results"):
                for ev in data["results"]:
                    eid = ev.get("idEvent", "")
                    if eid and eid not in existing_ids:
                        teams_needing_update.add(name)
                        print(f"  {name}: new game found ({ev.get('strEvent', '')} {ev.get('dateEvent', '')})")
                        break
                    # Also check if score was updated (was None, now has score)
                    if eid in existing_ids and ev.get("intHomeScore") not in (None, "", "None"):
                        # Check if our cached version has the score
                        for team_evts in existing.values():
                            for cached_ev in team_evts:
                                if cached_ev.get("id") == eid and cached_ev.get("home_score") in (None, "", "None"):
                                    teams_needing_update.add(name)
                                    print(f"  {name}: score updated ({ev.get('strEvent', '')})")
                                    break
        if not teams_needing_update:
            print("  No new games found — skipping all round fetches")

    # Fetch by league
    for league_key, team_names in teams_by_league.items():
        cfg = LEAGUES[league_key]
        all_seasons = get_seasons(league_key)

        # Split into current (always fetch) and past (skip if cached)
        fetch_seasons = []
        skip_seasons = []
        for s in all_seasons:
            if is_current_season(s, league_key) or s not in existing_seasons:
                fetch_seasons.append(s)
            else:
                skip_seasons.append(s)

        # If no teams in this league need updates, skip entirely
        league_teams_need_update = [n for n in team_names if n in teams_needing_update]
        if existing_ids and not league_teams_need_update and not [s for s in fetch_seasons if s not in existing_seasons]:
            print(f"\n--- {league_key}: no updates needed, skipping ---")
            continue

        print(f"\n--- {league_key} ({len(team_names)} teams) ---")
        print(f"  Teams: {', '.join(team_names)}")
        print(f"  Fetching: {', '.join(fetch_seasons[:6]) if fetch_seasons else 'none'}")
        if skip_seasons:
            print(f"  Cached (skipping): {', '.join(skip_seasons[:6])}")

        if not fetch_seasons:
            print(f"  All seasons cached, skipping")
            continue

        if cfg["method"] == "rounds":
            league_events = fetch_rounds_for_league(league_key, team_names, fetch_seasons, existing)
            for name, evts in league_events.items():
                all_events.setdefault(name, {}).update(evts)

        elif cfg["method"] == "search":
            for name in team_names:
                team_events = fetch_search_for_team(name, fetch_seasons)
                all_events.setdefault(name, {}).update(team_events)

    # Merge with existing cache:
    # - For skipped (past) seasons: keep all old events as-is
    # - For re-fetched (current) seasons: fresh data wins, old fills gaps
    for team_name, old_events in existing.items():
        if team_name not in all_events:
            all_events[team_name] = {}
        for ev in old_events:
            eid = ev.get("id", "")
            if eid and eid not in all_events[team_name]:
                all_events[team_name][eid] = ev

    # Convert to sorted lists
    events_out = {}
    total = 0
    for team_name, evts_dict in sorted(all_events.items()):
        events_list = sorted(evts_dict.values(), key=lambda e: e.get("date", ""), reverse=True)
        events_out[team_name] = events_list
        total += len(events_list)
        print(f"  {team_name}: {len(events_list)} games cached")

    # Build output
    output = {
        "teams": {t["name"]: {
            "team_id": t.get("team_id", ""),
            "league": t.get("league", ""),
            "league_id": t.get("league_id", ""),
            "sport": t.get("sport", ""),
        } for t in teams},
        "events": events_out,
        "updated": datetime.now().isoformat(),
        "total_events": total,
    }

    with open(cache_file, "w") as f:
        json.dump(output, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = os.path.getsize(cache_file) / 1024
    print(f"\n=== Done: {total} events for {len(teams)} teams ({size_kb:.0f} KB) ===")

    # Also save updated teams list (with resolved IDs)
    teams_file = os.path.join(data_dir, "sports_teams.json")
    with open(teams_file, "w") as f:
        json.dump([{
            "name": t["name"],
            "league": t.get("league", ""),
            "league_id": t.get("league_id", ""),
            "team_id": t.get("team_id", ""),
            "sport": t.get("sport", ""),
        } for t in teams], f, indent=2)


if __name__ == "__main__":
    main()
