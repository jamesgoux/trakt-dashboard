#!/usr/bin/env python3
"""
Sync Letterboxd diary entries from Iris queue → letterboxd.com.

Reads pending rows from Supabase `letterboxd_queue`, authenticates against
Letterboxd with the user's stored credentials, resolves TMDB → Letterboxd
filmId, and POSTs to `/s/save-diary-entry`.

Invocation:
    python scripts/sync_letterboxd.py [--dry-run] [--limit N] [--user USERNAME]

Environment:
    SUPABASE_URL, SUPABASE_SERVICE_KEY      (required)
    LETTERBOXD_USER_AGENT                   (optional, default: Mozilla/5.0)

Exit codes:
    0 = success (including zero-pending no-op)
    1 = fatal error (e.g., Supabase unreachable)
"""

import argparse
import json
import os
import re
import sys
import time

# Use curl_cffi for TLS impersonation (bypasses Cloudflare)
try:
    from curl_cffi import requests
    _USE_CFFI = True
except ImportError:
    import requests
    _USE_CFFI = False

# Allow running as `python scripts/sync_letterboxd.py` from repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from supabase_config import get_admin_client  # noqa: E402

LETTERBOXD_BASE = "https://letterboxd.com"
USER_AGENT = os.environ.get(
    "LETTERBOXD_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
)
CSRF_COOKIE = "com.xk72.webparts.csrf"
USER_COOKIE = "letterboxd.signed.in.as"
FILMID_CACHE_PATH = "data/letterboxd_filmid_cache.json"
MAX_RETRIES = 3
RETRY_BACKOFF_S = 2


# ---------------------------------------------------------------------------
# filmId cache (shared across users — it's a global TMDB → Letterboxd mapping)
# ---------------------------------------------------------------------------

def _load_filmid_cache():
    if os.path.exists(FILMID_CACHE_PATH):
        try:
            with open(FILMID_CACHE_PATH) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_filmid_cache(cache):
    os.makedirs(os.path.dirname(FILMID_CACHE_PATH), exist_ok=True)
    with open(FILMID_CACHE_PATH, "w") as f:
        json.dump(cache, f, separators=(",", ":"))


_FILM_ID_RE = re.compile(r'data-film-id="(\d+)"')
_FILM_SLUG_RE = re.compile(r'/film/([a-z0-9\-]+)/', re.IGNORECASE)


def resolve_film_id(session, tmdb_id, cache):
    """Resolve TMDB movie ID → Letterboxd (filmId, slug).

    Uses the cache first. Falls back to GET /tmdb/{tmdb_id}/ which redirects
    to the canonical /film/{slug}/ page; we parse data-film-id from the HTML.
    """
    key = str(tmdb_id)
    cached = cache.get(key)
    if cached and cached.get("filmId"):
        return cached["filmId"], cached.get("slug")

    # Strategy: derive slug from title, fetch /film/{slug}/ (Cloudflare-safe when logged in)
    # /tmdb/{id}/ redirects are blocked by Cloudflare, so we avoid them
    title = cache.get(key, {}).get("title") or ""
    year = cache.get(key, {}).get("year")

    # Try multiple slug patterns
    import re as _re
    base_slug = _re.sub(r"[^a-z0-9\s\-]", "", title.lower()).strip()
    base_slug = _re.sub(r"\s+", "-", base_slug).strip("-")
    candidates = [base_slug]
    if year:
        candidates.append(f"{base_slug}-{year}")

    for slug in candidates:
        if not slug:
            continue
        r = session.get(f"{LETTERBOXD_BASE}/film/{slug}/", allow_redirects=True, timeout=15)
        if r.status_code != 200:
            continue
        id_match = _FILM_ID_RE.search(r.text)
        if id_match:
            film_id = int(id_match.group(1))
            cache[key] = {"filmId": film_id, "slug": slug, "title": title, "year": year}
            return film_id, slug

    return None, None


# ---------------------------------------------------------------------------
# Letterboxd session auth
# ---------------------------------------------------------------------------

class LetterboxdAuthError(Exception):
    """Letterboxd login failed — do not retry."""


class LetterboxdTransientError(Exception):
    """Transient failure — safe to retry."""


