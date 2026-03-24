#!/usr/bin/env python3
"""
Process pending refresh requests from Supabase profiles table.
Runs after the main jamesgoux build in GH Actions.
Checks for users with refresh_requested_at > last_refresh_at and runs their pipeline.
"""

import sys, os, json, subprocess, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from supabase_config import get_admin_client, SUPABASE_URL, SUPABASE_SERVICE_KEY

def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("  [refresh_queue] Supabase not configured, skipping")
        return

    client = get_admin_client()

    # Find users with pending refresh requests
    # (refresh_requested_at is set AND either no last_refresh_at OR requested > last)
    profiles = client.select("profiles", {
        "refresh_status": "eq.pending",
        "select": "id,username,refresh_requested_at,last_refresh_at",
    })

    if not profiles:
        print("  [refresh_queue] No pending refresh requests")
        return

    print(f"  [refresh_queue] {len(profiles)} pending refresh(es)")

    scripts_dir = os.path.dirname(os.path.abspath(__file__))

    for profile in profiles:
        username = profile["username"]
        uid = profile["id"]
        print(f"\n  [refresh_queue] Processing: {username}")

        # Rate limit: skip if last refresh was < 10 min ago
        if profile.get("last_refresh_at"):
            from datetime import datetime, timezone
            last = datetime.fromisoformat(profile["last_refresh_at"].replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - last).total_seconds() / 60
            if age_min < 10:
                print(f"    Skipping: last refresh was {age_min:.0f}min ago (min: 10min)")
                client.update("profiles", {"refresh_status": "idle"}, {"id": f"eq.{uid}"})
                continue

        # Mark as running
        client.update("profiles", {"refresh_status": "running"}, {"id": f"eq.{uid}"})

        try:
            # Run the pipeline orchestrator
            cmd = [sys.executable, os.path.join(scripts_dir, "run_user_pipeline.py"),
                   f"--user={username}"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=900,
                cwd=os.path.dirname(scripts_dir),
                env=os.environ,
            )

            if result.returncode == 0:
                print(f"    ✓ Pipeline succeeded for {username}")
                client.update("profiles", {
                    "refresh_status": "idle",
                    "last_refresh_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }, {"id": f"eq.{uid}"})
            else:
                print(f"    ✗ Pipeline failed for {username} (exit {result.returncode})")
                if result.stderr:
                    print(f"      {result.stderr[:300]}")
                client.update("profiles", {
                    "refresh_status": "error",
                    "last_refresh_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }, {"id": f"eq.{uid}"})

        except subprocess.TimeoutExpired:
            print(f"    ⏰ Pipeline timed out for {username}")
            client.update("profiles", {"refresh_status": "error"}, {"id": f"eq.{uid}"})
        except Exception as e:
            print(f"    ✗ Error: {e}")
            client.update("profiles", {"refresh_status": "error"}, {"id": f"eq.{uid}"})


if __name__ == "__main__":
    main()
