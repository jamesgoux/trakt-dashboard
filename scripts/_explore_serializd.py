#!/usr/bin/env python3
"""Explore Serializd API to find ratings endpoints."""
import os, json, requests

BASE = "https://www.serializd.com/api"
HEADERS = {
    "Origin": "https://www.serializd.com",
    "Referer": "https://www.serializd.com",
    "X-Requested-With": "serializd_vercel",
    "Content-Type": "application/json",
}

email = os.environ.get("SERIALIZD_EMAIL")
password = os.environ.get("SERIALIZD_PASSWORD")
if not email or not password:
    print("Set SERIALIZD_EMAIL and SERIALIZD_PASSWORD"); exit(1)

# Login
print("Logging in...")
r = requests.post(f"{BASE}/login", headers=HEADERS, json={"email": email, "password": password})
print(f"Login status: {r.status_code}")
if r.status_code != 200:
    print(r.text[:500]); exit(1)

login_data = r.json()
print(f"Login response keys: {list(login_data.keys())}")
token = login_data.get("token") or login_data.get("access_token") or login_data.get("accessToken")
if not token:
    print(f"Full login response: {json.dumps(login_data, indent=2)[:1000]}")
    exit(1)

print(f"Got token: {token[:20]}...")

# Set auth cookie
session = requests.Session()
session.headers.update(HEADERS)
session.cookies.set("tvproject_credentials", token, domain=".serializd.com")

# Try various profile/ratings endpoints
endpoints = [
    "/user",
    "/user/profile",
    "/user/ratings",
    "/user/reviews",
    "/user/diary",
    "/user/watched",
    "/user/activity",
    "/profile",
    "/profile/ratings",
    "/ratings",
    "/getuserprofile",
    "/getUserProfile",
]

for ep in endpoints:
    try:
        r2 = session.get(f"{BASE}{ep}", timeout=5)
        status = r2.status_code
        body = r2.text[:200] if r2.status_code == 200 else r2.text[:100]
        print(f"\n{ep}: {status}")
        if status == 200:
            try:
                data = r2.json()
                print(f"  Keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, list):
                            print(f"  {k}: list[{len(v)}]")
                        elif isinstance(v, dict):
                            print(f"  {k}: dict keys={list(v.keys())[:5]}")
                        else:
                            print(f"  {k}: {repr(v)[:80]}")
            except:
                print(f"  Body: {body}")
    except Exception as e:
        print(f"\n{ep}: ERROR {e}")
