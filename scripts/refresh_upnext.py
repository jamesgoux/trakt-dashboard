#!/usr/bin/env python3
"""Fetch Up Next data from Trakt — next unwatched episode + recent history + streaming info."""
import os, sys, json, time, urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import retry_request, get_trakt_access_token
from user_config import load_user_config, get_service
_ucfg = load_user_config()


CLIENT_ID = get_service(_ucfg, "trakt", "client_id") or os.environ.get("TRAKT_CLIENT_ID")
USERNAME = get_service(_ucfg, "trakt", "username") or os.environ.get("TRAKT_USERNAME")
ACCESS_TOKEN = get_trakt_access_token()
TMDB_API_KEY = get_service(_ucfg, "_tmdb", "api_key") or os.environ.get("TMDB_API_KEY", "")
BASE = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}
AUTH_HEADERS = {**HEADERS, "Authorization": f"Bearer {ACCESS_TOKEN}"} if ACCESS_TOKEN else HEADERS

if not CLIENT_ID or not USERNAME:
    print("ERROR: Set TRAKT_CLIENT_ID and TRAKT_USERNAME"); sys.exit(1)
if not ACCESS_TOKEN:
    print("WARNING: TRAKT_ACCESS_TOKEN not set — progress endpoint requires OAuth")

NEW_PIN_DAYS = 30
JW_QUERY = 'query($path:String!){urlV2(fullPath:$path){node{...on MovieOrShow{offers(country:US platform:WEB filter:{monetizationTypes:[FLATRATE]}){package{clearName shortName icon(profile:S100 format:PNG)}}}}}}'


def fetch_streaming(slug):
    """Get streaming services from JustWatch for a show."""
    try:
        body = json.dumps({"query": JW_QUERY, "variables": {"path": f"/us/tv-show/{slug}"}}).encode()
        req = urllib.request.Request("https://apis.justwatch.com/graphql",
                                     data=body, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        d = json.loads(resp.read())
        offers = d.get("data", {}).get("urlV2", {}).get("node", {}).get("offers", [])
        seen = set()
        result = []
        for o in offers:
            p = o["package"]
            sn = p["shortName"]
            if sn in seen:
                continue
            seen.add(sn)
            result.append({"n": p["clearName"], "s": sn, "i": "https://images.justwatch.com" + p["icon"]})
        return result[:3]  # Top 3 streaming options
    except Exception:
        return []


def fetch_ep_still(tmdb_id, season, episode):
    """Get episode still image from TMDB."""
    if not TMDB_API_KEY or not tmdb_id:
        return ""
    try:
        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={TMDB_API_KEY}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        d = json.loads(resp.read())
        still = d.get("still_path", "")
        return f"https://image.tmdb.org/t/p/w780{still}" if still else ""
    except Exception:
        return ""


def fetch_tmdb_episode(tmdb_id, season, episode):
    """Get full episode info from TMDB (air_date, name, runtime, overview, still)."""
    if not TMDB_API_KEY or not tmdb_id:
        return None
    try:
        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={TMDB_API_KEY}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read())
    except Exception:
        return None


def fetch_season_runtimes(slug):
    """Fetch per-episode runtimes from Trakt seasons endpoint."""
    r = retry_request("get", f"{BASE}/shows/{slug}/seasons?extended=full,episodes",
                      headers=AUTH_HEADERS, timeout=15)
    if not r or r.status_code != 200:
        return {}
    runtimes = {}
    for season in r.json():
        sn = season.get("number", 0)
        for ep in season.get("episodes", []):
            rt = ep.get("runtime", 0)
            if rt:
                runtimes[(sn, ep.get("number", 0))] = rt
    return runtimes


