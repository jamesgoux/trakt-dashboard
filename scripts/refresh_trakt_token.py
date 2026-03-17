#!/usr/bin/env python3
"""
Auto-refresh Trakt OAuth token.

Reads refresh token from data/trakt_auth.json (or TRAKT_REFRESH_TOKEN env var on first run).
Writes new access + refresh tokens back to data/trakt_auth.json.
Other scripts read the access token from this file.

Trakt tokens expire every 7 days, so this runs every 2 hours in the enrichment workflow.
"""
import os, json, sys, time, requests

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "trakt_auth.json")

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TRAKT_CLIENT_SECRET", "")

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
    refresh_token = os.environ.get("TRAKT_REFRESH_TOKEN", "")
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
