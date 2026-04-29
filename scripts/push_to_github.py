#!/usr/bin/env python3
"""
Push changed files to GitHub via the REST API (no git operations needed).

Replaces the slow git add/commit/pull/push cycle in CI workflows.
Uses the GitHub Git Data API to create a single commit with all changed files.

Usage:
    python scripts/push_to_github.py "Core build 2026-04-21 05:00 UTC"

Requires GITHUB_TOKEN env var (automatically available in GitHub Actions).
"""
import os, sys, json, hashlib, base64, subprocess

REPO = "jamesgoux/iris-stats"
BRANCH = "main"
API = "https://api.github.com"

def github_get(path, token):
    """GET request to GitHub API."""
    import urllib.request
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except Exception as e:
        print(f"  API GET {path}: {e}")
        return None

def github_post(path, data, token):
    """POST request to GitHub API."""
    import urllib.request
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{API}{path}", data=body, method="POST", headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read())
    except Exception as e:
        print(f"  API POST {path}: {e}")
        return None

def github_patch(path, data, token):
    """PATCH request to GitHub API."""
    import urllib.request
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{API}{path}", data=body, method="PATCH", headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read())
    except Exception as e:
        print(f"  API PATCH {path}: {e}")
        return None


def get_changed_files():
    """Get list of files that differ from the git index (what would be staged by git add)."""
    # Files we track in git (not gitignored intermediate caches)
    tracked_patterns = [
        "index.html",
        "data/watchlist.json", "data/up_next.json", "data/upcoming.json",
        "data/letterboxd.json", "data/goodreads.json", "data/lastfm.json",
        "data/lastfm_daily.json", "data/pocketcasts.json", "data/serializd.json",
        "data/setlist.json", "data/setlist_songs.json", "data/health.json",
        "data/boardgames.json", "data/sports_schedule.json", "data/box_office.json",
        "data/gametrack.json", "data/bgstats_export.json",
        "data/headshots.json", "data/posters.json", "data/logos.json",
        "data/book_genres.json", "data/artist_genres.json",
        "data/pocketcasts_history.json",
        "data/tmdb_credits_done.json", "data/tmdb_trakt_cache.json",
        "data/lb_tmdb_cache.json", "data/slug_recency.json", "data/slug_tmdb.json",
        "templates/dashboard.html",
        "scripts/",
        ".gitignore",
    ]
    # Use git diff to find what changed (more reliable than git status in shallow clones)
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, timeout=30
    )
    status_stderr = result.stderr.strip()
    if status_stderr:
        print(f"  git diff stderr: {status_stderr[:200]}")

    changed_set = set()
    for line in result.stdout.strip().split("\n"):
        filepath = line.strip()
        if not filepath:
            continue
        for pattern in tracked_patterns:
            if pattern.endswith("/"):
                if filepath.startswith(pattern):
                    changed_set.add(filepath); break
            elif filepath == pattern:
                changed_set.add(filepath); break

    # Also check for new untracked files we care about
    result2 = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, timeout=10
    )
    for line in result2.stdout.strip().split("\n"):
        filepath = line.strip()
        if not filepath:
            continue
        for pattern in tracked_patterns:
            if pattern.endswith("/"):
                if filepath.startswith(pattern):
                    changed_set.add(filepath); break
            elif filepath == pattern:
                changed_set.add(filepath); break

    changed = [f for f in changed_set if os.path.exists(f)]
    print(f"  Detected {len(changed)} changed files (git diff: {result.stdout.count(chr(10))} lines)")
    return changed


def push_files(files, message, token):
    """Create a single commit with all changed files via the Git Data API."""
    if not files:
        print("No files to push.")
        return True

    print(f"Pushing {len(files)} files...")

    # 1. Get current commit SHA for the branch
    ref = github_get(f"/repos/{REPO}/git/ref/heads/{BRANCH}", token)
    if not ref:
        print("ERROR: Could not get branch ref")
        return False
    current_sha = ref["object"]["sha"]
    print(f"  Current HEAD: {current_sha[:7]}")

    # 2. Get the tree SHA from the current commit
    commit = github_get(f"/repos/{REPO}/git/commits/{current_sha}", token)
    if not commit:
        print("ERROR: Could not get current commit")
        return False
    base_tree_sha = commit["tree"]["sha"]

    # 3. Create blobs for each file
    tree_items = []
    for filepath in files:
        with open(filepath, "rb") as f:
            content = f.read()

        # Use base64 for binary safety
        blob = github_post(f"/repos/{REPO}/git/blobs", {
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        }, token)
        if not blob:
            print(f"  ERROR: Could not create blob for {filepath}")
            continue

        tree_items.append({
            "path": filepath,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })
        size_kb = len(content) / 1024
        print(f"  Blob: {filepath} ({size_kb:.0f} KB)")

    if not tree_items:
        print("ERROR: No blobs created")
        return False

    # 4. Create a new tree
    tree = github_post(f"/repos/{REPO}/git/trees", {
        "base_tree": base_tree_sha,
        "tree": tree_items,
    }, token)
    if not tree:
        print("ERROR: Could not create tree")
        return False
    print(f"  Tree: {tree['sha'][:7]}")

    # 5. Create the commit
    new_commit = github_post(f"/repos/{REPO}/git/commits", {
        "message": message,
        "tree": tree["sha"],
        "parents": [current_sha],
        "author": {
            "name": "github-actions[bot]",
            "email": "github-actions[bot]@users.noreply.github.com",
        },
    }, token)
    if not new_commit:
        print("ERROR: Could not create commit")
        return False
    print(f"  Commit: {new_commit['sha'][:7]}")

    # 6. Update the branch ref (fast-forward)
    updated = github_patch(f"/repos/{REPO}/git/refs/heads/{BRANCH}", {
        "sha": new_commit["sha"],
        "force": False,  # No force push — fails if not fast-forward
    }, token)
    if not updated:
        # If fast-forward fails, retry with force (another build pushed while we were working)
        print("  Fast-forward failed, retrying with force...")
        # Re-fetch current HEAD, create new commit on top of it
        ref2 = github_get(f"/repos/{REPO}/git/ref/heads/{BRANCH}", token)
        if ref2:
            new_head = ref2["object"]["sha"]
            # Create new commit with updated parent
            retry_commit = github_post(f"/repos/{REPO}/git/commits", {
                "message": message,
                "tree": tree["sha"],
                "parents": [new_head],
                "author": {
                    "name": "github-actions[bot]",
                    "email": "github-actions[bot]@users.noreply.github.com",
                },
            }, token)
            if retry_commit:
                updated = github_patch(f"/repos/{REPO}/git/refs/heads/{BRANCH}", {
                    "sha": retry_commit["sha"],
                    "force": True,
                }, token)
                if updated:
                    print(f"  Pushed (force): {retry_commit['sha'][:7]}")
                    return True
        print("ERROR: Could not update branch ref")
        return False

    print(f"  Pushed: {new_commit['sha'][:7]}")
    return True


def main():
    message = sys.argv[1] if len(sys.argv) > 1 else f"Pipeline update"
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN not set")
        sys.exit(1)

    files = get_changed_files()
    if not files:
        print("No changes to push.")
        return

    print(f"\n=== Push to GitHub ({len(files)} files) ===")
    success = push_files(files, message, token)
    if not success:
        print("Push failed!")
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