def make_session():
    if _USE_CFFI:
        s = requests.Session(impersonate="chrome120")
    else:
        s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def login(session, username, password):
    """Perform login, populate session cookies.

    Raises LetterboxdAuthError on bad credentials or form change.
    """
    # STEP 1 — Fetch sign-in page so the CSRF cookie is set
    r = session.get(f"{LETTERBOXD_BASE}/sign-in/", timeout=15)
    if r.status_code != 200:
        raise LetterboxdTransientError(f"sign-in page returned {r.status_code}")

    csrf = session.cookies.get(CSRF_COOKIE)
    if not csrf:
        raise LetterboxdAuthError("Missing CSRF cookie after sign-in GET")

    # STEP 2 — Submit login form
    form = {
        "__csrf": csrf,
        "username": username,
        "password": password,
        "remember": "1",
    }
    headers = {
        "Referer": f"{LETTERBOXD_BASE}/sign-in/",
        "Origin": LETTERBOXD_BASE,
    }
    r = session.post(
        f"{LETTERBOXD_BASE}/user/login.do",
        data=form,
        headers=headers,
        timeout=15,
        allow_redirects=True,
    )
    if r.status_code >= 500:
        raise LetterboxdTransientError(f"login.do returned {r.status_code}")

    # Letterboxd returns 200 with error HTML on bad creds. Detect via cookie.
    if not session.cookies.get(USER_COOKIE):
        # Try to pull a specific error from response JSON if present
        try:
            data = r.json()
            msg = data.get("messages") or data.get("result") or "unknown"
        except Exception:
            msg = "no signed-in cookie after login"
        raise LetterboxdAuthError(f"Letterboxd login failed: {msg}")


# ---------------------------------------------------------------------------
# Diary POST
# ---------------------------------------------------------------------------

def save_diary_entry(session, *, film_id, watched_date, rating_half_stars,
                     liked, review_text, tags, contains_spoilers, rewatch):
    """POST /s/save-diary-entry. Returns response JSON dict.

    Raises LetterboxdAuthError if the session died mid-run.
    Raises LetterboxdTransientError on 5xx / network error.
    """
    csrf = session.cookies.get(CSRF_COOKIE)
    if not csrf:
        raise LetterboxdAuthError("CSRF cookie vanished mid-session")

    form = {
        "__csrf": csrf,
        "filmId": str(film_id),
        "specifiedDate": "true",
        "viewingDateStr": watched_date,  # YYYY-MM-DD
        "rating": str(rating_half_stars or 0),  # 0 = no rating
        "liked": "true" if liked else "false",
        "review": review_text or "",
        "containsSpoilers": "true" if contains_spoilers else "false",
        "rewatch": "true" if rewatch else "false",
    }
    if tags:
        # Letterboxd accepts comma-separated tag string on the web form
        form["tags"] = ", ".join(tags) if isinstance(tags, list) else str(tags)

    headers = {
        "Referer": f"{LETTERBOXD_BASE}/film/",
        "Origin": LETTERBOXD_BASE,
        "X-Requested-With": "XMLHttpRequest",
    }
    r = session.post(
        f"{LETTERBOXD_BASE}/s/save-diary-entry",
        data=form,
        headers=headers,
        timeout=20,
    )

    if r.status_code in (401, 403):
        raise LetterboxdAuthError(f"save-diary-entry rejected session ({r.status_code})")
    if r.status_code >= 500:
        raise LetterboxdTransientError(f"save-diary-entry {r.status_code}")
    if r.status_code != 200:
        raise LetterboxdTransientError(
            f"save-diary-entry unexpected {r.status_code}: {r.text[:200]}"
        )

    try:
        data = r.json()
    except Exception:
        raise LetterboxdTransientError(
            f"save-diary-entry non-JSON response: {r.text[:200]}"
        )

    if not data.get("result"):
        # result=false means Letterboxd rejected the payload — treat as terminal
        raise LetterboxdTransientError(f"save-diary-entry result=false: {data}")

    return data


# ---------------------------------------------------------------------------
# Main drain loop
# ---------------------------------------------------------------------------

def sync_job(session, job, cache, *, dry_run=False):
    """Process one queue row. Returns a result dict the caller reports to Supabase."""
    tmdb_id = job.get("tmdb_id")
    if not tmdb_id:
        return {"status": "failed", "error": "tmdb_id missing — cannot resolve film"}

    # 1. Resolve filmId (may be cached on the queue row already)
    film_id = job.get("letterboxd_film_id")
    slug = job.get("film_slug")
    if not film_id:
        # Prime cache with title+year for slug derivation
        k = str(tmdb_id)
        if k not in cache:
            cache[k] = {}
        cache[k]["title"] = job.get("title") or ""
        cache[k]["year"] = job.get("year")
        film_id, slug = resolve_film_id(session, tmdb_id, cache)
        if not film_id:
            return {
                "status": "failed",
                "error": f"Could not resolve Letterboxd filmId for tmdb_id={tmdb_id}",
            }

    # 2. Format watched date
    watched_date = job.get("watched_date")
    if hasattr(watched_date, "strftime"):
        watched_date = watched_date.strftime("%Y-%m-%d")
    elif isinstance(watched_date, str) and len(watched_date) >= 10:
        watched_date = watched_date[:10]

    # 3. Tags may come back from Postgres as JSONB — already a list
    tags = job.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    payload_preview = {
        "filmId": film_id,
        "slug": slug,
        "rating": job.get("rating_half_stars"),
        "liked": job.get("liked"),
        "watched_date": watched_date,
        "tags": tags,
        "review_len": len(job.get("review_text") or ""),
    }

    if dry_run:
        print(f"  DRY-RUN: would POST {payload_preview}")
        return {
            "status": "skipped",
            "error": "dry-run",
            "letterboxd_film_id": film_id,
            "film_slug": slug,
        }

    # 4. POST
    try:
        resp = save_diary_entry(
            session,
            film_id=film_id,
            watched_date=watched_date,
            rating_half_stars=job.get("rating_half_stars"),
            liked=bool(job.get("liked")),
            review_text=job.get("review_text"),
            tags=tags,
            contains_spoilers=bool(job.get("contains_spoilers")),
            rewatch=bool(job.get("rewatch")),
        )
    except LetterboxdAuthError as e:
        return {
            "status": "auth_failed",
            "error": f"{e}",
            "letterboxd_film_id": film_id,
            "film_slug": slug,
        }
    except LetterboxdTransientError as e:
        return {
            "status": "failed",
            "error": f"{e}",
            "letterboxd_film_id": film_id,
            "film_slug": slug,
        }

    return {
        "status": "synced",
        "letterboxd_film_id": film_id,
        "film_slug": slug,
        "letterboxd_viewing_id": resp.get("viewingId"),
    }


