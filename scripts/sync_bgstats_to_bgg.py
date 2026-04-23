#!/usr/bin/env python3
"""
Sync local-only BG Stats plays to BoardGameGeek.

The BG Stats iOS app tracks each play with a `bggId` field — 0 when the play
hasn't been synced to BGG. We find all `bggId == 0` plays in
`data/bgstats_export.json` and POST each one to BGG's undocumented
`geekplay.php` endpoint (the same endpoint the web UI and BG Stats use).

On success, we update the play's `bggId` in-place so the local export stays
in sync with BGG. The next `refresh_boardgames.py` run then picks up those
plays via the XML API and their player-name mapping continues to work.

Usage:
  python scripts/sync_bgstats_to_bgg.py --dry-run    # default — preview only
  python scripts/sync_bgstats_to_bgg.py --commit     # actually POST to BGG
"""
import os, sys, json, time, argparse
from datetime import datetime

try:
    import requests
except ImportError:
    print("ERROR: requests not installed"); sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT_PATH = os.path.join(ROOT, 'data', 'bgstats_export.json')

USERNAME = os.environ.get('BGG_USERNAME', 'jamesgoux')
PASSWORD = os.environ.get('BGG_PASSWORD', '')
BASE = 'https://boardgamegeek.com'


def bgg_login(session):
    """Authenticate with BGG — sets session cookies used by subsequent writes."""
    print('  Logging into BGG...')
    r = session.post(
        f'{BASE}/login/api/v1',
        json={'credentials': {'username': USERNAME, 'password': PASSWORD}},
    )
    if r.status_code in (200, 204):
        print('  Login successful')
        return True
    print(f'  Login failed: HTTP {r.status_code}  body: {r.text[:200]}')
    return False


def fetch_bgg_userid(session):
    """Scrape the logged-in user's BGG userid from their profile page."""
    r = session.get(f'{BASE}/user/{USERNAME}')
    if r.status_code != 200:
        return 0
    # Look for the userid in the page HTML/JSON (e.g. "userid":123456)
    import re
    m = re.search(r'"userid":(\d+)', r.text)
    return int(m.group(1)) if m else 0


def build_payload(play, games_by_ref, locs_by_ref, players_by_ref, owner_userid):
    """Convert a BG Stats play record to the geekplay.php JSON payload.

    geekplay.php expects:
      action=save, objecttype=thing, objectid=<bgg_game_id>, playdate, date,
      quantity, length, hours, minutes, location, comments, twitter, ajax=1,
      players=[{username, userid, name, repeat, selected}, ...]
    """
    game = games_by_ref.get(play['gameRefId'], {})
    bgg_game_id = game.get('bggId', 0)
    if not bgg_game_id:
        return None
    loc = locs_by_ref.get(play.get('locationRefId', 0), '') or ''
    date_ymd = play.get('playDate', '')[:10]
    dur = int(play.get('durationMin') or 0)
    hours, minutes = divmod(dur, 60)
    comments = (play.get('comments') or '').strip()

    player_list = []
    for s in play.get('playerScores', []):
        pl = players_by_ref.get(s.get('playerRefId'), {})
        pname = pl.get('name', '').strip()
        is_self = pname.startswith('James Goux')  # match the BGG-logged-in user
        player_list.append({
            'username': USERNAME if is_self else '',
            'userid': owner_userid if is_self else 0,
            'name': pname,
            'repeat': 'true',
            'selected': 'false',
            'score': (s.get('score') or '').strip() if s.get('score') else '',
            'rating': 0,
            'new': 'false',
            'win': 'true' if s.get('winner') else 'false',
            'color': '',
            'startposition': str(s.get('seatOrder') or ''),
        })

    return {
        'action': 'save',
        'objecttype': 'thing',
        'objectid': str(bgg_game_id),
        'playdate': date_ymd,
        'date': f'{date_ymd}T05:00:00.000Z',
        'quantity': '1',
        'length': dur,
        'hours': hours,
        'minutes': minutes,
        'location': loc,
        'comments': comments,
        'twitter': 'false',
        'ajax': 1,
        'players': player_list,
    }


def post_play(session, payload):
    """POST a play to BGG. Returns (success, new_play_id_or_err)."""
    r = session.post(
        f'{BASE}/geekplay.php',
        json=payload,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
    )
    if r.status_code != 200:
        return False, f'HTTP {r.status_code}: {r.text[:200]}'
    # Response is typically JSON with a `playid` field
    try:
        resp = r.json()
    except Exception:
        return False, f'non-JSON response: {r.text[:200]}'
    if resp.get('error'):
        return False, f'BGG error: {resp.get("error")}'
    new_id = resp.get('playid') or resp.get('id') or 0
    try:
        new_id = int(new_id)
    except (ValueError, TypeError):
        new_id = 0
    if new_id <= 0:
        return False, f'no play id in response: {resp}'
    return True, new_id


