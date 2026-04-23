#!/usr/bin/env python3
"""
Delete duplicate plays on BoardGameGeek that were created by parallel sync runs.

Reads a list of BGG play IDs from an input JSON file and POSTs delete actions
via the same `geekplay.php` endpoint used for creates. Includes a dry-run mode
and a --limit N flag so the first use can be validated on a single play.

Expected input JSON (list of objects):
  [{"bgg_id": 113121243, "date": "...", "game_id": ..., "length": ...}, ...]
"""
import os, sys, json, time, argparse
try:
    import requests
except ImportError:
    print('ERROR: requests not installed'); sys.exit(1)

USERNAME = os.environ.get('BGG_USERNAME', 'jamesgoux')
PASSWORD = os.environ.get('BGG_PASSWORD', '')
BASE = 'https://boardgamegeek.com'


def bgg_login(session):
    print('  Logging into BGG...')
    r = session.post(f'{BASE}/login/api/v1', json={'credentials': {'username': USERNAME, 'password': PASSWORD}})
    if r.status_code in (200, 204):
        print('  Login successful')
        return True
    print(f'  Login failed: HTTP {r.status_code}  {r.text[:200]}')
    return False


def delete_play(session, play_id):
    """POST action=delete to geekplay.php. Try both JSON and form encodings."""
    payload = {'action': 'delete', 'playid': str(play_id), 'ajax': 1, 'finalize': 1}
    # Form-encoded attempt (BGG often uses forms for legacy actions)
    r = session.post(f'{BASE}/geekplay.php', data=payload,
                     headers={'Accept': 'application/json'})
    if r.status_code != 200:
        return False, f'HTTP {r.status_code}: {r.text[:200]}'
    text = r.text.strip()
    if not text:
        return True, 'empty-response-ok'
    try:
        resp = r.json()
    except Exception:
        # Some responses aren't JSON — treat HTTP 200 + non-error text as success
        if 'error' in text.lower() or 'login' in text.lower():
            return False, text[:200]
        return True, text[:120]
    if resp.get('error'):
        return False, f'error: {resp.get("error")}'
    return True, str(resp)[:120]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True, help='Path to delete manifest JSON')
    ap.add_argument('--commit', action='store_true', help='Actually delete (default: dry-run)')
    ap.add_argument('--limit', type=int, default=0, help='Stop after N deletes (0 = all)')
    ap.add_argument('--sleep', type=float, default=1.0, help='Seconds between delete requests')
    args = ap.parse_args()

    with open(args.input) as f:
        targets = json.load(f)
    print(f'Loaded {len(targets)} play(s) to delete from {args.input}')

    if args.limit and args.limit < len(targets):
        targets = targets[:args.limit]
        print(f'  (limited to first {args.limit})')

    if not args.commit:
        print(f'\n[DRY RUN] Would delete {len(targets)} plays:')
        for i, t in enumerate(targets[:20]):
            print(f'  {i+1:3d}. bgg_id={t["bgg_id"]}  date={t.get("date")}  game={t.get("game_id")}  len={t.get("length")}m')
        if len(targets) > 20:
            print(f'  ... and {len(targets)-20} more')
        print('\nRe-run with --commit to actually delete.')
        return

    if not PASSWORD:
        print('ERROR: BGG_PASSWORD required'); sys.exit(1)

    session = requests.Session()
    session.headers.update({'User-Agent': 'IrisDashboardCleanup/1.0'})
    if not bgg_login(session):
        sys.exit(1)

    deleted = 0
    failed = []
    for i, t in enumerate(targets):
        ok, msg = delete_play(session, t['bgg_id'])
        label = f"{t.get('date','')}  game={t.get('game_id','')}  bgg_id={t['bgg_id']}"
        if ok:
            deleted += 1
            print(f'  [{i+1:3d}/{len(targets)}] {label}  -> {msg}')
        else:
            failed.append((t['bgg_id'], msg))
            print(f'  [{i+1:3d}/{len(targets)}] {label}  FAIL: {msg}')
        time.sleep(args.sleep)

    print(f'\nDeleted: {deleted}  Failed: {len(failed)}')
    if failed and deleted == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
