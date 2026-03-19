#!/usr/bin/env python3
"""
Migrate airdate-matched episode watches to dateless on Trakt.
Removes specific history entries (by history ID) so episodes remain
"watched" but lose the fake airdate timestamp.

Rules:
- MIGRATE group: all airdate-matched episodes for pre-tracking shows
- BOUNDARY shows: only pre-2017 airdate-matched episodes
- PARTIAL: GoT S1 only, Twin Peaks original only
- User-confirmed: Mad Men, Rick and Morty, Schitt's Creek, Deadwood

Requires: TRAKT_CLIENT_ID, TRAKT_ACCESS_TOKEN env vars
"""
import os, json, sys, time, requests
from datetime import datetime, date
from collections import defaultdict

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
ACCESS_TOKEN = os.environ.get("TRAKT_ACCESS_TOKEN")
USERNAME = os.environ.get("TRAKT_USERNAME", "jamesgoux")
BASE = "https://api.trakt.tv"

def get_headers(auth=False):
    h = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": CLIENT_ID,
    }
    if auth:
        h["Authorization"] = f"Bearer {ACCESS_TOKEN}"
    return h

def fetch_all_episode_history():
    """Fetch complete episode watch history with extended info."""
    all_entries = []
    page = 1
    while True:
        url = f"{BASE}/users/{USERNAME}/history/episodes?page={page}&limit=100&extended=full"
        print(f"  Fetching page {page}...", end="", flush=True)
        resp = requests.get(url, headers=get_headers())
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", 5))
            print(f" rate limited, waiting {retry}s...", flush=True)
            time.sleep(retry)
            continue
        resp.raise_for_status()
        items = resp.json()
        total_pages = int(resp.headers.get("X-Pagination-Page-Count", 1))
        total_items = int(resp.headers.get("X-Pagination-Item-Count", 0))
        if page == 1:
            print(f" {total_items} total across {total_pages} pages", flush=True)
        all_entries.extend(items)
        print(f" got {len(items)} (total: {len(all_entries)})", flush=True)
        if page >= total_pages or not items:
            break
        page += 1
        time.sleep(0.3)
    return all_entries

# ── Shows fully in MIGRATE group ──
MIGRATE_ALL_SHOWS = {
    'The Big Bang Theory', 'Angel', 'The League', 'Cougar Town',
    'Friday Night Lights', 'Modern Family', "Bob's Burgers", 'In Treatment',
    'Frasier', 'The Legend of Korra', 'Up All Night', 'The O.C.', 'The Wire',
    'Dollhouse', 'Portlandia', 'Outsourced', 'Flight of the Conchords',
    'Studio 60 on the Sunset Strip', 'Orphan Black', 'The Walking Dead',
    'Bored to Death', 'Undeclared', 'Spaced', 'The Office', 'Selfie',
    'Battleground', 'Wilfred', 'The Increasingly Poor Decisions of Todd Margaret',
    'Lucky Louie', 'Horace and Pete', 'Making a Murderer',
    'Terminator: The Sarah Connor Chronicles', 'The Night Of',
    'Wet Hot American Summer: First Day of Camp', 'Garfunkel and Oates',
    'Quick Draw', 'Wonderfalls', 'Ballers', 'Hannibal', 'Up to Speed',
    "Dr. Horrible's Sing-Along Blog", 'Tin Man', 'Doctor Who', 'Friends',
    'Downton Abbey', 'Coupling', 'Togetherness',
    'HitRECord on TV with Joseph Gordon-Levitt', 'Fringe', 'White Collar',
    "Chef's Table", 'Superstore', 'Star Wars Rebels', 'Lovesick',
    'A Day in the Life', 'Once Upon a Time', 'Misfits',
    # User-confirmed migrate all
    'Mad Men', 'Rick and Morty', "Schitt's Creek", 'Deadwood',
}

# ── Shows to keep ALL airdate matches ──
KEEP_SHOWS = {
    'True Detective', 'Better Call Saul', 'The Good Place',
    'The Marvelous Mrs. Maisel', 'WandaVision',
}

TRACKING_CUTOFF = date(2017, 1, 1)