def mark_result(client, queue_id, result):
    client.rpc(
        "update_letterboxd_sync_result",
        {
            "p_queue_id": queue_id,
            "p_status": result["status"],
            "p_error": result.get("error"),
            "p_letterboxd_film_id": result.get("letterboxd_film_id"),
            "p_film_slug": result.get("film_slug"),
            "p_letterboxd_viewing_id": result.get("letterboxd_viewing_id"),
        },
    )


def main():
    parser = argparse.ArgumentParser(description="Sync queued Iris movie logs → Letterboxd")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read queue + resolve filmIds but do not POST to Letterboxd")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max rows to process this run (default 100)")
    parser.add_argument("--user", type=str, default=None,
                        help="Restrict to a single username (debug)")
    args = parser.parse_args()

    try:
        client = get_admin_client()
    except AssertionError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    # Fetch pending jobs (already joined with decrypted creds)
    jobs = client.rpc("get_pending_letterboxd_jobs", {"p_limit": args.limit})
    if args.user:
        # Additional client-side filter: jobs return user_id; look up username
        profiles = {p["id"]: p["username"]
                    for p in client.select("profiles", {"select": "id,username"})}
        jobs = [j for j in jobs if profiles.get(j["user_id"]) == args.user]

    if not jobs:
        print("No pending Letterboxd sync jobs.")
        return 0

    print(f"=== Letterboxd sync: {len(jobs)} pending job(s) ===")

    cache = _load_filmid_cache()
    sessions = {}  # user_id → logged-in requests.Session
    counts = {"synced": 0, "failed": 0, "auth_failed": 0, "skipped": 0}

    # Group jobs by user_id so we log in once per user
    from collections import defaultdict
    by_user = defaultdict(list)
    for j in jobs:
        by_user[j["user_id"]].append(j)

    for user_id, user_jobs in by_user.items():
        username = user_jobs[0].get("lb_username")
        password = user_jobs[0].get("lb_password")
        if not username or not password:
            for job in user_jobs:
                result = {"status": "auth_failed",
                          "error": "Missing Letterboxd username or password"}
                if not args.dry_run:
                    mark_result(client, job["queue_id"], result)
                counts["auth_failed"] += 1
            continue

        # Log in
        session = make_session()
        try:
            login(session, username, password)
        except LetterboxdAuthError as e:
            print(f"  [{username}] auth failed: {e}")
            for job in user_jobs:
                if not args.dry_run:
                    mark_result(client, job["queue_id"],
                                {"status": "auth_failed", "error": str(e)})
                counts["auth_failed"] += 1
            continue
        except LetterboxdTransientError as e:
            print(f"  [{username}] transient login error: {e}")
            for job in user_jobs:
                if not args.dry_run:
                    mark_result(client, job["queue_id"],
                                {"status": "failed", "error": f"login: {e}"})
                counts["failed"] += 1
            continue

        print(f"  [{username}] logged in. Draining {len(user_jobs)} job(s)...")
        sessions[user_id] = session

        for job in user_jobs:
            qid = job["queue_id"]
            attempt = 0
            result = None
            while attempt < MAX_RETRIES:
                attempt += 1
                result = sync_job(session, job, cache, dry_run=args.dry_run)
                if result["status"] in ("synced", "skipped", "auth_failed"):
                    break
                # transient failure — back off
                print(f"    retry {attempt}/{MAX_RETRIES} after {RETRY_BACKOFF_S}s: "
                      f"{result.get('error')}")
                time.sleep(RETRY_BACKOFF_S * attempt)

            if not args.dry_run:
                mark_result(client, qid, result)
            counts[result["status"]] = counts.get(result["status"], 0) + 1
            label = result["status"]
            tmdb = job.get("tmdb_id")
            title = job.get("title") or f"tmdb:{tmdb}"
            print(f"    {label:11s}  {title}")

    _save_filmid_cache(cache)

    print()
    print(f"Done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
