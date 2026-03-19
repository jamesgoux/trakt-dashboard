#!/usr/bin/env python3
"""
Restore removed episodes as dateless watches on Trakt.
Re-adds episodes using epoch timestamp (1970-01-01T00:00:00.000Z)
which is Trakt's convention for dateless watches.

Reads candidate list from data/migration_candidates.json.
Requires: TRAKT_CLIENT_ID, TRAKT_ACCESS_TOKEN env vars.
"""
import os, json, sys, time, requests
from collections import defaultdict

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID")
ACCESS_TOKEN = os.environ.get("TRAKT_ACCESS_TOKEN")
BASE = "https://api.trakt.tv"

HEADERS = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
    "trakt-api-key": CLIENT_ID,
    "Authorization": f"Bearer {ACCESS_TOKEN}",
}

EPOCH = "1970-01-01T00:00:00.000Z"

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in ("--dry-run", "--execute"):
        print("Usage: python restore_dateless_watches.py [--dry-run|--execute]")
        sys.exit(1)

    is_dry = mode == "--dry-run"
    print(f"=== Restore Dateless Watches ({'DRY RUN' if is_dry else 'EXECUTE'}) ===\n")

    if not CLIENT_ID:
        print("ERROR: TRAKT_CLIENT_ID not set"); sys.exit(1)
    if not is_dry and not ACCESS_TOKEN:
        print("ERROR: TRAKT_ACCESS_TOKEN not set"); sys.exit(1)

    # Verify auth
    if not is_dry:
        resp = requests.get(f"{BASE}/users/me", headers=HEADERS)
        if resp.status_code != 200:
            print(f"ERROR: Auth failed (HTTP {resp.status_code})"); sys.exit(1)
        print(f"Authenticated as: {resp.json().get('username')}\n")

    # Load candidates
    with open("data/migration_candidates.json") as f:
        data = json.load(f)

    candidates = data["candidates"]
    print(f"Episodes to restore: {len(candidates):,} across {data['shows']} shows\n")

    # Group by show for summary
    by_show = defaultdict(list)
    for c in candidates:
        by_show[c["show"]].append(c)

    for show in sorted(by_show, key=lambda x: len(by_show[x]), reverse=True)[:20]:
        print(f"  {show:50s} {len(by_show[show]):4d}")
    if len(by_show) > 20:
        remaining = sum(len(v) for k, v in by_show.items()
                       if k not in sorted(by_show, key=lambda x: len(by_show[x]), reverse=True)[:20])
        print(f"  {'... and ' + str(len(by_show)-20) + ' more shows':50s} {remaining:4d}")
    print(f"  {'TOTAL':50s} {len(candidates):4d}")

    if is_dry:
        print(f"\nDRY RUN complete. Run with --execute to restore.")
        return

    # Build episode list for sync/history endpoint
    # Group into batches — Trakt accepts up to ~500 items per call
    BATCH = 200
    total_added = 0
    total_failed = 0

    for i in range(0, len(candidates), BATCH):
        batch = candidates[i:i+BATCH]
        batch_num = i // BATCH + 1
        total_batches = (len(candidates) + BATCH - 1) // BATCH

        # Build payload: episodes with epoch timestamp
        episodes = []
        for c in batch:
            ep = {"ids": {"trakt": c["episode_trakt_id"]}, "watched_at": EPOCH}
            episodes.append(ep)

        payload = {"episodes": episodes}

        for attempt in range(3):
            resp = requests.post(f"{BASE}/sync/history",
                json=payload, headers=HEADERS)
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", 10))
                print(f"    Rate limited, waiting {retry}s...", flush=True)
                time.sleep(retry)
                continue
            break

        if resp.status_code == 201:
            result = resp.json()
            added = result.get("added", {}).get("episodes", 0)
            not_found = result.get("not_found", {}).get("episodes", [])
            total_added += added
            nf = len(not_found)
            total_failed += nf
            pct = min((i + len(batch)) / len(candidates) * 100, 100)
            nf_str = f", {nf} not found" if nf else ""
            print(f"  Batch {batch_num}/{total_batches}: {added} added{nf_str}  [{pct:.0f}%]", flush=True)
        else:
            print(f"  Batch {batch_num}/{total_batches}: HTTP {resp.status_code} — {resp.text[:200]}", flush=True)
            total_failed += len(batch)

        time.sleep(0.3)

    print(f"\n{'='*60}")
    print(f"RESTORE COMPLETE")
    print(f"{'='*60}")
    print(f"  Added:  {total_added:,}")
    print(f"  Failed: {total_failed:,}")
    print(f"\nEpisodes restored as dateless watches (epoch timestamp).")


if __name__ == "__main__":
    main()