def main():
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument('--dry-run', action='store_true', default=True,
                     help='Preview only — do not POST to BGG (default)')
    grp.add_argument('--commit', action='store_true',
                     help='Actually POST plays to BGG and update the export file')
    ap.add_argument('--limit', type=int, default=0,
                    help='Stop after N plays (0 = all)')
    ap.add_argument('--sleep', type=float, default=1.5,
                    help='Seconds between POSTs (default 1.5)')
    args = ap.parse_args()
    commit = args.commit
    if commit:
        args.dry_run = False

    if not os.path.exists(EXPORT_PATH):
        print(f'ERROR: {EXPORT_PATH} not found')
        sys.exit(1)
    with open(EXPORT_PATH) as f:
        export = json.load(f)

    games_by_ref = {g['id']: g for g in export.get('games', [])}
    locs_by_ref = {l['id']: l.get('name', '') for l in export.get('locations', [])}
    players_by_ref = {p['id']: p for p in export.get('players', [])}

    candidates = [p for p in export.get('plays', [])
                  if not p.get('bggId', 0) and not p.get('ignored')]
    print(f'Found {len(candidates)} local-only plays (bggId=0, not ignored)')

    if not candidates:
        return

    if args.limit and args.limit < len(candidates):
        candidates = candidates[:args.limit]
        print(f'  (limited to first {args.limit})')

    if args.dry_run:
        print(f'\n[DRY RUN] — would POST {len(candidates)} plays. Preview:')
        for i, play in enumerate(candidates):
            game = games_by_ref.get(play['gameRefId'], {})
            name = game.get('bggName') or game.get('name', '?')
            loc = locs_by_ref.get(play.get('locationRefId', 0), '')
            date = play.get('playDate', '')[:10]
            dur = play.get('durationMin', 0)
            names = [players_by_ref.get(s['playerRefId'], {}).get('name', '')
                     for s in play.get('playerScores', [])]
            print(f'  {i+1:2d}. {date}  {name}  {dur}m  @{loc or "-"}  [{len(names)}p: {", ".join(names)}]')
        # Show full payload for the first one
        if candidates:
            sample = build_payload(candidates[0], games_by_ref, locs_by_ref, players_by_ref, owner_userid=0)
            print('\nExample payload (first play):')
            print(json.dumps(sample, indent=2, ensure_ascii=False))
        print('\nDry run complete. Re-run with --commit to actually POST.')
        return

    # Real sync path
    if not PASSWORD:
        print('ERROR: BGG_PASSWORD env var required for --commit')
        sys.exit(1)

    session = requests.Session()
    session.headers.update({'User-Agent': 'IrisDashboardSync/1.0'})
    if not bgg_login(session):
        sys.exit(1)

    owner_userid = fetch_bgg_userid(session)
    print(f'  BGG userid: {owner_userid}')

    synced_count = 0
    failed = []
    changed = False
    for i, play in enumerate(candidates):
        payload = build_payload(play, games_by_ref, locs_by_ref, players_by_ref, owner_userid)
        if payload is None:
            failed.append((play.get('uuid'), 'no BGG game id'))
            continue
        label = f"{payload['playdate']}  {payload.get('objectid')}  len={payload['length']}m"
        ok, result = post_play(session, payload)
        if ok:
            new_id = int(result)
            play['bggId'] = new_id
            play['bggLastSync'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            changed = True
            synced_count += 1
            print(f'  [{i+1:2d}/{len(candidates)}] {label}  -> new bggId={new_id}')
        else:
            failed.append((play.get('uuid'), result))
            print(f'  [{i+1:2d}/{len(candidates)}] {label}  FAIL: {result}')
        time.sleep(args.sleep)

    if changed:
        with open(EXPORT_PATH, 'w') as f:
            json.dump(export, f, separators=(',', ':'), ensure_ascii=False)
        print(f'\nSaved {synced_count} new bggIds to {EXPORT_PATH}')
    print(f'\nSynced: {synced_count}  Failed: {len(failed)}')
    if failed:
        print('Failures:')
        for uuid, err in failed:
            print(f'  {uuid}  {err}')
        sys.exit(1 if synced_count == 0 else 0)


if __name__ == '__main__':
    main()
