#!/usr/bin/env python3
"""
Sync Serializd season-finale reviews from Iris queue → serializd.com.

Reads pending rows from Supabase `serializd_queue`, authenticates against
Serializd with the user's stored credentials, resolves TMDB season number
→ Serializd season_id, and POSTs to `/api/show/reviews/add`.

Invocation:
    python scripts/sync_serializd.py [--dry-run] [--limit N] [--user USERNAME]

Environment:
    SUPABASE_URL, SUPABASE_SERVICE_KEY      (required)

Exit codes:
    0 = success (including zero-pending no-op)
    1 = fatal error
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from supabase_config import get_admin_client  # noqa: E402

BASE = "https://www.serializd.com/api"
HEADERS = {
    "Origin": "https://www.serializd.com",
    "Referer": "https://www.serializd.com",
    "X-Requested-With": "serializd_vercel",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
MAX_RETRIES = 3
RETRY_BACKOFF_S = 2

# Local season-id cache: tmdb_show_id → {season_number: serializd_season_id}
SEASON_CACHE_PATH = "data/serializd_season_cache.json"


class SerializdAuthError(Exception):
    """Login failed — don't retry."""


class SerializdTransientError(Exception):
    """Transient failure — safe to retry."""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _load_season_cache():
    """Bootstrap from existing serializd.json if the dedicated cache is missing."""
    if os.path.exists(SEASON_CACHE_PATH):
        try:
            with open(SEASON_CACHE_PATH) as f:
                return json.load(f)
        except Exception:
            pass

    # Bootstrap from data/serializd.json (which refresh_serializd.py populates)
    cache = {}
    if os.path.exists("data/serializd.json"):
        try:
            with open("data/serializd.json") as f:
                sz = json.load(f)
            for show_id, info in sz.items():
                seasons = info.get("seasons") or {}
                # seasons is {season_id: season_number}; invert to season_number → season_id
                show_map = {}
                for sid, snum in seasons.items():
                    try:
                        show_map[str(int(snum))] = int(sid)
                    except (ValueError, TypeError):
                        continue
                if show_map:
                    cache[str(show_id)] = show_map
        except Exception:
            pass
    return cache


