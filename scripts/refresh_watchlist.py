#!/usr/bin/env python3
"""
Fetch watchlist data from Letterboxd (RSS) and Trakt (API).
Enrich with TMDB runtimes/posters and JustWatch streaming + rental + purchase prices.
Saves to data/watchlist.json for dashboard.
"""
import os, sys, json, time, urllib.request, requests
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import retry_request
from user_config import load_user_config, get_service
_ucfg = load_user_config()


CLIENT_ID = get_service(_ucfg, "trakt", "client_id") or os.environ.get("TRAKT_CLIENT_ID")
USERNAME = get_service(_ucfg, "trakt", "username") or os.environ.get("TRAKT_USERNAME", "jamesgoux")
TMDB_API_KEY = get_service(_ucfg, "_tmdb", "api_key") or os.environ.get("TMDB_API_KEY", "")
BASE = "https://api.trakt.tv"
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID}
LB_USERNAME = get_service(_ucfg, "letterboxd", "username") or os.environ.get("LETTERBOXD_USERNAME", USERNAME)

# JustWatch query: FLATRATE + RENT + BUY with prices
JW_QUERY = """query($path:String!){urlV2(fullPath:$path){node{...on MovieOrShow{
  offers(country:US platform:WEB){
    monetizationType
    retailPrice(language:en)
    package{clearName shortName icon(profile:S100 format:PNG)}
  }
}}}}"""

JW_BUDGET = 100  # max new JustWatch lookups per run
JW_STALE_HOURS = 24  # re-fetch JW prices older than this


def fetch_letterboxd_watchlist():
    """Fetch Letterboxd watchlist by scraping HTML pages.
    RSS endpoint (/watchlist/rss/) is Cloudflare-blocked from GH Actions,
    but the HTML pages work fine with a browser User-Agent."""
    import re as _re
    print(f"Fetching Letterboxd watchlist ({LB_USERNAME})...")
    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    # Load existing LB→TMDB cache for slug-based lookups
    lb_tmdb = {}
    if os.path.exists("data/lb_tmdb_cache.json"):
        with open("data/lb_tmdb_cache.json") as f:
            lb_tmdb = json.load(f)

    movies = []
    for page in range(1, 20):  # up to ~500 films
        url = f"https://letterboxd.com/{LB_USERNAME}/watchlist/page/{page}/"
        try:
            r = requests.get(url, timeout=15, headers=ua)
            if r.status_code != 200:
                break
        except Exception as e:
            print(f"  Page {page} error: {e}")
            break

        # Extract film data from HTML attributes
        films = _re.findall(
            r'data-item-name="([^"]+)"\s+data-item-slug="([^"]+)"\s+'
            r'data-item-link="([^"]+)"\s+data-item-full-display-name="([^"]+)"\s+'
            r'data-film-id="(\d+)"',
            r.text
        )
        if not films:
            break

        for name, slug, link, full_name, film_id in films:
            # Parse "Title (Year)" from full display name
            ym = _re.match(r'^(.+)\s+\((\d{4})\)$', full_name)
            title = ym.group(1) if ym else name
            # Unescape HTML entities
            title = title.replace("&#039;", "'").replace("&amp;", "&").replace("&quot;", '"')
            year = int(ym.group(2)) if ym else None

            # Try to get TMDB ID from cache (slug-based or title|year format)
            tmdb_id = lb_tmdb.get(slug, {}).get("tmdb_id") if isinstance(lb_tmdb.get(slug), dict) else lb_tmdb.get(slug)
            if not tmdb_id and year:
                tmdb_id = lb_tmdb.get(f"{title}|{year}")
            if not tmdb_id:
                tmdb_id = lb_tmdb.get(f"{name}|{year}") if year else None

            movies.append({
                "title": title,
                "year": year,
                "tmdb_id": int(tmdb_id) if tmdb_id else None,
                "lb_slug": slug,
                "added_at": "",
            })

        if len(films) < 28:
            break
        time.sleep(0.5)

    print(f"  Letterboxd watchlist: {len(movies)} films across {page} pages")
    return movies


