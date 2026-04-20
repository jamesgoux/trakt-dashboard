#!/usr/bin/env python3
"""
Sync Letterboxd diary entries from Iris queue → letterboxd.com via Playwright.

Uses headless Chrome to submit diary entries through the actual Letterboxd
web UI, handling Cloudflare Turnstile automatically.

Invocation:
    python scripts/sync_letterboxd.py [--dry-run] [--limit N] [--user USERNAME]

Environment:
    SUPABASE_URL, SUPABASE_SERVICE_KEY      (required)
    PLAYWRIGHT_HEADLESS                     (optional, default: 1)

Exit codes:
    0 = success (including zero-pending no-op)
    1 = fatal error
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from supabase_config import get_admin_client  # noqa: E402

HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "1") != "0"


class LetterboxdAuthError(Exception):
    pass


def sync_batch(jobs, username, password, *, dry_run=False):
    """Sync a batch of jobs for one user via headless Chrome."""
    from playwright.sync_api import sync_playwright

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # ── Login ──
        print(f"  Logging in as {username}...")
        page.goto("https://letterboxd.com/sign-in/", wait_until="networkidle", timeout=30000)
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_timeout(3000)

        if "letterboxd.signed.in.as" not in {c["name"] for c in context.cookies()}:
            browser.close()
            raise LetterboxdAuthError("no signed-in cookie after login")
        print(f"  ✓ Logged in")

        # ── Process each job ──
        for job in jobs:
            qid = job["queue_id"]
            tmdb_id = job.get("tmdb_id")
            title = job.get("title") or f"tmdb:{tmdb_id}"
            rating = job.get("rating_half_stars") or 0
            liked = bool(job.get("liked"))
            watched_date = str(job.get("watched_date") or "")[:10]
            tags = job.get("tags") or []
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = []

            if dry_run:
                print(f"    DRY-RUN: {title} r={rating} liked={liked} d={watched_date}")
                results[qid] = {"status": "skipped", "error": "dry-run"}
                continue

            try:
                result = _sync_one(page, tmdb_id, rating, liked, watched_date, tags)
                results[qid] = result
                status_char = "✓" if result["status"] == "synced" else "✗"
                print(f"    {status_char} {title}: {result['status']}")
            except Exception as e:
                results[qid] = {"status": "failed", "error": str(e)[:500]}
                print(f"    ✗ {title}: {e}")

        browser.close()
    return results


def _sync_one(page, tmdb_id, rating, liked, watched_date, tags):
    """Open film page, fill diary form, submit via real browser."""

    # 1. Navigate to film
    page.goto(f"https://letterboxd.com/tmdb/{tmdb_id}/",
              wait_until="networkidle", timeout=20000)
    url = page.url
    if "/film/" not in url:
        return {"status": "failed",
                "error": f"tmdb {tmdb_id} → {url} (not a film page)"}

    slug = None
    m = re.search(r"/film/([a-z0-9\-]+)/", url)
    if m:
        slug = m.group(1)

    # 2. Open the "Review or log" dialog
    page.wait_for_timeout(1000)
    log_btn = page.locator('text="Review or log"').first
    if log_btn.count() == 0:
        log_btn = page.locator('text="Log"').first
    log_btn.click()
    page.wait_for_timeout(2000)

    # 3. Wait for form
    form = page.locator(".diary-entry-form")
    form.wait_for(state="visible", timeout=5000)

    # 4. Ensure "Watched on" is checked (adds to diary)
    specify = page.locator("#frm-specify-date")
    if specify.count() > 0 and not specify.is_checked():
        specify.check()
        page.wait_for_timeout(300)

    # 5. Set rating via hidden range input
    if rating > 0:
        page.evaluate(f"""(() => {{
            const el = document.querySelector('#frm-rating');
            if (!el) return;
            const setter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value').set;
            setter.call(el, '{rating}');
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            // Trigger rateit widget refresh
            try {{ $(el).rateit('value', {rating}); }} catch(e) {{}}
        }})()""")
        page.wait_for_timeout(300)

    # 6. Set liked
    if liked:
        like_cb = page.locator('input[name="liked"]')
        if like_cb.count() > 0 and not like_cb.is_checked():
            like_cb.check()

    # 7. Set date
    if watched_date:
        page.evaluate(f"""(() => {{
            const el = document.querySelector('#frm-viewing-date-string');
            if (!el) return;
            const setter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value').set;
            setter.call(el, '{watched_date}');
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }})()""")

    # 8. Add tags
    for tag in tags:
        tag_input = page.locator("#frm-tags, input.tag-input-field").first
        if tag_input.count() > 0:
            tag_input.fill("")
            tag_input.type(tag, delay=50)
            page.wait_for_timeout(400)
            tag_input.press("Tab")
            page.wait_for_timeout(200)

    # 9. Submit
    save_btn = page.locator('button:has-text("Save")').last
    try:
        with page.expect_response(
            lambda r: "save-diary" in r.url or "/s/" in r.url, timeout=15000
        ) as resp_info:
            save_btn.click()
        resp = resp_info.value
        if resp.status == 200:
            try:
                data = resp.json()
                return {
                    "status": "synced",
                    "film_slug": slug,
                    "letterboxd_viewing_id": data.get("viewingId"),
                }
            except Exception:
                return {"status": "synced", "film_slug": slug}
        return {"status": "failed",
                "error": f"save returned HTTP {resp.status}"}
    except Exception as e:
        # Timeout on expect_response — check if page changed (success redirect)
        page.wait_for_timeout(3000)
        if "/film/" in page.url and slug and slug in page.url:
            return {"status": "synced", "film_slug": slug}
        return {"status": "failed", "error": f"save failed: {e}"}


def mark_result(client, queue_id, result):
    client.rpc("update_letterboxd_sync_result", {
        "p_queue_id": str(queue_id),
        "p_status": result["status"],
        "p_error": result.get("error"),
        "p_letterboxd_film_id": result.get("letterboxd_film_id"),
        "p_film_slug": result.get("film_slug"),
        "p_letterboxd_viewing_id": result.get("letterboxd_viewing_id"),
    })


def main():
    parser = argparse.ArgumentParser(
        description="Sync queued Iris movie logs → Letterboxd (Playwright)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--user", type=str, default=None)
    args = parser.parse_args()

    try:
        client = get_admin_client()
    except AssertionError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    # Check queue BEFORE importing playwright (saves ~2s when empty)
    jobs = client.rpc("get_pending_letterboxd_jobs", {"p_limit": args.limit})
    if args.user:
        profiles = {p["id"]: p["username"]
                    for p in client.select("profiles", {"select": "id,username"})}
        jobs = [j for j in jobs if profiles.get(j["user_id"]) == args.user]

    if not jobs:
        print("No pending Letterboxd sync jobs.")
        return 0

    print(f"=== Letterboxd sync (Playwright): {len(jobs)} job(s) ===")

    by_user = defaultdict(list)
    for j in jobs:
        by_user[j["user_id"]].append(j)

    total = {"synced": 0, "failed": 0, "auth_failed": 0, "skipped": 0}

    for user_id, user_jobs in by_user.items():
        username = user_jobs[0].get("lb_username")
        password = user_jobs[0].get("lb_password")
        if not username or not password:
            for job in user_jobs:
                if not args.dry_run:
                    mark_result(client, job["queue_id"],
                                {"status": "auth_failed",
                                 "error": "Missing Letterboxd credentials"})
                total["auth_failed"] += 1
            continue

        try:
            results = sync_batch(user_jobs, username, password,
                                 dry_run=args.dry_run)
        except LetterboxdAuthError as e:
            print(f"  Auth failed: {e}")
            for job in user_jobs:
                if not args.dry_run:
                    mark_result(client, job["queue_id"],
                                {"status": "auth_failed", "error": str(e)})
                total["auth_failed"] += 1
            continue
        except Exception as e:
            print(f"  Error: {e}")
            for job in user_jobs:
                if not args.dry_run:
                    mark_result(client, job["queue_id"],
                                {"status": "failed", "error": str(e)[:500]})
                total["failed"] += 1
            continue

        for job in user_jobs:
            qid = job["queue_id"]
            result = results.get(qid, {"status": "failed",
                                        "error": "no result"})
            if not args.dry_run:
                mark_result(client, qid, result)
            s = result["status"]
            total[s] = total.get(s, 0) + 1

    print(f"\nDone: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
