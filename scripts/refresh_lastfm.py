#!/usr/bin/env python3
"""Fetch Last.fm listening data and save to data/lastfm.json"""
import json, os, sys, time
import urllib.request

LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")
LASTFM_USER = os.environ.get("LASTFM_USER", "")
if not LASTFM_API_KEY or not LASTFM_USER:
    print("Set LASTFM_API_KEY and LASTFM_USER environment variables")
    sys.exit(0)

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "https://ws.audioscrobbler.com/2.0/"

def api(method, **params):
    params["api_key"] = LASTFM_API_KEY
    params["user"] = LASTFM_USER
    params["format"] = "json"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}?method={method}&{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "Iris/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

print("=== Last.fm Refresh ===")

# User info
info = api("user.getinfo")["user"]
total_scrobbles = int(info.get("playcount", 0))
total_artists = int(info.get("artist_count", 0))
total_albums = int(info.get("album_count", 0))
total_tracks = int(info.get("track_count", 0))
print(f"  User: {info['name']}, Scrobbles: {total_scrobbles}, Artists: {total_artists}, Albums: {total_albums}")

# Top artists (all time + by year periods)
top_artists = []
for period in ["overall", "12month", "3month", "1month"]:
    data = api("user.gettopartists", period=period, limit=25)
    artists = [{"n": a["name"], "c": int(a["playcount"])} for a in data.get("topartists", {}).get("artist", [])]
    top_artists.append({"period": period, "artists": artists})
    time.sleep(0.3)

# Top tracks
top_tracks = []
for period in ["overall", "12month", "3month", "1month"]:
    data = api("user.gettoptracks", period=period, limit=20)
    tracks = [{"n": t["name"], "a": t["artist"]["name"], "c": int(t["playcount"])} for t in data.get("toptracks", {}).get("track", [])]
    top_tracks.append({"period": period, "tracks": tracks})
    time.sleep(0.3)

# Top albums
top_albums = []
for period in ["overall", "12month", "3month", "1month"]:
    data = api("user.gettopalbums", period=period, limit=15)
    albums = [{"n": a["name"], "a": a["artist"]["name"], "c": int(a["playcount"]),
               "img": a.get("image", [{}])[-1].get("#text", "")} for a in data.get("topalbums", {}).get("album", [])]
    top_albums.append({"period": period, "albums": albums})
    time.sleep(0.3)

# Top tags/genres (from top artists' tags)
print("  Fetching artist tags for genres...")
genre_counter = {}
for a in top_artists[0]["artists"][:15]:  # top 15 all-time artists
    try:
        data = api("artist.gettoptags", artist=a["n"])
        tags = data.get("toptags", {}).get("tag", [])
        for t in tags[:5]:
            name = t["name"].lower()
            if name not in ("seen live", "favorites", "favourite", "american", "british", "all", ""):
                genre_counter[name] = genre_counter.get(name, 0) + int(t.get("count", 1))
        time.sleep(0.3)
    except:
        pass

top_genres = sorted(genre_counter.items(), key=lambda x: x[1], reverse=True)[:15]
genres = [{"n": g, "c": c} for g, c in top_genres]

# Weekly chart list — aggregate into yearly and monthly buckets
from datetime import datetime
from collections import defaultdict
print("  Fetching weekly charts (all time)...")
weekly = []
yearly_scrobbles = defaultdict(int)
yearly_artist_plays = defaultdict(lambda: defaultdict(int))  # yr -> artist -> plays
yearly_album_plays = defaultdict(lambda: defaultdict(int))   # yr -> album -> plays
monthly_scrobbles = defaultdict(int)
monthly_artist_plays = defaultdict(lambda: defaultdict(int))
monthly_album_plays = defaultdict(lambda: defaultdict(int))
weekly_details = {}  # week_date -> {artists: [...], albums: [...]}
try:
    charts_data = api("user.getweeklychartlist")
    chart_list = charts_data.get("weeklychartlist", {}).get("chart", [])
    for i, ch in enumerate(chart_list):
        try:
            dt = datetime.fromtimestamp(int(ch["from"]))
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
            # Album chart
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
            except:
                pass
            # Keep recent 52 weeks with detail
            if i >= len(chart_list) - 52:
                weekly.append({"week": wk_date, "c": week_total})
                weekly_details[wk_date] = {"artists": wk_artists[:10], "albums": wk_albums[:10]}
            if i % 50 == 0:
                print(f"    Week {i+1}/{len(chart_list)} ({yr})...")
            time.sleep(0.25)
        except:
            pass
except Exception as e:
    print(f"  Weekly chart error: {e}")

# Build top lists per period
def top_n(counter, n=10):
    return [{"n": k, "c": v} for k, v in sorted(counter.items(), key=lambda x: x[1], reverse=True)[:n]]

# Build yearly/monthly summary arrays with top artists/albums
lfm_yearly = sorted([{"yr": y, "s": yearly_scrobbles[y],
                       "a": len(yearly_artist_plays[y]), "al": len(yearly_album_plays[y]),
                       "ta": top_n(yearly_artist_plays[y]), "tal": top_n(yearly_album_plays[y])}
                      for y in yearly_scrobbles], key=lambda x: x["yr"])
lfm_monthly = sorted([{"m": m, "s": monthly_scrobbles[m],
                       "a": len(monthly_artist_plays[m]), "al": len(monthly_album_plays[m]),
                       "ta": top_n(monthly_artist_plays[m]), "tal": top_n(monthly_album_plays[m])}
                       for m in monthly_scrobbles], key=lambda x: x["m"])
print(f"  Years: {len(lfm_yearly)}, Months: {len(lfm_monthly)}")

# Recent tracks (last 200 for activity display)
print("  Fetching recent tracks...")
recent = []
try:
    data = api("user.getrecenttracks", limit=200)
    for t in data.get("recenttracks", {}).get("track", []):
        if not t.get("date"):
            continue
        recent.append({
            "n": t["name"],
            "a": t["artist"]["#text"],
            "al": t.get("album", {}).get("#text", ""),
            "d": t["date"]["#text"],
        })
except Exception as e:
    print(f"  Recent tracks error: {e}")

output = {
    "total": total_scrobbles,
    "artists": total_artists,
    "albums": total_albums,
    "tracks": total_tracks,
    "top_artists": top_artists,
    "top_tracks": top_tracks,
    "top_albums": top_albums,
    "genres": genres,
    "yearly": lfm_yearly,
    "monthly": lfm_monthly,
    "weekly": weekly,
    "wd": weekly_details,
    "recent": recent[:100],
}

with open("data/lastfm.json", "w") as f:
    json.dump(output, f, separators=(",", ":"))

print(f"  Saved: {total_scrobbles} scrobbles, {len(genres)} genres, {len(weekly)} weeks")
print("Done!")