def fetch_trakt_watchlist():
    """Fetch Trakt watchlist (movies + shows) via public API."""
    movies = []
    shows = []

    # Movies
    print("Fetching Trakt watchlist movies...")
    r = retry_request("get", f"{BASE}/users/{USERNAME}/watchlist/movies?extended=full",
                      headers=HEADERS, timeout=15)
    if r and r.status_code == 200:
        for item in r.json():
            m = item.get("movie", {})
            ids = m.get("ids", {})
            movies.append({
                "title": m.get("title", ""),
                "year": m.get("year"),
                "slug": ids.get("slug", ""),
                "tmdb_id": ids.get("tmdb"),
                "imdb_id": ids.get("imdb", ""),
                "runtime": m.get("runtime", 0),
                "genres": m.get("genres", []),
                "rating": round(m.get("rating", 0), 1) if m.get("rating") else None,
                "overview": (m.get("overview") or "")[:300],
                "added_at": item.get("listed_at", ""),
            })
        print(f"  Trakt movies: {len(movies)}")
    else:
        print(f"  Trakt movies failed: {r.status_code if r else 'no response'}")

    # Shows
    print("Fetching Trakt watchlist shows...")
    r = retry_request("get", f"{BASE}/users/{USERNAME}/watchlist/shows?extended=full",
                      headers=HEADERS, timeout=15)
    if r and r.status_code == 200:
        for item in r.json():
            s = item.get("show", {})
            ids = s.get("ids", {})
            shows.append({
                "title": s.get("title", ""),
                "year": s.get("year"),
                "slug": ids.get("slug", ""),
                "tmdb_id": ids.get("tmdb"),
                "imdb_id": ids.get("imdb", ""),
                "runtime": s.get("runtime", 0),  # avg episode runtime
                "genres": s.get("genres", []),
                "rating": round(s.get("rating", 0), 1) if s.get("rating") else None,
                "overview": (s.get("overview") or "")[:300],
                "status": s.get("status", ""),
                "aired_episodes": s.get("aired_episodes", 0),
                "added_at": item.get("listed_at", ""),
            })
        print(f"  Trakt shows: {len(shows)}")
    else:
        print(f"  Trakt shows failed: {r.status_code if r else 'no response'}")

    return movies, shows


def search_tmdb_movie(title, year=None):
    """Search TMDB for a movie by title + year to get TMDB ID.
    Retries without year if year-specific search returns no results."""
    if not TMDB_API_KEY or not title:
        return None
    try:
        q = urllib.request.quote(title)
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={q}"
        if year:
            url += f"&year={year}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        d = json.loads(resp.read())
        results = d.get("results", [])
        if results:
            return results[0].get("id")
        # Retry without year filter if year-specific search failed
        if year:
            url2 = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={q}"
            req2 = urllib.request.Request(url2, headers={"Accept": "application/json"})
            resp2 = urllib.request.urlopen(req2, timeout=5)
            d2 = json.loads(resp2.read())
            results2 = d2.get("results", [])
            if results2:
                return results2[0].get("id")
    except Exception as e:
        print(f"    TMDB search error for '{title}' ({year}): {e}")
    return None


def fetch_tmdb_movie(tmdb_id):
    """Fetch movie details from TMDB for poster + runtime."""
    if not TMDB_API_KEY or not tmdb_id:
        return {}
    try:
        url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={TMDB_API_KEY}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        d = json.loads(resp.read())
        return {
            "runtime": d.get("runtime", 0),
            "poster": f"https://image.tmdb.org/t/p/w342{d['poster_path']}" if d.get("poster_path") else "",
            "genres": [g["name"].lower() for g in d.get("genres", [])],
            "rating": round(d.get("vote_average", 0), 1) if d.get("vote_average") else None,
            "overview": (d.get("overview") or "")[:300],
            "imdb_id": d.get("imdb_id", ""),
        }
    except Exception:
        return {}


