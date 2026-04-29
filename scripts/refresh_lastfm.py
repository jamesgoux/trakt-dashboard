#!/usr/bin/env python3
"""
Fetch Last.fm listening data and save to data/lastfm.json.
INCREMENTAL: Only fetches new weekly charts since last run.
Full data is preserved and merged.
"""
import json, os, sys, time
import urllib.request
from datetime import datetime
from collections import defaultdict
from zoneinfo import ZoneInfo
from user_config import load_user_config, get_service
_ucfg = load_user_config()
_tz_pac = ZoneInfo("America/Los_Angeles")


LASTFM_API_KEY = get_service(_ucfg, "lastfm", "api_key") or os.environ.get("LASTFM_API_KEY", "")
LASTFM_USER = get_service(_ucfg, "lastfm", "username") or os.environ.get("LASTFM_USER", "")
if not LASTFM_API_KEY or not LASTFM_USER:
    print("Set LASTFM_API_KEY and LASTFM_USER environment variables")
    sys.exit(0)

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "https://ws.audioscrobbler.com/2.0/"

def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

def api(method, **params):
    params["api_key"] = LASTFM_API_KEY
    params["user"] = LASTFM_USER
    params["format"] = "json"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}?method={method}&{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "Iris/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

SKIP_TAGS = {"seen live", "favorites", "favourite", "american", "british", "all", ""}

def load_existing():
    if os.path.exists("data/lastfm.json"):
        with open("data/lastfm.json") as f:
            return json.load(f)
    return {}

print("=== Last.fm Refresh (Incremental) ===")
existing = load_existing()

# ── 1. User info + top lists (always refresh, fast) ──
info = api("user.getinfo")["user"]
total_scrobbles = int(info.get("playcount", 0))
total_artists = int(info.get("artist_count", 0))
total_albums = int(info.get("album_count", 0))
total_tracks = int(info.get("track_count", 0))
print(f"  User: {info['name']}, Scrobbles: {total_scrobbles}")

top_artists = []
for period in ["overall", "12month", "3month", "1month"]:
    data = api("user.gettopartists", period=period, limit=50)
    artists = [{"n": a["name"], "c": safe_int(a["playcount"])} for a in data.get("topartists", {}).get("artist", [])]
    top_artists.append({"period": period, "artists": artists})
    time.sleep(0.3)

top_tracks = []
for period in ["overall", "12month", "3month", "1month"]:
    data = api("user.gettoptracks", period=period, limit=50)
    tracks = [{"n": t["name"], "a": t["artist"]["name"], "c": safe_int(t["playcount"])} for t in data.get("toptracks", {}).get("track", [])]
    top_tracks.append({"period": period, "tracks": tracks})
    time.sleep(0.3)

top_albums = []
for period in ["overall", "12month", "3month", "1month"]:
    data = api("user.gettopalbums", period=period, limit=20)
    albums = [{"n": a["name"], "a": a["artist"]["name"], "c": safe_int(a["playcount"]),
               "img": a.get("image", [{}])[-1].get("#text", "")} for a in data.get("topalbums", {}).get("album", [])]
    top_albums.append({"period": period, "albums": albums})
    time.sleep(0.3)

# ── 2. Per-track genre tagging (with persistent cache) ──
# Each scrobble counts toward the genres of the specific TRACK (not just the artist).
# Cache maps "artist\ttrack" → ["genre1", "genre2", "genre3"].
# Falls back to artist-level tags for tracks Last.fm doesn't have tags for.
_TRACK_GENRES_FILE = "data/track_genres_cache.json"
_track_genres_cache = {}
if os.path.exists(_TRACK_GENRES_FILE):
    try:
        with open(_TRACK_GENRES_FILE) as f:
            _track_genres_cache = json.load(f)
        print(f"  Track genres cache: {len(_track_genres_cache)} entries loaded")
    except Exception:
        pass

# Also fetch artist-level tags (used as fallback + for artist_genres.py compatibility)
print("  Fetching artist tags for genre fallback...")
fetched_artist_tags = {}
for pdata in top_artists:
    for a in pdata["artists"][:15]:
        if a["n"] not in fetched_artist_tags:
            try:
                data = api("artist.gettoptags", artist=a["n"])
                fetched_artist_tags[a["n"]] = data.get("toptags", {}).get("tag", [])
                time.sleep(0.3)
            except Exception:
                fetched_artist_tags[a["n"]] = []

_genre_api_calls = 0
_genre_time_limit = time.time() + 180  # 3-minute safety net; cache persists so next run continues

def _get_track_genres(artist, track_name):
    """Get top 3 genre tags for a track. Cache → API → artist fallback."""
    global _genre_api_calls
    key = artist + "\t" + track_name
    if key in _track_genres_cache:
        return _track_genres_cache[key]
    # Try API (no budget cap — only a time limit as safeguard)
    if time.time() < _genre_time_limit:
        try:
            data = api("track.gettoptags", artist=artist, track=track_name)
            tags = data.get("toptags", {}).get("tag", [])
            genres = [t["name"].lower() for t in tags[:5] if t["name"].lower() not in SKIP_TAGS][:3]
            _genre_api_calls += 1
            if genres:
                _track_genres_cache[key] = genres
                return genres
            time.sleep(0.25)
        except Exception:
            _genre_api_calls += 1
    # Fallback: artist-level tags
    if artist in fetched_artist_tags:
        genres = [t["name"].lower() for t in fetched_artist_tags[artist][:5] if t["name"].lower() not in SKIP_TAGS][:3]
        if genres:
            _track_genres_cache[key] = genres
            return genres
    return []

def _compute_genres_from_tracks(track_plays):
    """Given {artist\\ttrack: play_count}, return top 15 genres by scrobble count.
    Processes ALL tracks (no cap) — every scrobble counts toward genres."""
    genre_counter = {}
    for key, plays in track_plays.items():
        parts = key.split("\t", 1)
        artist = parts[0]
        track_name = parts[1] if len(parts) > 1 else parts[0]
        for g in _get_track_genres(artist, track_name):
            genre_counter[g] = genre_counter.get(g, 0) + plays
    return [{"n": g, "c": c} for g, c in sorted(genre_counter.items(), key=lambda x: x[1], reverse=True)[:15]]

# Period-based genres (overall, 12month, 3month, 1month) from top_tracks API data
print("  Computing per-track genres...")
genres_by_period = {}
for pdata in top_tracks:
    period = pdata["period"]
    track_plays = {}
    for t in pdata.get("tracks", []):
        track_plays[t["a"] + "\t" + t["n"]] = t["c"]
    genres_by_period[period] = _compute_genres_from_tracks(track_plays)
genres = genres_by_period.get("overall", [])

# ── 3. Weekly charts — INCREMENTAL ──
# Load existing yearly/monthly data and only fetch new weeks
print("  Fetching weekly charts (incremental)...")

# Preserve existing aggregated data
old_yearly = {y["yr"]: y for y in existing.get("yearly", [])}
old_monthly = {m["m"]: m for m in existing.get("monthly", [])}
old_weekly = existing.get("weekly", [])
old_wd = existing.get("wd", {})

# Migration: older weekly entries didn't store the chart 'from' epoch and used
# Pacific-time date strings while last_fetched_ts compared as UTC, which caused:
#   (a) the same week's chart to be re-fetched every run (52 duplicate entries)
#   (b) the seed-skip branch below to wipe yearly/monthly aggregates for the
#       current year and current month every time a new week was crossed
# (Bug introduced 2026-03-09 in commit b3bbf62 when incremental fetching was added.)
#
# When we detect old-format data, do a TARGETED rebuild: only the current year
# is corrupted (pre-current-year aggregates were snapshotted before the bug),
# so we wipe only that year's cached aggregates and re-fetch only that year's
# weekly charts. The new_charts derivation below filters by year when in
# migration mode. This keeps the migration run under ~30 sec instead of ~20 min.
_has_from = any(w.get("from") for w in old_weekly)
_migration_year = None
if old_weekly and not _has_from:
    _migration_year = str(datetime.now(tz=_tz_pac).year)
    print(f"  Migration: old format detected — wiping {_migration_year} aggregates and re-fetching {_migration_year} weekly charts only")
    existing["yearly"] = [y for y in existing.get("yearly", []) if y["yr"] != _migration_year]
    existing["monthly"] = [m for m in existing.get("monthly", []) if not m["m"].startswith(_migration_year + "-")]
    old_yearly = {y["yr"]: y for y in existing["yearly"]}
    old_monthly = {m["m"]: m for m in existing["monthly"]}
    # Drop the duplicate-polluted weekly entries; cur-year weeks will be re-fetched.
    # Pre-cur-year weekly entries were already corrupted by the same bug, so dropping
    # them is no regression — the dashboard's weekly view filters to the selected year.
    old_weekly = []
    old_wd = {}

# Use the chart 'from' epoch as the canonical week identifier (timezone-agnostic).
# Build a from-keyed dict so duplicate fetches replace rather than append.
weekly_by_from = {w["from"]: w for w in old_weekly if w.get("from")}

# Track the highest chart epoch we've ever processed. This is the cutoff for
# "new" charts — anything with from <= this has already been counted in the
# seeded yearly/monthly aggregates. Using a single max epoch (instead of a set
# of all fetched epochs) avoids the problem where the 52-entry weekly array
# doesn't cover pre-current-year charts, causing 1000+ re-fetches and timeouts.
_last_chart_from = existing.get("_last_chart_from", 0)
if not _last_chart_from and weekly_by_from:
    _last_chart_from = max(weekly_by_from.keys())
print(f"  Last chart from: {_last_chart_from}")

# Rebuild mutable aggregates from existing data
yearly_scrobbles = defaultdict(int)
monthly_scrobbles = defaultdict(int)
yearly_artist_plays = defaultdict(lambda: defaultdict(int))
yearly_album_plays = defaultdict(lambda: defaultdict(int))
yearly_track_plays = defaultdict(lambda: defaultdict(int))
monthly_artist_plays = defaultdict(lambda: defaultdict(int))
monthly_album_plays = defaultdict(lambda: defaultdict(int))
monthly_track_plays = defaultdict(lambda: defaultdict(int))
# Genre counters — accumulated per-track during the weekly fetch loop so EVERY
# scrobble is counted (not just the saved top-50 tracks).
yearly_genre_plays = defaultdict(lambda: defaultdict(int))
monthly_genre_plays = defaultdict(lambda: defaultdict(int))

# Seed from existing yearly/monthly totals UNCONDITIONALLY.
# The new_charts loop below only fetches charts whose 'from' epoch isn't already
# in old_weekly_from_set, so seeded counts won't be double-counted by new += adds.
for y in existing.get("yearly", []):
    yearly_scrobbles[y["yr"]] = y["s"]
    for a in y.get("ta", []):
        yearly_artist_plays[y["yr"]][a["n"]] = a["c"]
    for a in y.get("tal", []):
        yearly_album_plays[y["yr"]][a["n"]] = a["c"]
    for t in y.get("tt", []):
        yearly_track_plays[y["yr"]][t["a"] + "\t" + t["n"]] = t["c"]
    for g in y.get("g", []):
        yearly_genre_plays[y["yr"]][g["n"]] = g["c"]
for m in existing.get("monthly", []):
    monthly_scrobbles[m["m"]] = m["s"]
    for a in m.get("ta", []):
        monthly_artist_plays[m["m"]][a["n"]] = a["c"]
    for a in m.get("tal", []):
        monthly_album_plays[m["m"]][a["n"]] = a["c"]
    for t in m.get("tt", []):
        monthly_track_plays[m["m"]][t["a"] + "\t" + t["n"]] = t["c"]

weekly_details = dict(old_wd)

try:
    charts_data = api("user.getweeklychartlist")
    chart_list = charts_data.get("weeklychartlist", {}).get("chart", [])

    if _migration_year:
        # Migration: re-fetch only the current year's charts. Pre-cur-year aggregates
        # are already correct (snapshotted before the bug was introduced 2026-03-09).
        new_charts = []
        for ch in chart_list:
            ts = safe_int(ch["from"])
            ch_dt = datetime.fromtimestamp(ts, tz=_tz_pac)
            if ch_dt.strftime("%Y") == _migration_year:
                new_charts.append(ch)
        print(f"  Migration: filtered to {len(new_charts)} {_migration_year} weeks (out of {len(chart_list)} total)")
    else:
        # Fetch only charts newer than the highest epoch we've ever processed.
        # This is timezone-safe (compares raw epochs) and prevents both the
        # duplicate-fetch bug and the post-migration 1000+ chart re-fetch timeout.
        new_charts = [ch for ch in chart_list if safe_int(ch["from"]) > _last_chart_from]
        print(f"  Total charts: {len(chart_list)}, New to fetch: {len(new_charts)}")

    for i, ch in enumerate(new_charts):
        try:
            from_ts = safe_int(ch["from"])
            dt = datetime.fromtimestamp(from_ts, tz=_tz_pac)
            yr = dt.strftime("%Y")
            mo = dt.strftime("%Y-%m")
            wk_date = dt.strftime("%Y-%m-%d")

            wk = api("user.getweeklyartistchart", **{"from": ch["from"], "to": ch["to"]})
            artists_in_week = wk.get("weeklyartistchart", {}).get("artist", [])
            week_total = sum(int(a.get("playcount", 0)) for a in artists_in_week)
            yearly_scrobbles[yr] += week_total
            monthly_scrobbles[mo] += week_total

            wk_artists = []
            for a in artists_in_week:
                pc = int(a.get("playcount", 0))
                yearly_artist_plays[yr][a["name"]] += pc
                monthly_artist_plays[mo][a["name"]] += pc
                wk_artists.append({"n": a["name"], "c": pc})

            wk_albums = []
            try:
                wka = api("user.getweeklyalbumchart", **{"from": ch["from"], "to": ch["to"]})
                for al in wka.get("weeklyalbumchart", {}).get("album", []):
                    pc = int(al.get("playcount", 0))
                    name = al["name"]
                    artist = al["artist"]["#text"]
                    yearly_album_plays[yr][artist + " — " + name] += pc
                    monthly_album_plays[mo][artist + " — " + name] += pc
                    wk_albums.append({"n": name, "a": artist, "c": pc})
            except Exception:
                pass

            # Track chart (for per-year/month top tracks AND per-track genres)
            try:
                wkt = api("user.getweeklytrackchart", **{"from": ch["from"], "to": ch["to"]})
                for t in wkt.get("weeklytrackchart", {}).get("track", []):
                    pc = int(t.get("playcount", 0))
                    t_artist = t["artist"]["#text"]
                    t_name = t["name"]
                    key = t_artist + "\t" + t_name
                    yearly_track_plays[yr][key] += pc
                    monthly_track_plays[mo][key] += pc
                    # Accumulate genres for EVERY scrobble (not just top-50)
                    for g in _get_track_genres(t_artist, t_name):
                        yearly_genre_plays[yr][g] += pc
                        monthly_genre_plays[mo][g] += pc
            except Exception:
                pass

            # Store with 'from' epoch so re-runs deduplicate by chart identity, not date string
            weekly_by_from[from_ts] = {"week": wk_date, "c": week_total, "from": from_ts}
            weekly_details[wk_date] = {"artists": wk_artists[:10], "albums": wk_albums[:10]}

            # Update the high-water mark
            if from_ts > _last_chart_from:
                _last_chart_from = from_ts

            if (i + 1) % 10 == 0:
                print(f"    Fetched {i+1}/{len(new_charts)} new weeks...")
            time.sleep(0.25)
        except Exception:
            pass
except Exception as e:
    print(f"  Weekly chart error: {e}")

# Keep only last 52 weeks of detail (sort by 'from' epoch, then drop oldest)
weekly = sorted(weekly_by_from.values(), key=lambda x: x.get("from", 0), reverse=True)[:52]
keep_weeks = set(w["week"] for w in weekly)
weekly_details = {k: v for k, v in weekly_details.items() if k in keep_weeks}

# ── 4. Recent tracks (always refresh, ~30 days) ──
def top_n(counter, n=10):
    return [{"n": k, "c": v} for k, v in sorted(counter.items(), key=lambda x: x[1], reverse=True)[:n]]

print("  Fetching recent tracks...")
recent = []
try:
    for page in range(1, 20):
        data = api("user.getrecenttracks", limit=200, page=page)
        tracks = data.get("recenttracks", {}).get("track", [])
        if not tracks:
            break
        for t in tracks:
            if not t.get("date"):
                continue
            recent.append({
                "n": t["name"],
                "a": t["artist"]["#text"],
                "al": t.get("album", {}).get("#text", ""),
                "d": t["date"]["#text"],
            })
        if len(recent) > 100:
            oldest = recent[-1]["d"]
            try:
                from datetime import datetime as dt2
                oldest_date = dt2.strptime(oldest, "%d %b %Y, %H:%M")
                if (dt2.now() - oldest_date).days >= 35:
                    break
            except Exception:
                pass
        time.sleep(0.3)
except Exception as e:
    print(f"  Recent tracks error: {e}")
print(f"  Recent tracks: {len(recent)}")

# ── 4b. Per-year genres ──
# Two sources: (1) yearly_genre_plays accumulated per-track during the weekly
# fetch loop (comprehensive — every scrobble counted). (2) For years where the
# weekly loop didn't run (0 new charts, seeded from previous top-50-only data),
# fall back to artist-level genre computation from yearly_artist_plays which
# covers 100% of scrobbles.
print("  Computing per-year genres...")
# Ensure artist tags exist for yearly + period artists (for genre fallback)
_all_genre_artists = set()
for yr in yearly_artist_plays:
    _all_genre_artists.update(list(yearly_artist_plays[yr].keys())[:50])
for pdata in top_artists:
    for a in pdata["artists"]:
        _all_genre_artists.add(a["n"])
for artist_name in _all_genre_artists:
    if artist_name not in fetched_artist_tags and time.time() < _genre_time_limit:
        try:
            data = api("artist.gettoptags", artist=artist_name)
            fetched_artist_tags[artist_name] = data.get("toptags", {}).get("tag", [])
            time.sleep(0.25)
        except Exception:
            fetched_artist_tags[artist_name] = []

# Also pull in artist play counts from the period-based top_artists (50 per period)
# as supplementary data — these cover more artists than the yearly top-10/50 seed.
_cur_yr = str(datetime.now(tz=_tz_pac).year)
_period_artist_plays = {}  # {artist: plays} for the best matching period
for pdata in top_artists:
    if pdata["period"] == "12month":
        for a in pdata["artists"]:
            _period_artist_plays[a["n"]] = a["c"]

yearly_genres = {}
for yr in set(list(yearly_genre_plays.keys()) + list(yearly_scrobbles.keys())):
    genre_data = yearly_genre_plays.get(yr, {})
    genre_total = sum(genre_data.values())
    yr_scrobbles = yearly_scrobbles.get(yr, 0)
    # If per-track genres cover less than 50% of the year's scrobbles,
    # rebuild from artist-level plays. Merge yearly_artist_plays with
    # period-based data for comprehensive coverage.
    if yr_scrobbles > 0 and genre_total < yr_scrobbles * 0.5:
        genre_data = {}
        # Combine yearly artist plays with period data (for current year)
        combined_artists = dict(yearly_artist_plays.get(yr, {}))
        if yr == _cur_yr:
            for artist_name, plays in _period_artist_plays.items():
                if artist_name not in combined_artists:
                    combined_artists[artist_name] = plays
        for artist_name, play_count in combined_artists.items():
            if artist_name in fetched_artist_tags:
                tags = fetched_artist_tags[artist_name]
            else:
                tags = []
            genres = [t["name"].lower() for t in tags[:5] if t["name"].lower() not in SKIP_TAGS][:3]
            for g in genres:
                genre_data[g] = genre_data.get(g, 0) + play_count
    top = sorted(genre_data.items(), key=lambda x: x[1], reverse=True)[:15]
    yearly_genres[yr] = [{"n": g, "c": c} for g, c in top]
print(f"  Genres: {len(yearly_genres)} years, track cache: {len(_track_genres_cache)} entries ({_genre_api_calls} track API calls)")

# Save track genres cache
with open(_TRACK_GENRES_FILE, "w") as f:
    json.dump(_track_genres_cache, f, separators=(",", ":"))

# ── 5. Build output ──
# Album image cache from period-based top_albums (already fetched with covers)
_alb_img_cache = {}
for pdata in top_albums:
    for a in pdata.get("albums", []):
        key = a["n"] + "\t" + a["a"]
        if a.get("img") and key not in _alb_img_cache:
            _alb_img_cache[key] = a["img"]

def top_n_albums(counter, n=10):
    """Like top_n but attaches album images from the period-based cache."""
    items = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:n]
    result = []
    for key, count in items:
        parts = key.split(" — ", 1)
        artist = parts[0] if len(parts) > 1 else ""
        name = parts[1] if len(parts) > 1 else parts[0]
        entry = {"n": key, "c": count}
        img = _alb_img_cache.get(name + "\t" + artist, "")
        if img:
            entry["img"] = img
        result.append(entry)
    return result