def identify_candidates(entries):
    """Identify episodes to migrate."""
    candidates = []
    kept = []

    for entry in entries:
        if entry.get('type') != 'episode':
            continue
        ep = entry.get('episode', {})
        show = entry.get('show', {})
        show_title = show.get('title', '')
        watched_str = entry.get('watched_at')
        aired_str = ep.get('first_aired')
        history_id = entry.get('id')
        trakt_ep_id = ep.get('ids', {}).get('trakt')

        if not watched_str or not aired_str or not history_id:
            continue
        try:
            watched_dt = datetime.fromisoformat(watched_str.replace('Z', '+00:00'))
            aired_dt = datetime.fromisoformat(aired_str.replace('Z', '+00:00'))
            watched_date = watched_dt.date()
            aired_date = aired_dt.date()
        except (ValueError, TypeError):
            continue

        # Only airdate matches
        if watched_date != aired_date:
            continue

        info = {
            'history_id': history_id,
            'trakt_ep_id': trakt_ep_id,
            'show': show_title,
            'season': ep.get('season'),
            'episode': ep.get('number'),
        }

        if show_title in KEEP_SHOWS:
            kept.append(info)
            continue
        if show_title in MIGRATE_ALL_SHOWS:
            candidates.append(info)
            continue
        # Game of Thrones: S1 only
        if show_title == 'Game of Thrones':
            if ep.get('season') == 1:
                candidates.append(info)
            else:
                kept.append(info)
            continue
        # Twin Peaks: original only
        if show_title == 'Twin Peaks':
            if aired_date < TRACKING_CUTOFF:
                candidates.append(info)
            else:
                kept.append(info)
            continue
        # All others: pre-2017 cutoff
        if aired_date < TRACKING_CUTOFF:
            candidates.append(info)
        else:
            kept.append(info)

    return candidates, kept

def remove_history(history_ids):
    """Remove history entries in batches."""
    total = len(history_ids)
    removed = 0
    failed = 0
    BATCH = 200

    for i in range(0, total, BATCH):
        batch = history_ids[i:i+BATCH]
        batch_num = i // BATCH + 1
        total_batches = (total + BATCH - 1) // BATCH

        resp = None
        for attempt in range(3):
            resp = requests.post(f"{BASE}/sync/history/remove",
                json={"ids": batch}, headers=get_headers(auth=True))
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", 10))
                print(f"    Rate limited, waiting {retry}s...", flush=True)
                time.sleep(retry)
                continue
            break

        if resp and resp.status_code == 200:
            result = resp.json()
            deleted = result.get('deleted', {}).get('episodes', 0)
            not_found = result.get('not_found', {}).get('ids', [])
            removed += deleted
            nf = len(not_found)
            failed += nf
            pct = min((i + len(batch)) / total * 100, 100)
            nf_str = f", {nf} not found" if nf else ""
            print(f"  Batch {batch_num}/{total_batches}: {deleted} removed{nf_str}  [{pct:.0f}%]", flush=True)
        else:
            status = resp.status_code if resp else "no response"
            print(f"  Batch {batch_num}/{total_batches}: HTTP {status}", flush=True)
            failed += len(batch)

        time.sleep(0.3)

    return removed, failed