def fetch_tmdb_show(tmdb_id):
    """Fetch show details from TMDB for poster + runtime."""
    if not TMDB_API_KEY or not tmdb_id:
        return {}
    try:
        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={TMDB_API_KEY}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        d = json.loads(resp.read())
        runtimes = d.get("episode_run_time", [])
        return {
            "runtime": runtimes[0] if runtimes else 0,
            "poster": f"https://image.tmdb.org/t/p/w342{d['poster_path']}" if d.get("poster_path") else "",
        }
    except Exception:
        return {}


def fetch_tmdb_watch_providers(tmdb_id, media_type="movie"):
    """Fallback: fetch streaming info from TMDB Watch Providers (no prices but reliable matching)."""
    if not TMDB_API_KEY or not tmdb_id:
        return {}
    try:
        mtype = "movie" if media_type == "movie" else "tv"
        url = f"https://api.themoviedb.org/3/{mtype}/{tmdb_id}/watch/providers?api_key={TMDB_API_KEY}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        d = json.loads(resp.read())
        us = d.get("results", {}).get("US", {})
        result = {}
        if us.get("flatrate"):
            result["s"] = [{"n": p["provider_name"], "s": str(p["provider_id"]),
                           "i": f"https://image.tmdb.org/t/p/w92{p['logo_path']}" if p.get("logo_path") else ""}
                          for p in us["flatrate"][:5]]
        if us.get("rent"):
            result["r"] = [{"n": p["provider_name"], "s": str(p["provider_id"]),
                           "i": f"https://image.tmdb.org/t/p/w92{p['logo_path']}" if p.get("logo_path") else ""}
                          for p in us["rent"][:3]]
        if us.get("buy"):
            result["b"] = [{"n": p["provider_name"], "s": str(p["provider_id"]),
                           "i": f"https://image.tmdb.org/t/p/w92{p['logo_path']}" if p.get("logo_path") else ""}
                          for p in us["buy"][:3]]
        return result
    except Exception:
        return {}