def fetch_recent_history():
    """Fetch last 20 watched episodes from Trakt history."""
    r = retry_request("get", f"{BASE}/users/{USERNAME}/history/episodes?limit=100&extended=full",
                      headers=AUTH_HEADERS, timeout=10)
    if not r or r.status_code != 200:
        return []
    items = []
    for e in r.json():
        show = e.get("show", {})
        ep = e.get("episode", {})
        items.append({
            "show": show.get("title", ""),
            "slug": show.get("ids", {}).get("slug", ""),
            "season": ep.get("season", 0),
            "episode": ep.get("number", 0),
            "ep_title": ep.get("title", ""),
            "watched_at": e.get("watched_at", ""),
            "ep_id": e.get("id", 0),
            "ep_aired": (ep.get("first_aired") or "")[:10],
        })
    return items


def run():
    # Load existing streaming cache (including empty results to avoid re-fetching)
    stream_cache = {}
    if os.path.exists("data/up_next.json"):
        with open("data/up_next.json") as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                for item in raw.get("shows", []):
                    if "stream" in item:
                        stream_cache[item["slug"]] = item["stream"]

    # Fetch recent watch history
    print("Fetching recent history...")
    recent = fetch_recent_history()
    print(f"  {len(recent)} recent episodes")

    # Build set of recently watched episodes for cross-check against stale progress
    recent_set = set()
    for re_ep in recent:
        recent_set.add(f"{re_ep.get('slug')}|{re_ep.get('season')}|{re_ep.get('episode')}")

    print("Fetching watched shows...")
    r = retry_request("get", f"{BASE}/users/{USERNAME}/watched/shows?extended=full",
                      headers=AUTH_HEADERS, timeout=15)
    if not r or r.status_code != 200:
        print(f"Failed: {r.status_code if r else 'no response'}"); return
    watched = r.json()
    print(f"  {len(watched)} shows")

    posters = {}
    if os.path.exists("data/posters.json"):
        with open("data/posters.json") as f:
            posters = json.load(f)

    now = datetime.now(timezone.utc)
    results = []
    total = len(watched)
    stream_fetched = 0

    for i, show_data in enumerate(watched):
        show = show_data.get("show", {})
        slug = show.get("ids", {}).get("slug", "")
        if not slug:
            continue

        last_watched = show_data.get("last_watched_at", "")

        r2 = retry_request("get", f"{BASE}/shows/{slug}/progress/watched?extended=full",
                           headers=AUTH_HEADERS, timeout=10)
        if not r2 or r2.status_code != 200:
            time.sleep(0.3); continue

        prog = r2.json()
        next_ep = prog.get("next_episode")

        # Verify next_episode isn't stale (already completed per season data)
        if next_ep:
            ne_s = next_ep.get("season", 0)
            ne_e = next_ep.get("number", 0)
            for sn in prog.get("seasons", []):
                if sn.get("number") == ne_s:
                    for ep in sn.get("episodes", []):
                        if ep.get("number") == ne_e and ep.get("completed", False):
                            print(f"  Stale next_episode for {slug}: S{ne_s:02d}E{ne_e:02d} already completed, deriving...")
                            next_ep = None  # Fall through to derive from seasons
                    break

        if not next_ep:
            aired = prog.get("aired", 0)
            completed = prog.get("completed", 0)
            if aired <= completed:
                continue
            # next_episode is null/stale — derive from seasons (first unwatched episode)
            for sn in prog.get("seasons", []):
                sn_num = sn.get("number", 0)
                if sn_num == 0:
                    continue  # skip specials
                for ep in sn.get("episodes", []):
                    if not ep.get("completed", False):
                        next_ep = {"season": sn_num, "number": ep.get("number", 0),
                                   "title": ep.get("title", ""), "first_aired": ep.get("first_aired", ""),
                                   "runtime": ep.get("runtime", 0), "overview": ep.get("overview", ""),
                                   "ids": {"trakt": ep.get("ids", {}).get("trakt", "")}}
                        break
                if next_ep:
                    break
            if not next_ep:
                continue  # truly nothing to watch
            print(f"  Derived next ep for {slug}: S{next_ep['season']:02d}E{next_ep['number']:02d}")

        ep_aired = next_ep.get("first_aired", "")
        is_aired = False
        aired_days_ago = None
        if ep_aired:
            try:
                aired_dt = datetime.fromisoformat(ep_aired.replace("Z", "+00:00"))
                is_aired = aired_dt <= now
                aired_days_ago = (now - aired_dt).days
            except Exception:
                pass

        # Skip episodes that haven't aired yet
        if ep_aired and not is_aired:
            continue

        is_new = is_aired and aired_days_ago is not None and aired_days_ago <= NEW_PIN_DAYS
        poster = posters.get(slug, "")
        ep_runtime = next_ep.get("runtime", 0) or show.get("runtime", 0) or 0

        # Fetch per-episode runtimes for accurate remaining time
        rt_map = fetch_season_runtimes(slug)
        remaining_min = 0
        for sn in prog.get("seasons", []):
            sn_num = sn.get("number", 0)
            for ep in sn.get("episodes", []):
                if not ep.get("completed", False):
                    ep_num = ep.get("number", 0)
                    remaining_min += rt_map.get((sn_num, ep_num), ep_runtime)

        aired_total = prog.get("aired", 0)
        completed = prog.get("completed", 0)
        if aired_total and completed >= aired_total:
            continue  # 100% caught up

        # If next episode already in recent history, progress API is stale —
        # try to advance to the following episode using TMDB
        ep_key = f"{slug}|{next_ep.get('season', 0)}|{next_ep.get('number', 0)}"
        if ep_key in recent_set:
            ne_s = next_ep.get("season", 0)
            ne_e = next_ep.get("number", 0)
            tmdb_id_val = show.get("ids", {}).get("tmdb", "")
            advanced = False
            if tmdb_id_val:
                ep_info = fetch_tmdb_episode(tmdb_id_val, ne_s, ne_e + 1)
                if ep_info and ep_info.get("air_date"):
                    try:
                        ep_dt = datetime.fromisoformat(ep_info["air_date"] + "T00:00:00+00:00")
                        if ep_dt <= now:
                            still = ep_info.get("still_path", "")
                            next_ep = {
                                "season": ne_s, "number": ne_e + 1,
                                "title": ep_info.get("name", ""),
                                "first_aired": ep_info["air_date"],
                                "runtime": ep_info.get("runtime", 0),
                                "overview": (ep_info.get("overview", "") or "")[:500],
                                "ids": {"trakt": ep_info.get("id", "")},
                                "_still": f"https://image.tmdb.org/t/p/w780{still}" if still else "",
                            }
                            completed += 1
                            aired_total = max(aired_total, completed + 1)
                            print(f"  Advanced {slug} past stale S{ne_s:02d}E{ne_e:02d} → S{ne_s:02d}E{ne_e+1:02d}")
                            advanced = True
                    except Exception:
                        pass
            if not advanced:
                continue

        # Episode overview from extended data
        ep_overview = next_ep.get("overview", "")

        # Episode still image from TMDB (skip if already fetched during advance)
        tmdb_id = show.get("ids", {}).get("tmdb", "")
        ep_still = next_ep.pop("_still", "")
        if not ep_still and tmdb_id and TMDB_API_KEY:
            ep_still = fetch_ep_still(tmdb_id, next_ep.get("season", 1), next_ep.get("number", 1))
            time.sleep(0.15)

        # Streaming info (cache to avoid hammering JustWatch)
        stream = stream_cache.get(slug)
        if stream is None and stream_fetched < 100:
            stream = fetch_streaming(slug)
            stream_cache[slug] = stream
            stream_fetched += 1
            time.sleep(0.3)

        eps_left = aired_total - completed

        entry = {
            "slug": slug,
            "show": show.get("title", ""),
            "trakt_id": show.get("ids", {}).get("trakt", ""),
            "tmdb_id": show.get("ids", {}).get("tmdb", ""),
            "season": next_ep.get("season", 0),
            "episode": next_ep.get("number", 0),
            "ep_title": next_ep.get("title", ""),
            "ep_runtime": ep_runtime,
            "ep_overview": ep_overview[:500] if ep_overview else "",
            "ep_still": ep_still,
            "ep_aired": ep_aired[:10] if ep_aired else "",
            "ep_trakt_id": next_ep.get("ids", {}).get("trakt", ""),
            "is_new": is_new,
            "last_watched": last_watched,
            "poster": poster,
            "aired_total": aired_total,
            "completed": completed,
            "eps_left": eps_left,
            "remaining_min": remaining_min,
            "stream": stream or [],
        }
        results.append(entry)

        if (i + 1) % 50 == 0:
            print(f"  progress: {i+1}/{total}")
        time.sleep(0.8)

    # Sort: new first, then by last_watched desc
    new_items = sorted([r for r in results if r["is_new"]], key=lambda x: x.get("last_watched", ""), reverse=True)
    rest = sorted([r for r in results if not r["is_new"]], key=lambda x: x.get("last_watched", ""), reverse=True)

    # Merge with previous data to preserve shows lost to API failures
    # But only if the show still exists in the user's watched list on Trakt
    # (if it's gone from watched entirely, the user removed it — don't preserve)
    prev_shows = []
    if os.path.exists("data/up_next.json"):
        try:
            with open("data/up_next.json") as f:
                prev = json.load(f)
            prev_shows = prev.get("shows", [])
        except Exception:
            pass
    current_slugs = set(r["slug"] for r in results)
    watched_slugs = set(s.get("show", {}).get("ids", {}).get("slug", "") for s in watched)
    preserved = 0
    skipped_complete = 0
    skipped_removed = 0
    for ps in prev_shows:
        if ps.get("slug") and ps["slug"] not in current_slugs:
            # Don't preserve shows the user removed from their watch history
            if ps["slug"] not in watched_slugs:
                skipped_removed += 1
                continue
            # Don't preserve shows whose next episode is already in recent history
            # (progress API was stale — if we couldn't advance, the show is caught up)
            ps_ep_key = f"{ps['slug']}|{ps.get('season', 0)}|{ps.get('episode', 0)}"
            if ps_ep_key in recent_set:
                skipped_complete += 1
                continue
            # Don't preserve shows that are actually complete — they were
            # skipped by the current run for a reason (100% caught up)
            at = ps.get("aired_total", 0)
            comp = ps.get("completed", 0)
            if at > 0 and comp >= at:
                skipped_complete += 1
                continue
            # Don't preserve shows whose next episode hasn't aired yet
            ps_aired = ps.get("ep_aired", "")
            if ps_aired:
                try:
                    ps_dt = datetime.fromisoformat(ps_aired + "T00:00:00+00:00")
                    if ps_dt > now:
                        continue
                except Exception:
                    pass
            results.append(ps)
            preserved += 1
    if preserved:
        # Re-sort after merge
        new_items = sorted([r for r in results if r.get("is_new")], key=lambda x: x.get("last_watched", ""), reverse=True)
        rest = sorted([r for r in results if not r.get("is_new")], key=lambda x: x.get("last_watched", ""), reverse=True)
        print(f"  Preserved {preserved} shows from previous data (API failures)")
    if skipped_removed:
        print(f"  Dropped {skipped_removed} previously-preserved shows (removed from Trakt history)")
    if skipped_complete:
        print(f"  Dropped {skipped_complete} previously-preserved shows (now 100% complete)")

    all_shows = new_items + rest
    with_stream = sum(1 for s in all_shows if s.get("stream"))
    print(f"  Streaming: {with_stream}/{len(all_shows)} shows, {stream_fetched} new lookups")
    output = {"shows": all_shows, "recent": recent, "tmdb_key": TMDB_API_KEY}

    os.makedirs("data", exist_ok=True)
    with open("data/up_next.json", "w") as f:
        json.dump(output, f, separators=(',', ':'))
    print(f"  Saved {len(results)} shows ({len(new_items)} new), {len(recent)} recent")

if __name__ == "__main__":
    run()
