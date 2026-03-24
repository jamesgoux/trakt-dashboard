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
from user_config import load_user_config, get_service
_ucfg = load_user_config()


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

# ── 2. Genres from top artists' tags (always refresh) ──
print("  Fetching artist tags for genres...")
genres_by_period = {}
fetched_artist_tags = {}
for pdata in top_artists:
    period = pdata["period"]
    genre_counter = {}
    for a in pdata["artists"][:15]:
        if a["n"] not in fetched_artist_tags:
            try:
                data = api("artist.gettoptags", artist=a["n"])
                fetched_artist_tags[a["n"]] = data.get("toptags", {}).get("tag", [])
                time.sleep(0.3)
            except Exception:
                fetched_artist_tags[a["n"]] = []
        for t in fetched_artist_tags[a["n"]][:5]:
            name = t["name"].lower()
            if name not in SKIP_TAGS:
                genre_counter[name] = genre_counter.get(name, 0) + int(t.get("count", 1))
    top_genres = sorted(genre_counter.items(), key=lambda x: x[1], reverse=True)[:15]
    genres_by_period[period] = [{"n": g, "c": c} for g, c in top_genres]
genres = genres_by_period.get("overall", [])

# ── 3. Weekly charts — INCREMENTAL ──
# Load existing yearly/monthly data and only fetch new weeks
print("  Fetching weekly charts (incremental)...")

# Preserve existing aggregated data
old_yearly = {y["yr"]: y for y in existing.get("yearly", [])}
old_monthly = {m["m"]: m for m in existing.get("monthly", [])}
old_weekly = existing.get("weekly", [])
old_wd = existing.get("wd", {})

# Find the most recent week we already have
last_fetched_ts = 0
if old_weekly:
    try:
        last_week = max(w["week"] for w in old_weekly)
        last_fetched_ts = int(datetime.strptime(last_week, "%Y-%m-%d").timestamp())
        print(f"  Last fetched week: {last_week}")
    except Exception:
        pass

# Rebuild mutable aggregates from existing data
yearly_scrobbles = defaultdict(int)
monthly_scrobbles = defaultdict(int)
yearly_artist_plays = defaultdict(lambda: defaultdict(int))
yearly_album_plays = defaultdict(lambda: defaultdict(int))
monthly_artist_plays = defaultdict(lambda: defaultdict(int))
monthly_album_plays = defaultdict(lambda: defaultdict(int))

# Seed from existing yearly/monthly totals
# Track which periods will get new data so we don't double-count
new_periods_y = set()
new_periods_m = set()
if last_fetched_ts:
    try:
        charts_data_pre = api("user.getweeklychartlist")
        for ch in charts_data_pre.get("weeklychartlist", {}).get("chart", []):
            if safe_int(ch["from"]) > last_fetched_ts:
                dt = datetime.fromtimestamp(safe_int(ch["from"]))
                new_periods_y.add(dt.strftime("%Y"))
                new_periods_m.add(dt.strftime("%Y-%m"))
    except Exception:
        pass

for y in existing.get("yearly", []):
    if y["yr"] not in new_periods_y:
        yearly_scrobbles[y["yr"]] = y["s"]
    for a in y.get("ta", []):
        if y["yr"] not in new_periods_y:
            yearly_artist_plays[y["yr"]][a["n"]] = a["c"]
    for a in y.get("tal", []):
        if y["yr"] not in new_periods_y:
            yearly_album_plays[y["yr"]][a["n"]] = a["c"]
for m in existing.get("monthly", []):
    if m["m"] not in new_periods_m:
        monthly_scrobbles[m["m"]] = m["s"]
    for a in m.get("ta", []):
        if m["m"] not in new_periods_m:
            monthly_artist_plays[m["m"]][a["n"]] = a["c"]
    for a in m.get("tal", []):
        if m["m"] not in new_periods_m:
            monthly_album_plays[m["m"]][a["n"]] = a["c"]

weekly = list(old_weekly)
weekly_details = dict(old_wd)

try:
    charts_data = api("user.getweeklychartlist")
    chart_list = charts_data.get("weeklychartlist", {}).get("chart", [])
    
    # Only fetch charts newer than what we have
    new_charts = [ch for ch in chart_list if safe_int(ch["from"]) > last_fetched_ts] if last_fetched_ts else chart_list
    print(f"  Total charts: {len(chart_list)}, New to fetch: {len(new_charts)}")
    
    for i, ch in enumerate(new_charts):
        try:
            dt = datetime.fromtimestamp(safe_int(ch["from"]))
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
            
            weekly.append({"week": wk_date, "c": week_total})
            weekly_details[wk_date] = {"artists": wk_artists[:10], "albums": wk_albums[:10]}
            
            if (i + 1) % 10 == 0:
                print(f"    Fetched {i+1}/{len(new_charts)} new weeks...")
            time.sleep(0.25)
        except Exception:
            pass
except Exception as e:
    print(f"  Weekly chart error: {e}")

# Keep only last 52 weeks of detail
weekly.sort(key=lambda x: x["week"], reverse=True)
weekly = weekly[:52]
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

# ── 5. Build output ──
lfm_yearly = sorted([{"yr": y, "s": yearly_scrobbles[y],
                       "a": len(yearly_artist_plays[y]), "al": len(yearly_album_plays[y]),
                       "ta": top_n(yearly_artist_plays[y]), "tal": top_n(yearly_album_plays[y])}
                      for y in yearly_scrobbles], key=lambda x: x["yr"])
lfm_monthly = sorted([{"m": m, "s": monthly_scrobbles[m],
                       "a": len(monthly_artist_plays[m]), "al": len(monthly_album_plays[m]),
                       "ta": top_n(monthly_artist_plays[m]), "tal": top_n(monthly_album_plays[m])}
                       for m in monthly_scrobbles], key=lambda x: x["m"])

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
}

with open("data/lastfm.json", "w") as f:
    json.dump(output, f, separators=(",", ":"))

print(f"  Saved: {total_scrobbles} scrobbles, {len(lfm_yearly)} years, {len(lfm_monthly)} months, {len(weekly)} weeks")
print("Done!")
