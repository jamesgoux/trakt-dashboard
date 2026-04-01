#!/usr/bin/env python3
"""
Auto-refresh Trakt OAuth token.

Reads refresh token from data/trakt_auth.json (or TRAKT_REFRESH_TOKEN env var on first run).
Writes new access + refresh tokens back to data/trakt_auth.json.
Other scripts read the access token from this file.

Trakt tokens expire every 7 days, so this runs every 2 hours in the enrichment workflow.
"""
import os, json, sys, time, requests
from user_config import load_user_config, get_service
_ucfg = load_user_config()


DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "trakt_auth.json")

CLIENT_ID = get_service(_ucfg, "trakt", "client_id") or os.environ.get("TRAKT_CLIENT_ID", "")
CLIENT_SECRET = get_service(_ucfg, "trakt", "client_secret") or os.environ.get("TRAKT_CLIENT_SECRET", "")

# Try data file first (self-renewing), fall back to env var (bootstrap)
refresh_token = ""
existing = {}
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE) as f:
            existing = json.load(f)
        refresh_token = existing.get("refresh_token", "")
        if refresh_token:
            print(f"Using refresh token from {DATA_FILE}")
    except Exception:
        pass

if not refresh_token:
    refresh_token = get_service(_ucfg, "trakt", "refresh_token") or os.environ.get("TRAKT_REFRESH_TOKEN", "")
    if refresh_token:
        print("Using refresh token from TRAKT_REFRESH_TOKEN env var (bootstrap)")

if not all([CLIENT_ID, CLIENT_SECRET, refresh_token]):
    print("ERROR: Need TRAKT_CLIENT_ID, TRAKT_CLIENT_SECRET, and refresh token")
    sys.exit(1)

# Check if current token is still fresh (more than 2 days left = skip)
created = existing.get("created_at", 0)
expires_in = existing.get("expires_in", 0)
if created and expires_in:
    remaining = (created + expires_in) - time.time()
    if remaining > 2 * 86400:
        print(f"Token still valid ({remaining/86400:.1f} days left), skipping refresh")
        sys.exit(0)
    else:
        print(f"Token expires in {remaining/86400:.1f} days, refreshing...")

print("Refreshing Trakt OAuth token...")
r = requests.post("https://api.trakt.tv/oauth/token", json={
    "refresh_token": refresh_token,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
    "grant_type": "refresh_token",
})

if r.status_code != 200:
    print(f"ERROR: {r.status_code} {r.text}")
    if existing.get("access_token"):
        print("Keeping existing token data")
        sys.exit(0)
    sys.exit(1)

data = r.json()
result = {
    "access_token": data["access_token"],
    "refresh_token": data["refresh_token"],
    "expires_in": data.get("expires_in", 0),
    "created_at": data.get("created_at", int(time.time())),
}

os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
with open(DATA_FILE, "w") as f:
    json.dump(result, f, indent=2)

print(f"Token refreshed! Expires in {result['expires_in']/86400:.1f} days")
print(f"Written to {DATA_FILE}")

# Sync refreshed token to Supabase integrations table
sb_url = os.environ.get("SUPABASE_URL", "")
sb_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
trakt_user = os.environ.get("TRAKT_USERNAME", "jamesgoux")
if sb_url and sb_key:
    try:
        # Look up user_id
        prof_r = requests.get(
            f"{sb_url}/rest/v1/profiles?username=eq.{trakt_user}&select=id",
            headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"}
        )
        if prof_r.status_code == 200 and prof_r.json():
            uid = prof_r.json()[0]["id"]
            # Update the Trakt integration config with new tokens
            # The auto-encrypt trigger will encrypt sensitive fields on write
            new_cfg = {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "access_token": result["access_token"],
                "refresh_token": result["refresh_token"],
                "username": trakt_user,
                "token_expires_at": result["created_at"] + result["expires_in"],
            }
            up_r = requests.patch(
                f"{sb_url}/rest/v1/integrations?user_id=eq.{uid}&service=eq.trakt",
                headers={
                    "apikey": sb_key,
                    "Authorization": f"Bearer {sb_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json={"config": new_cfg, "is_enabled": True, "last_error": None},
            )
            if up_r.status_code in (200, 204):
                print(f"  Synced token to Supabase integrations for {trakt_user}")
            else:
                print(f"  Supabase sync failed: {up_r.status_code} {up_r.text[:200]}")
        else:
            print(f"  Profile not found for {trakt_user}, skipping Supabase sync")
    except Exception as e:
        print(f"  Supabase token sync error (non-fatal): {e}")
else:
    print("  Supabase not configured, skipping token sync")
