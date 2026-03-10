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
login_data = r.json()
username = login_data.get("username", "")
token = login_data.get("token", "")
print(f"Username: {username}")
if not token:
    print("No token!"); exit(1)

# Session with auth cookie
session = requests.Session()
session.headers.update(HEADERS)
session.cookies.set("tvproject_credentials", token, domain=".serializd.com")
# Also try as Authorization header
session.headers["Authorization"] = f"Bearer {token}"
session.headers["Cookie"] = f"tvproject_credentials={token}"

# Broader endpoint exploration
endpoints = [
    # Profile patterns
    f"/user/{username}",
    f"/user/{username}/ratings",
    f"/user/{username}/reviews",
    f"/user/{username}/diary",
    f"/user/{username}/watched",
    f"/user/{username}/activity",
    f"/user/{username}/shows",
    f"/user/{username}/profile",
    # getUserX patterns (common in Next.js/Vercel apps)
    f"/getUserShows/{username}",
    f"/getUserRatings/{username}",
    f"/getUserReviews/{username}",
    f"/getUserDiary/{username}",
    f"/getUserWatched/{username}",
    f"/getUserActivity/{username}",
    f"/getUserProfile/{username}",
    # camelCase patterns
    f"/userShows/{username}",
    f"/userRatings/{username}",
    f"/userReviews/{username}",
    f"/userProfile/{username}",
    # Kebab patterns
    f"/user-shows/{username}",
    f"/user-ratings/{username}",
    f"/user-profile/{username}",
    # Show-specific (test with a known TMDB ID - Breaking Bad = 1396)
    "/show/1396",
    "/show/1396/reviews",
    "/show/1396/ratings",
    # Other patterns
    "/me",
    "/me/ratings",
    "/me/shows",
    "/account",
    "/account/ratings",
    "/diary",
    "/reviews",
    "/watched",
    "/watchedShows",
    "/getWatchedShows",
    # POST endpoints (some APIs use POST for queries)
]

for ep in endpoints:
    try:
        r2 = session.get(f"{BASE}{ep}", timeout=5)
        status = r2.status_code
        if status == 200:
            try:
                data = r2.json()
                if isinstance(data, dict):
                    print(f"\n{ep}: 200 - keys: {list(data.keys())[:10]}")
                    for k, v in list(data.items())[:5]:
                        if isinstance(v, list):
                            print(f"  {k}: list[{len(v)}]")
                            if v: print(f"    first: {json.dumps(v[0])[:200]}")
                        elif isinstance(v, dict):
                            print(f"  {k}: dict keys={list(v.keys())[:8]}")
                        else:
                            print(f"  {k}: {repr(v)[:100]}")
                elif isinstance(data, list):
                    print(f"\n{ep}: 200 - list[{len(data)}]")
                    if data: print(f"  first: {json.dumps(data[0])[:200]}")
                else:
                    print(f"\n{ep}: 200 - {type(data).__name__}: {str(data)[:100]}")
            except:
                print(f"\n{ep}: 200 - body: {r2.text[:200]}")
        elif status != 404:
            print(f"\n{ep}: {status} - {r2.text[:100]}")
    except Exception as e:
        print(f"\n{ep}: ERROR {e}")

# Also try POST endpoints
post_endpoints = [
    ("/getUserShows", {"username": username}),
    ("/getUserRatings", {"username": username}),
    ("/getUserProfile", {"username": username}),
    ("/getProfile", {"username": username}),
    ("/getRatings", {"username": username}),
    ("/getReviews", {"username": username}),
    ("/getDiary", {"username": username}),
    ("/getWatched", {"username": username}),
    ("/getActivity", {"username": username}),
    ("/getUserData", {"username": username}),
]

print("\n\n=== POST endpoints ===")
for ep, body in post_endpoints:
    try:
        r3 = session.post(f"{BASE}{ep}", json=body, timeout=5)
        status = r3.status_code
        if status == 200:
            try:
                data = r3.json()
                if isinstance(data, dict):
                    print(f"\n{ep}: 200 - keys: {list(data.keys())[:10]}")
                    for k, v in list(data.items())[:5]:
                        if isinstance(v, list):
                            print(f"  {k}: list[{len(v)}]")
                            if v: print(f"    first: {json.dumps(v[0])[:200]}")
                        elif isinstance(v, dict):
                            print(f"  {k}: dict keys={list(v.keys())[:8]}")
                        else:
                            print(f"  {k}: {repr(v)[:100]}")
                elif isinstance(data, list):
                    print(f"\n{ep}: 200 - list[{len(data)}]")
                    if data: print(f"  first: {json.dumps(data[0])[:200]}")
            except:
                print(f"\n{ep}: 200 - body: {r3.text[:200]}")
        elif status != 404:
            print(f"\n{ep}: {status} - {r3.text[:100]}")
    except Exception as e:
        print(f"\n{ep}: ERROR {e}")