def readd_without_dates(trakt_ep_ids):
    """Re-add episodes as dateless watches (no watched_at = Trakt 'unknown date')."""
    total = len(trakt_ep_ids)
    added = 0
    failed = 0
    BATCH = 200

    for i in range(0, total, BATCH):
        batch = trakt_ep_ids[i:i+BATCH]
        batch_num = i // BATCH + 1
        total_batches = (total + BATCH - 1) // BATCH

        body = {"episodes": [{"ids": {"trakt": tid}} for tid in batch]}

        resp = None
        for attempt in range(3):
            resp = requests.post(f"{BASE}/sync/history",
                json=body, headers=get_headers(auth=True))
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", 10))
                print(f"    Rate limited, waiting {retry}s...", flush=True)
                time.sleep(retry)
                continue
            break

        if resp and resp.status_code == 201:
            result = resp.json()
            n = result.get('added', {}).get('episodes', 0)
            nf = len(result.get('not_found', {}).get('episodes', []))
            added += n
            failed += nf
            pct = min((i + len(batch)) / total * 100, 100)
            nf_str = f", {nf} not found" if nf else ""
            print(f"  Batch {batch_num}/{total_batches}: {n} re-added{nf_str}  [{pct:.0f}%]", flush=True)
        else:
            status = resp.status_code if resp else "no response"
            print(f"  Batch {batch_num}/{total_batches}: HTTP {status}", flush=True)
            failed += len(batch)

        time.sleep(0.3)

    return added, failed

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in ("--dry-run", "--execute"):
        print("Usage: python migrate_airdate_watches.py [--dry-run|--execute]")
        sys.exit(1)

    is_dry = mode == "--dry-run"
    print(f"=== Trakt Airdate Watch Migration ({'DRY RUN' if is_dry else 'EXECUTE'}) ===\n")

    if not CLIENT_ID:
        print("ERROR: TRAKT_CLIENT_ID not set"); sys.exit(1)
    if not is_dry and not ACCESS_TOKEN:
        print("ERROR: TRAKT_ACCESS_TOKEN not set"); sys.exit(1)

    # Verify auth for execute mode
    if not is_dry:
        resp = requests.get(f"{BASE}/users/me", headers=get_headers(auth=True))
        if resp.status_code != 200:
            print(f"ERROR: Auth failed (HTTP {resp.status_code})"); sys.exit(1)
        print(f"Authenticated as: {resp.json().get('username')}\n")

    print("Fetching episode history from Trakt API...")
    entries = fetch_all_episode_history()

    print("\nIdentifying migration candidates...")
    candidates, kept = identify_candidates(entries)

    by_show = defaultdict(list)
    for c in candidates:
        by_show[c['show']].append(c)

    print(f"\n{'='*60}")
    print(f"Episodes to migrate: {len(candidates):,}")
    print(f"Episodes kept:       {len(kept):,}")
    print(f"Shows affected:      {len(by_show)}")
    print(f"{'='*60}")
    for show in sorted(by_show, key=lambda x: len(by_show[x]), reverse=True):
        eps = by_show[show]
        seasons = sorted(set(e['season'] for e in eps if e['season'] is not None))
        s_str = f"  S{','.join(str(s) for s in seasons)}" if len(seasons) <= 5 else f"  S{seasons[0]}-{seasons[-1]}"
        print(f"  {show:45s} {len(eps):4d} eps{s_str}")
    print(f"  {'TOTAL':45s} {len(candidates):4d}")

    # Show KEEP summary too
    if kept:
        kept_by_show = defaultdict(int)
        for k in kept:
            kept_by_show[k['show']] += 1
        print(f"\nKEPT (airdate matches preserved):")
        for show in sorted(kept_by_show, key=lambda x: kept_by_show[x], reverse=True):
            print(f"  {show:45s} {kept_by_show[show]:4d} eps")

    if is_dry:
        print(f"\nDRY RUN complete. Run with --execute to migrate.")
        print(f"Migration will: remove {len(candidates):,} dated entries → re-add as dateless watches.")
        return

    # Check for missing trakt episode IDs
    missing_ids = [c for c in candidates if not c.get('trakt_ep_id')]
    if missing_ids:
        print(f"\nWARNING: {len(missing_ids)} candidates missing trakt episode ID — these will be removed but NOT re-added!")
        for m in missing_ids[:10]:
            print(f"  {m['show']} S{m['season']:02d}E{m['episode']:02d}")

    # Step 1: Remove dated history entries
    print(f"\nStep 1: Removing {len(candidates):,} dated history entries...")
    history_ids = [c['history_id'] for c in candidates]
    removed, remove_failed = remove_history(history_ids)
    print(f"  Removed: {removed:,}, Failed: {remove_failed:,}")

    # Step 2: Re-add as dateless watches
    trakt_ep_ids = [c['trakt_ep_id'] for c in candidates if c.get('trakt_ep_id')]
    # Deduplicate (same episode watched multiple times → only re-add once)
    unique_ep_ids = list(dict.fromkeys(trakt_ep_ids))
    print(f"\nStep 2: Re-adding {len(unique_ep_ids):,} unique episodes as dateless watches...")
    added, add_failed = readd_without_dates(unique_ep_ids)
    print(f"  Re-added: {added:,}, Failed: {add_failed:,}")

    print(f"\n{'='*60}")
    print(f"MIGRATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Dated entries removed:   {removed:,}")
    print(f"  Dateless watches added:  {added:,}")
    print(f"  Remove failures:         {remove_failed:,}")
    print(f"  Re-add failures:         {add_failed:,}")

if __name__ == "__main__":
    main()
