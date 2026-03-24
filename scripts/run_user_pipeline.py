#!/usr/bin/env python3
"""
Iris Per-User Pipeline Orchestrator

Runs the full data pipeline for a specific user, loading their credentials
from Supabase and outputting to both local files and Supabase Storage.

Usage:
    python3 scripts/run_user_pipeline.py --user=jamesgoux
    python3 scripts/run_user_pipeline.py --user=jamesgoux --dry-run
    python3 scripts/run_user_pipeline.py --user=jamesgoux --target=staging
"""

import sys, os, json, time, subprocess, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from user_config import load_user_config, get_service, upload_user_data

# Pipeline steps in execution order
# Each step: (script_name, required_service, description)
PIPELINE_STEPS = [
    ("refresh_trakt_token.py", "trakt", "Refresh Trakt OAuth token"),
    ("refresh_data.py", "trakt", "Trakt watch history + build dashboard"),
    ("refresh_letterboxd.py", "letterboxd", "Letterboxd diary + ratings"),
    ("refresh_goodreads.py", "goodreads", "Goodreads reading data"),
    ("refresh_lastfm.py", "lastfm", "Last.fm scrobbles"),
    ("refresh_pocketcasts.py", "pocketcasts", "Pocket Casts episodes"),
    ("refresh_serializd.py", "serializd", "Serializd TV ratings"),
    ("refresh_setlist.py", "setlistfm", "setlist.fm concerts"),
    ("refresh_boardgames.py", "bgg", "BoardGameGeek plays"),
    ("refresh_health.py", "health", "Apple Health workouts"),
    ("refresh_upnext.py", "trakt", "Up Next episodes"),
    ("refresh_upcoming.py", "trakt", "Upcoming calendar"),
    ("refresh_watchlist.py", "trakt", "Watchlist + JustWatch"),
    ("refresh_sports_schedule.py", None, "Sports schedule cache"),
]


def run_pipeline(username, dry_run=False, target="staging"):
    print(f"\n{'='*60}")
    print(f"  Iris Pipeline: {username}")
    print(f"  Target: {target} | Dry run: {dry_run}")
    print(f"{'='*60}\n")

    # Load user config
    config = load_user_config(username)
    if not config:
        print(f"ERROR: Could not load config for user '{username}'")
        return False

    user_id = config.get("_user_id")
    print(f"  User: {config.get('_username')} (uid: {user_id[:8] if user_id else 'env-mode'}...)")
    print(f"  Timezone: {config.get('_timezone', 'unknown')}")
    print()

    # Check which services are enabled
    enabled = []
    skipped = []
    for script, svc, desc in PIPELINE_STEPS:
        if svc is None:
            enabled.append((script, svc, desc))
        elif svc in config and config[svc]:
            # Check if service has meaningful config
            cfg = config[svc]
            has_creds = any(v for k, v in cfg.items() if k not in ("tracked_teams",))
            if has_creds or svc == "sports":
                enabled.append((script, svc, desc))
            else:
                skipped.append((script, svc, desc, "no credentials"))
        else:
            skipped.append((script, svc, desc, "not configured"))

    print(f"  Enabled: {len(enabled)} steps")
    for s, _, d in enabled:
        print(f"    ✓ {d}")
    if skipped:
        print(f"  Skipped: {len(skipped)} steps")
        for s, _, d, reason in skipped:
            print(f"    · {d} ({reason})")
    print()

    if dry_run:
        print("  DRY RUN — no scripts will be executed.")
        print(f"  Would run {len(enabled)} steps for {username}")
        return True

    # Execute pipeline
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    results = []
    total_start = time.time()

    for script, svc, desc in enabled:
        script_path = os.path.join(scripts_dir, script)
        if not os.path.exists(script_path):
            print(f"  SKIP {script} (file not found)")
            results.append((script, "skipped", 0))
            continue

        print(f"  ▶ {desc} ({script})...")
        start = time.time()
        try:
            # Pass --user to each script
            cmd = [sys.executable, script_path, f"--user={username}"]
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=600,
                cwd=os.path.dirname(scripts_dir),  # repo root
                env={**os.environ, "IRIS_PIPELINE_USER": username},
            )
            elapsed = time.time() - start

            if result.returncode == 0:
                print(f"    ✓ {desc} ({elapsed:.1f}s)")
                results.append((script, "success", elapsed))
            else:
                print(f"    ✗ {desc} (exit {result.returncode}, {elapsed:.1f}s)")
                if result.stderr:
                    print(f"      {result.stderr[:200]}")
                results.append((script, "failed", elapsed))
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            print(f"    ⏰ {desc} (timeout after {elapsed:.0f}s)")
            results.append((script, "timeout", elapsed))
        except Exception as e:
            elapsed = time.time() - start
            print(f"    ✗ {desc} (error: {e})")
            results.append((script, "error", elapsed))

    total_elapsed = time.time() - total_start

    # Summary
    print(f"\n{'='*60}")
    print(f"  Pipeline complete: {total_elapsed:.1f}s")
    succeeded = sum(1 for _, s, _ in results if s == "success")
    failed = sum(1 for _, s, _ in results if s in ("failed", "error", "timeout"))
    print(f"  Results: {succeeded} succeeded, {failed} failed, {len(results) - succeeded - failed} skipped")
    print(f"{'='*60}\n")

    # Upload final data blob to Supabase
    if user_id and os.path.exists("data"):
        print("  Uploading data to Supabase Storage...")
        # Rebuild the data blob from data/*.json
        blob_path = os.path.join("data", "dashboard_blob.json")
        if os.path.exists("index.html"):
            # Extract blob from built index.html
            with open("index.html") as f:
                html = f.read()
            start = html.find("var _irisEmbeddedData=")
            if start == -1:
                start = html.find("var D=") + 6
                end = html.find(";\nvar HS=")
            else:
                start += len("var _irisEmbeddedData=")
                end = html.find(";\nvar _IRIS_EMBEDDED_USER=")
            if start > 0 and end > start:
                blob = html[start:end]
                upload_user_data(config, "dashboard.json", blob)

    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Iris per-user pipeline orchestrator")
    parser.add_argument("--user", required=True, help="Username to run pipeline for")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without executing")
    parser.add_argument("--target", default="staging", choices=["staging", "production"], help="Target environment")
    args = parser.parse_args()

    success = run_pipeline(args.user, dry_run=args.dry_run, target=args.target)
    sys.exit(0 if success else 1)