def _save_season_cache(cache):
    os.makedirs(os.path.dirname(SEASON_CACHE_PATH), exist_ok=True)
    with open(SEASON_CACHE_PATH, "w") as f:
        json.dump(cache, f, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def make_session(email, password):
    """Log in and return a session with the auth cookie set."""
    s = requests.Session()
    s.headers.update(HEADERS)

    r = s.post(f"{BASE}/login",
               data=json.dumps({"email": email, "password": password}),
               timeout=15)
    if r.status_code == 401 or r.status_code == 403:
        raise SerializdAuthError(f"login rejected ({r.status_code})")
    if r.status_code >= 500:
        raise SerializdTransientError(f"login 5xx {r.status_code}")
    if r.status_code != 200:
        raise SerializdAuthError(f"login unexpected {r.status_code}: {r.text[:200]}")

    try:
        data = r.json()
    except Exception:
        raise SerializdAuthError(f"login non-JSON: {r.text[:200]}")

    token = data.get("token")
    if not token:
        raise SerializdAuthError(f"login no token in response: {data}")

    s.cookies.set("tvproject_credentials", token, domain=".serializd.com")
    return s, data.get("username")


# ---------------------------------------------------------------------------
# Season ID resolution
# ---------------------------------------------------------------------------

def resolve_season_id(session, tmdb_show_id, season_number, cache):
    key = str(tmdb_show_id)
    snum_key = str(season_number)
    show_map = cache.get(key, {})
    if snum_key in show_map:
        return show_map[snum_key]

    r = session.get(f"{BASE}/show/{tmdb_show_id}", timeout=15)
    if r.status_code != 200:
        raise SerializdTransientError(
            f"show lookup {tmdb_show_id} returned {r.status_code}"
        )
    try:
        data = r.json()
    except Exception:
        raise SerializdTransientError(
            f"show lookup {tmdb_show_id} non-JSON"
        )

    seasons = data.get("seasons") or []
    show_map = {}
    match = None
    for s in seasons:
        sid = s.get("id")
        snum = s.get("seasonNumber")
        if sid is None or snum is None:
            continue
        show_map[str(snum)] = sid
        if snum == season_number:
            match = sid

    if show_map:
        cache[key] = show_map
    if match is None:
        raise SerializdTransientError(
            f"season {season_number} not found for show {tmdb_show_id}"
        )
    return match


# ---------------------------------------------------------------------------
# Review POST
# ---------------------------------------------------------------------------

def post_review(session, *, show_id, season_id, rating_half_stars, liked,
                review_text, tags, contains_spoilers, is_rewatch, watched_at):
    """POST /api/show/reviews/add — schema matches production bundle extraction.

    rating_half_stars is 1–10 (half-star); 0 means "no rating" — we still POST
    (review-only) but Serializd may reject rating=0, so callers should decide
    whether to skip based on that.
    """
    tags_arr = tags if isinstance(tags, list) else (
        json.loads(tags) if isinstance(tags, str) and tags else []
    )

    # Convert watched_at to ISO 8601 if it's a datetime/string
    backdate = None
    if watched_at:
        if hasattr(watched_at, "isoformat"):
            backdate = watched_at.isoformat()
        elif isinstance(watched_at, str):
            backdate = watched_at

    payload = {
        "show_id": int(show_id),
        "season_id": int(season_id),
        "review_text": review_text or "",
        "rating": int(rating_half_stars) if rating_half_stars else 0,
        "contains_spoiler": bool(contains_spoilers),
        "backdate": backdate,
        "is_log": False,           # false = review row (not log-only)
        "is_rewatch": bool(is_rewatch),
        "episode_number": None,    # season-level
        "tags": tags_arr,
        "allows_comments": True,
        "like": bool(liked),
    }

    r = session.post(f"{BASE}/show/reviews/add",
                     data=json.dumps(payload), timeout=20)
    if r.status_code in (401, 403):
        raise SerializdAuthError(f"reviews/add rejected session ({r.status_code})")
    if r.status_code >= 500:
        raise SerializdTransientError(f"reviews/add {r.status_code}")
    if r.status_code != 200:
        raise SerializdTransientError(
            f"reviews/add unexpected {r.status_code}: {r.text[:200]}"
        )

    try:
        data = r.json()
    except Exception:
        raise SerializdTransientError(
            f"reviews/add non-JSON response: {r.text[:200]}"
        )
    return data


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def sync_job(session, job, cache, *, dry_run=False):
    tmdb_show_id = job.get("tmdb_show_id")
    season_number = job.get("season_number")

    season_id = job.get("serializd_season_id")
    if not season_id:
        try:
            season_id = resolve_season_id(session, tmdb_show_id, season_number, cache)
        except SerializdAuthError as e:
            return {"status": "auth_failed", "error": f"{e}"}
        except SerializdTransientError as e:
            return {"status": "failed", "error": f"{e}"}

    payload_preview = {
        "show_id": tmdb_show_id,
        "season_id": season_id,
        "season_number": season_number,
        "rating": job.get("rating_half_stars"),
        "liked": job.get("liked"),
        "tags_count": len(job.get("tags") or []),
        "review_len": len(job.get("review_text") or ""),
        "watched_at": str(job.get("watched_at")),
    }

    if dry_run:
        print(f"  DRY-RUN: would POST {payload_preview}")
        return {"status": "skipped", "error": "dry-run",
                "serializd_season_id": season_id}

    try:
        resp = post_review(
            session,
            show_id=tmdb_show_id,
            season_id=season_id,
            rating_half_stars=job.get("rating_half_stars"),
            liked=bool(job.get("liked")),
            review_text=job.get("review_text"),
            tags=job.get("tags"),
            contains_spoilers=bool(job.get("contains_spoilers")),
            is_rewatch=bool(job.get("is_rewatch")),
            watched_at=job.get("watched_at"),
        )
    except SerializdAuthError as e:
        return {"status": "auth_failed", "error": f"{e}",
                "serializd_season_id": season_id}
    except SerializdTransientError as e:
        return {"status": "failed", "error": f"{e}",
                "serializd_season_id": season_id}

    return {
        "status": "synced",
        "serializd_season_id": season_id,
        "serializd_review_id": resp.get("review_id") or resp.get("id"),
    }


def mark_result(client, queue_id, result):
    client.rpc(
        "update_serializd_sync_result",
        {
            "p_queue_id": queue_id,
            "p_status": result["status"],
            "p_error": result.get("error"),
            "p_serializd_season_id": result.get("serializd_season_id"),
            "p_serializd_review_id": result.get("serializd_review_id"),
        },
    )


def main():
    parser = argparse.ArgumentParser(description="Sync queued Iris season finales → Serializd")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read queue + resolve season_ids but do not POST")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--user", type=str, default=None)
    args = parser.parse_args()

    try:
        client = get_admin_client()
    except AssertionError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    jobs = client.rpc("get_pending_serializd_jobs", {"p_limit": args.limit})
    if args.user:
        profiles = {p["id"]: p["username"]
                    for p in client.select("profiles", {"select": "id,username"})}
        jobs = [j for j in jobs if profiles.get(j["user_id"]) == args.user]

    if not jobs:
        print("No pending Serializd sync jobs.")
        return 0

    print(f"=== Serializd sync: {len(jobs)} pending job(s) ===")

    cache = _load_season_cache()
    counts = {"synced": 0, "failed": 0, "auth_failed": 0, "skipped": 0}

    by_user = defaultdict(list)
    for j in jobs:
        by_user[j["user_id"]].append(j)

    for user_id, user_jobs in by_user.items():
        email = user_jobs[0].get("sz_email")
        password = user_jobs[0].get("sz_password")
        if not email or not password:
            for job in user_jobs:
                result = {"status": "auth_failed",
                          "error": "Missing Serializd email or password"}
                if not args.dry_run:
                    mark_result(client, job["queue_id"], result)
                counts["auth_failed"] += 1
            continue

        try:
            session, username = make_session(email, password)
        except SerializdAuthError as e:
            print(f"  [{email}] auth failed: {e}")
            for job in user_jobs:
                if not args.dry_run:
                    mark_result(client, job["queue_id"],
                                {"status": "auth_failed", "error": str(e)})
                counts["auth_failed"] += 1
            continue
        except SerializdTransientError as e:
            print(f"  [{email}] transient login error: {e}")
            for job in user_jobs:
                if not args.dry_run:
                    mark_result(client, job["queue_id"],
                                {"status": "failed", "error": f"login: {e}"})
                counts["failed"] += 1
            continue

        print(f"  [{username or email}] logged in. Draining {len(user_jobs)} job(s)...")

        for job in user_jobs:
            qid = job["queue_id"]
            attempt = 0
            result = None
            while attempt < MAX_RETRIES:
                attempt += 1
                result = sync_job(session, job, cache, dry_run=args.dry_run)
                if result["status"] in ("synced", "skipped", "auth_failed"):
                    break
                print(f"    retry {attempt}/{MAX_RETRIES} after {RETRY_BACKOFF_S}s: "
                      f"{result.get('error')}")
                time.sleep(RETRY_BACKOFF_S * attempt)

            if not args.dry_run:
                mark_result(client, qid, result)
            counts[result["status"]] = counts.get(result["status"], 0) + 1
            title = job.get("show_title") or f"tmdb:{job.get('tmdb_show_id')}"
            print(f"    {result['status']:11s}  {title} S{job.get('season_number')}")

    _save_season_cache(cache)

    print()
    print(f"Done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main(main())