def fetch_justwatch(slug, media_type="movie", tmdb_id=None):
    """Fetch streaming + rental + purchase prices from JustWatch GraphQL API."""
    jw_type = "movie" if media_type == "movie" else "tv-show"
    path = f"/us/{jw_type}/{slug}"
    try:
        body = json.dumps({"query": JW_QUERY, "variables": {"path": path}}).encode()
        req = urllib.request.Request("https://apis.justwatch.com/graphql",
                                     data=body, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        d = json.loads(resp.read())
        url_v2 = (d.get("data") or {}).get("urlV2") or {}
        node = url_v2.get("node")
        if not node:
            print(f"    JW miss for {slug} ({jw_type}), trying TMDB providers...")
            return fetch_tmdb_watch_providers(tmdb_id, media_type)
        offers = node.get("offers", [])

        stream = []  # FLATRATE
        rent = []    # RENT
        buy = []     # BUY
        seen_stream = set()
        seen_rent = set()
        seen_buy = set()

        for o in offers:
            p = o.get("package", {})
            sn = p.get("shortName", "")
            mt = o.get("monetizationType", "")
            price = o.get("retailPrice", "")
            icon = "https://images.justwatch.com" + p.get("icon", "") if p.get("icon") else ""
            name = p.get("clearName", "")

            if mt == "FLATRATE" and sn not in seen_stream:
                seen_stream.add(sn)
                stream.append({"n": name, "s": sn, "i": icon})
            elif mt == "RENT" and sn not in seen_rent:
                seen_rent.add(sn)
                entry = {"n": name, "s": sn, "i": icon}
                if price:
                    entry["p"] = price
                rent.append(entry)
            elif mt == "BUY" and sn not in seen_buy:
                seen_buy.add(sn)
                entry = {"n": name, "s": sn, "i": icon}
                if price:
                    entry["p"] = price
                buy.append(entry)

        result = {}
        if stream:
            result["s"] = stream[:5]
        if rent:
            # Sort by price (cheapest first)
            rent.sort(key=lambda x: float(str(x.get("p", "999")).replace("$", "").replace(",", "")))
            result["r"] = rent[:3]
        if buy:
            buy.sort(key=lambda x: float(str(x.get("p", "999")).replace("$", "").replace(",", "")))
            result["b"] = buy[:3]
        return result
    except Exception as e:
        print(f"    JW error for {slug}: {e}, trying TMDB providers...")
        return fetch_tmdb_watch_providers(tmdb_id, media_type)


def slugify_for_jw(title, year=None):
    """Convert a movie/show title to a JustWatch-style slug."""
    import re
    s = title.lower().strip()
    s = re.sub(r"[''']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def run():
    print("=== Watchlist Refresh ===")

    # Load existing watchlist for JW price cache + timestamps
    jw_cache = {}  # slug -> jw data
    jw_ts_cache = {}  # slug -> epoch when jw was last fetched
    existing = {"movies": [], "shows": []}
    if os.path.exists("data/watchlist.json"):
        with open("data/watchlist.json") as f:
            existing = json.load(f)
        for item in existing.get("movies", []) + existing.get("shows", []):
            if item.get("jw") and item.get("slug"):
                jw_cache[item["slug"]] = item["jw"]
                jw_ts_cache[item["slug"]] = item.get("jw_ts", 0)

    # Load poster cache for fallback
    posters = {}
    if os.path.exists("data/posters.json"):
        with open("data/posters.json") as f:
            posters = json.load(f)

    # 1. Fetch from both sources
    lb_movies = fetch_letterboxd_watchlist()
    trakt_movies, trakt_shows = fetch_trakt_watchlist()

    # 2. Deduplicate movies (Letterboxd + Trakt by TMDB ID)
    movies_by_tmdb = {}

    # Trakt movies first (they have more metadata)
    for m in trakt_movies:
        tid = m.get("tmdb_id")
        if tid:
            movies_by_tmdb[tid] = {**m, "source": "trakt"}
        else:
            # No TMDB ID — use slug as key
            movies_by_tmdb[f"slug:{m['slug']}"] = {**m, "source": "trakt"}

    # Merge Letterboxd — resolve TMDB IDs for items missing from cache
    lb_only = 0
    lb_both = 0
    lb_searched = 0
    for lb in lb_movies:
        tid = lb.get("tmdb_id")

        # If no TMDB ID from cache, search TMDB by title+year (budgeted)
        if not tid and lb_searched < 300:
            tid = search_tmdb_movie(lb["title"], lb.get("year"))
            if tid:
                lb["tmdb_id"] = tid
                lb_searched += 1
                time.sleep(0.1)

        if tid and tid in movies_by_tmdb:
            movies_by_tmdb[tid]["source"] = "both"
            lb_both += 1
        elif tid:
            # Letterboxd-only movie — needs TMDB enrichment
            movies_by_tmdb[tid] = {
                "title": lb["title"],
                "year": lb["year"],
                "tmdb_id": tid,
                "slug": lb.get("lb_slug") or slugify_for_jw(lb["title"]),
                "source": "letterboxd",
                "added_at": lb.get("added_at", ""),
                "runtime": 0,
                "genres": [],
                "rating": None,
                "overview": "",
            }
            lb_only += 1
        else:
            # No TMDB ID at all — still add with title-based slug
            key = f"lb:{lb.get('lb_slug', lb['title'])}"
            movies_by_tmdb[key] = {
                "title": lb["title"],
                "year": lb["year"],
                "tmdb_id": None,
                "slug": lb.get("lb_slug") or slugify_for_jw(lb["title"]),
                "source": "letterboxd",
                "added_at": lb.get("added_at", ""),
                "runtime": 0,
                "genres": [],
                "rating": None,
                "overview": "",
            }
            lb_only += 1

    if lb_searched:
        print(f"  TMDB search: resolved {lb_searched} LB films missing from cache")
    print(f"  Deduplication: {len(movies_by_tmdb)} unique movies ({lb_both} on both, {lb_only} LB-only)")

    # 3. Enrich movies from TMDB (runtime, poster, genres) — use cache for existing items
    # Load existing enrichment cache to avoid re-fetching
    enrich_cache = {}
    for item in existing.get("movies", []):
        if item.get("tmdb_id") and item.get("runtime"):
            enrich_cache[item["tmdb_id"]] = item

    tmdb_fetched = 0
    TMDB_BUDGET = 300  # max new TMDB lookups per run (cached after first pass)

    for key, m in movies_by_tmdb.items():
        tid = m.get("tmdb_id")
        if not tid:
            continue

        # Use enrichment cache first
        if tid in enrich_cache and not m.get("runtime"):
            cached = enrich_cache[tid]
            m["runtime"] = cached.get("runtime", 0)
            m["poster"] = cached.get("poster", "")
            m["genres"] = cached.get("genres", m.get("genres", []))
            m["rating"] = cached.get("rating", m.get("rating"))
            continue

        # Only fetch from TMDB if we need runtime/poster
        if not m.get("runtime") and tmdb_fetched < TMDB_BUDGET:
            tmdb_data = fetch_tmdb_movie(tid)
            if tmdb_data:
                m["runtime"] = tmdb_data.get("runtime", 0)
                m["poster"] = tmdb_data.get("poster", "")
                if tmdb_data.get("genres"):
                    m["genres"] = tmdb_data["genres"]
                if tmdb_data.get("rating"):
                    m["rating"] = tmdb_data["rating"]
                if tmdb_data.get("imdb_id"):
                    m["imdb_id"] = tmdb_data["imdb_id"]
                tmdb_fetched += 1
                time.sleep(0.15)

    # Fetch posters for movies that don't have them
    for key, m in movies_by_tmdb.items():
        if not m.get("poster") and m.get("tmdb_id") and TMDB_API_KEY:
            # Check poster cache first
            slug = m.get("slug", "")
            if slug and slug in posters:
                m["poster"] = posters[slug]
            elif tmdb_fetched < TMDB_BUDGET:
                tmdb_data = fetch_tmdb_movie(m["tmdb_id"])
                if tmdb_data.get("poster"):
                    m["poster"] = tmdb_data["poster"]
                    tmdb_fetched += 1
                    time.sleep(0.15)

    # Also fetch posters for shows
    for s in trakt_shows:
        slug = s.get("slug", "")
        if slug and slug in posters:
            s["poster"] = posters[slug]
        elif not s.get("poster") and s.get("tmdb_id") and TMDB_API_KEY and tmdb_fetched < 60:
            tmdb_data = fetch_tmdb_show(s["tmdb_id"])
            if tmdb_data.get("poster"):
                s["poster"] = tmdb_data["poster"]
            if tmdb_data.get("runtime") and not s.get("runtime"):
                s["runtime"] = tmdb_data["runtime"]
            tmdb_fetched += 1
            time.sleep(0.15)

    print(f"  TMDB enrichment: {tmdb_fetched} lookups")

    # 4. Fetch JustWatch prices (new items only — stale refresh in enrichment)
    jw_fetched = 0
    all_items = list(movies_by_tmdb.values()) + trakt_shows
    now = int(time.time())

    for item in all_items:
        slug = item.get("slug", "")
        if not slug:
            slug = slugify_for_jw(item.get("title", ""))
            item["slug"] = slug
        if not slug:
            continue

        # Use cache if available (stale refresh handled by refresh_jw_stale.py)
        if slug in jw_cache:
            item["jw"] = jw_cache[slug]
            item["jw_ts"] = jw_ts_cache.get(slug, 0)
            continue

        if jw_fetched >= JW_BUDGET:
            continue

        media_type = "show" if "aired_episodes" in item else "movie"
        jw_data = fetch_justwatch(slug, media_type, tmdb_id=item.get("tmdb_id"))
        item["jw"] = jw_data
        item["jw_ts"] = now
        jw_cache[slug] = jw_data
        jw_ts_cache[slug] = now
        jw_fetched += 1
        time.sleep(0.3)

    print(f"  JustWatch: {jw_fetched} new lookups, {sum(1 for i in all_items if i.get('jw'))} with data")

    # 5. Build final output
    final_movies = []
    for m in movies_by_tmdb.values():
        entry = {
            "title": m["title"],
            "year": m.get("year"),
            "slug": m.get("slug", ""),
            "tmdb_id": m.get("tmdb_id"),
            "imdb_id": m.get("imdb_id", ""),
            "poster": m.get("poster", ""),
            "runtime": m.get("runtime", 0),
            "genres": m.get("genres", [])[:3],
            "rating": m.get("rating"),
            "source": m.get("source", "trakt"),
            "added_at": (m.get("added_at") or "")[:10],
        }
        if m.get("jw"):
            entry["jw"] = m["jw"]
        if m.get("jw_ts"):
            entry["jw_ts"] = m["jw_ts"]
        final_movies.append(entry)

    # Sort by added_at desc (most recent first)
    final_movies.sort(key=lambda x: x.get("added_at") or "", reverse=True)

    final_shows = []
    for s in trakt_shows:
        entry = {
            "title": s["title"],
            "year": s.get("year"),
            "slug": s.get("slug", ""),
            "tmdb_id": s.get("tmdb_id"),
            "imdb_id": s.get("imdb_id", ""),
            "poster": s.get("poster", ""),
            "runtime": s.get("runtime", 0),
            "genres": s.get("genres", [])[:3],
            "rating": s.get("rating"),
            "status": s.get("status", ""),
            "aired_episodes": s.get("aired_episodes", 0),
            "source": "trakt",
            "added_at": (s.get("added_at") or "")[:10],
        }
        if s.get("jw"):
            entry["jw"] = s["jw"]
        if s.get("jw_ts"):
            entry["jw_ts"] = s["jw_ts"]
        final_shows.append(entry)

    final_shows.sort(key=lambda x: x.get("added_at") or "", reverse=True)

    # 6. Read custom order from Trakt personal list (if exists)
    custom_order = {}
    if CLIENT_ID:
        try:
            r = retry_request("get", f"{BASE}/users/{USERNAME}/lists", headers=HEADERS, timeout=10)
            if r and r.status_code == 200:
                for lst in r.json():
                    if lst.get("name") == "Iris Custom Order":
                        desc = lst.get("description", "")
                        if desc:
                            custom_order = json.loads(desc)
                            print(f"  Custom order: {len(custom_order.get('movies',[]))} movies, {len(custom_order.get('shows',[]))} shows")
                        break
        except Exception as e:
            print(f"  Custom order read failed: {e}")

    output = {
        "movies": final_movies,
        "shows": final_shows,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if custom_order:
        output["custom_order"] = custom_order

    os.makedirs("data", exist_ok=True)
    with open("data/watchlist.json", "w") as f:
        json.dump(output, f, separators=(",", ":"))

    # Save resolved TMDB IDs back to lb_tmdb_cache (both slug and title|year formats)
    cache_updated = 0
    for m in final_movies:
        tid = m.get("tmdb_id")
        if tid:
            slug_key = m.get("slug", "")
            title_key = f"{m.get('title', '')}|{m.get('year', '')}" if m.get("year") else ""
            if slug_key and slug_key not in lb_tmdb:
                lb_tmdb[slug_key] = tid
                cache_updated += 1
            if title_key and title_key not in lb_tmdb:
                lb_tmdb[title_key] = tid
                cache_updated += 1
    if cache_updated:
        with open("data/lb_tmdb_cache.json", "w") as f:
            json.dump(lb_tmdb, f, separators=(",", ":"))
        print(f"  Updated lb_tmdb_cache: +{cache_updated} entries ({len(lb_tmdb)} total)")

    # Stats
    movies_with_jw = sum(1 for m in final_movies if m.get("jw"))
    shows_with_jw = sum(1 for s in final_shows if s.get("jw"))
    movies_with_rt = sum(1 for m in final_movies if m.get("runtime"))
    movies_with_tmdb = sum(1 for m in final_movies if m.get("tmdb_id"))
    print(f"\n  Final: {len(final_movies)} movies ({movies_with_rt} with runtime, {movies_with_jw} with JW, {movies_with_tmdb} with TMDB ID)")
    print(f"         {len(final_shows)} shows ({shows_with_jw} with JW)")
    print(f"  Saved to data/watchlist.json")


if __name__ == "__main__":
    run()