def top_n_tracks(counter, n=50):
    items = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:n]
    result = []
    for key, count in items:
        parts = key.split("\t", 1)
        result.append({"n": parts[1] if len(parts) > 1 else parts[0], "a": parts[0], "c": count})
    return result

lfm_yearly = sorted([{"yr": y, "s": yearly_scrobbles[y],
                       "a": len(yearly_artist_plays[y]), "al": len(yearly_album_plays[y]),
                       "ta": top_n(yearly_artist_plays[y], 50), "tal": top_n_albums(yearly_album_plays[y]),
                       "tt": top_n_tracks(yearly_track_plays[y]),
                       "g": yearly_genres.get(y, [])}
                      for y in yearly_scrobbles], key=lambda x: x["yr"])
lfm_monthly = sorted([{"m": m, "s": monthly_scrobbles[m],
                       "a": len(monthly_artist_plays[m]), "al": len(monthly_album_plays[m]),
                       "ta": top_n(monthly_artist_plays[m]), "tal": top_n_albums(monthly_album_plays[m]),
                       "tt": top_n_tracks(monthly_track_plays[m])}
                       for m in monthly_scrobbles], key=lambda x: x["m"])

# ── 5b. Fill missing album covers via album.getinfo ──
# Year-aggregated albums may not appear in any period top-20, so they miss
# the _alb_img_cache built from period-based data. Fetch covers for up to
# 30 uncovered albums per run (budgeted to stay under ~10s extra).
_cover_budget = 30
_cover_fetched = 0
_cover_filled = 0
_cover_fail_cache = set()  # avoid re-fetching known failures within this run
print("  Filling missing album covers...")
for entry_list in [lfm_yearly, lfm_monthly]:
    for entry in entry_list:
        for a in entry.get("tal", []):
            if a.get("img") or _cover_fetched >= _cover_budget:
                continue
            parts = a["n"].split(" — ", 1)
            artist = parts[0] if len(parts) > 1 else ""
            name = parts[1] if len(parts) > 1 else parts[0]
            cache_key = name + "\t" + artist
            if cache_key in _cover_fail_cache:
                continue
            if cache_key in _alb_img_cache:
                a["img"] = _alb_img_cache[cache_key]
                _cover_filled += 1
                continue
            try:
                ainfo = api("album.getinfo", album=name, artist=artist)
                images = ainfo.get("album", {}).get("image", [])
                img_url = images[-1].get("#text", "") if images else ""
                _cover_fetched += 1
                if img_url:
                    a["img"] = img_url
                    _alb_img_cache[cache_key] = img_url
                    _cover_filled += 1
                else:
                    _cover_fail_cache.add(cache_key)
                time.sleep(0.3)
            except Exception:
                _cover_fail_cache.add(cache_key)
                _cover_fetched += 1
print(f"  Album covers: {_cover_filled} filled, {_cover_fetched} API calls, {len(_cover_fail_cache)} unavailable")

output = {
    "total": total_scrobbles,
    "artists": total_artists,
    "albums": total_albums,
    "tracks": total_tracks,
    "top_artists": top_artists,
    "top_tracks": top_tracks,
    "top_albums": top_albums,
    "genres": genres,
    "genres_p": genres_by_period,
    "yearly": lfm_yearly,
    "monthly": lfm_monthly,
    "weekly": weekly,
    "wd": weekly_details,
    "recent": recent,
    "_last_chart_from": _last_chart_from,
}

with open("data/lastfm.json", "w") as f:
    json.dump(output, f, separators=(",", ":"))

print(f"  Saved: {total_scrobbles} scrobbles, {len(lfm_yearly)} years, {len(lfm_monthly)} months, {len(weekly)} weeks")
print("Done!")
