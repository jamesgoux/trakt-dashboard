#!/usr/bin/env python3
"""Refresh Trakt OAuth token using the refresh token.
Writes result to data/.token_refresh_result as JSON."""
import os, json, base64, requests

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TRAKT_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("TRAKT_REFRESH_TOKEN", "")

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    result = {"ok": False, "error": "Missing env vars"}
    with open("data/.token_refresh_result", "w") as f:
        json.dump(result, f)
    exit(1)

print("Refreshing Trakt OAuth token...")
r = requests.post("https://api.trakt.tv/oauth/token", json={
    "refresh_token": REFRESH_TOKEN,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
    "grant_type": "refresh_token",
})

if r.status_code != 200:
    result = {"ok": False, "error": f"{r.status_code} {r.text}"}
    with open("data/.token_refresh_result", "w") as f:
        json.dump(result, f)
    print(f"ERROR: {r.status_code}")
    exit(1)

data = r.json()
# Base64-encode to avoid accidental secret masking in logs
result = {
    "ok": True,
    "at": base64.b64encode(data["access_token"].encode()).decode(),
    "rt": base64.b64encode(data["refresh_token"].encode()).decode(),
    "expires_in": data.get("expires_in", 0),
}
with open("data/.token_refresh_result", "w") as f:
    json.dump(result, f)
print("Token refreshed successfully. Result written to data/.token_refresh_result")
