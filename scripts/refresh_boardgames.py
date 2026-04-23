#!/usr/bin/env python3
"""
Fetch board game plays from BoardGameGeek via XML API.
Requires BGG_PASSWORD (and optionally BGG_USERNAME) environment variables.
Outputs data/boardgames.json for the dashboard.
"""
import os, sys, json, time, xml.etree.ElementTree as ET
from user_config import load_user_config, get_service
_ucfg = load_user_config()

try:
    import requests
except ImportError:
    print("ERROR: requests not installed"); sys.exit(1)

USERNAME = get_service(_ucfg, "bgg", "username") or os.environ.get("BGG_USERNAME", 'jamesgoux')
PASSWORD = get_service(_ucfg, "bgg", "password") or os.environ.get("BGG_PASSWORD", '')
BASE = 'https://boardgamegeek.com'
API = 'https://boardgamegeek.com/xmlapi2'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'boardgames.json')

def bgg_login(session):
    """Log into BGG and get session cookies."""
    print('  Logging into BGG...')
    r = session.post(f'{BASE}/login/api/v1', json={
        'credentials': {'username': USERNAME, 'password': PASSWORD}
    })
    if r.status_code == 200 or r.status_code == 204:
        print('  Login successful')
        return True
    elif r.status_code == 400:
        # BGG returns 400 with error message
        try:
            err = r.json().get('errors', {}).get('message', 'Unknown error')
        except:
            err = r.text[:200]
        print(f'  Login failed: {err}')
        return False
    else:
        print(f'  Login failed: HTTP {r.status_code}')
        return False

def fetch_plays(session):
    """Fetch all plays via the XML API (paginated, 100 per page)."""
    all_plays = []
    page = 1
    while True:
        url = f'{API}/plays?username={USERNAME}&page={page}'
        r = session.get(url)
        if r.status_code == 202:
            # BGG queued the request, retry after delay
            print(f'  Page {page}: queued, waiting 5s...')
            time.sleep(5)
            continue
        if r.status_code == 429:
            print(f'  Rate limited, waiting 10s...')
            time.sleep(10)
            continue
        if r.status_code != 200:
            print(f'  Page {page}: HTTP {r.status_code}, stopping')
            break

        root = ET.fromstring(r.text)
        total = int(root.get('total', '0'))
        plays = root.findall('play')
        if not plays:
            break

        for play in plays:
            item = play.find('item')
            if item is None:
                continue

            # Extract players
            players = []
            for p in play.findall('.//player'):
                players.append({
                    'name': p.get('name', ''),
                    'score': p.get('score', ''),
                    'win': p.get('win', '0') == '1',
                    'new': p.get('new', '0') == '1',
                    'color': p.get('color', ''),
                })

            play_data = {
                'play_id': int(play.get('id', '0') or '0'),  # BGG's unique play ID — used for name mapping
                'date': play.get('date', ''),
                'quantity': int(play.get('quantity', '1')),
                'length': int(play.get('length', '0')),
                'incomplete': play.get('incomplete', '0') == '1',
                'location': play.get('location', ''),
                'game': item.get('name', ''),
                'bgg_id': int(item.get('objectid', '0')),
                'players': players,
                'comments': (play.find('comments') or ET.Element('x')).text or '',
            }
            all_plays.append(play_data)

        print(f'  Page {page}: {len(plays)} plays (total so far: {len(all_plays)}/{total})')

        if len(all_plays) >= total:
            break
        page += 1
        time.sleep(1)  # Be nice to BGG

    return all_plays

def build_aggregates(plays):
    """Build aggregates for the dashboard."""
    by_game = {}
    by_year = {}
    by_month = {}
    by_date = {}  # date (YYYY-MM-DD) -> total quantity — drives weekly Activity chart bucketing
    players_count = {}
    locations = {}

    for p in plays:
        game = p['game']
        date = p['date']
        yr = date[:4] if date else ''
        mo = date[:7] if date else ''
        qty = p['quantity']

        # Game counts
        if game not in by_game:
            by_game[game] = {'count': 0, 'bgg_id': p['bgg_id'], 'total_time': 0}
        by_game[game]['count'] += qty
        by_game[game]['total_time'] += p['length'] * qty

        # Year/month/day counts
        if yr:
            by_year[yr] = by_year.get(yr, 0) + qty
        if mo:
            by_month[mo] = by_month.get(mo, 0) + qty
        if date:
            by_date[date] = by_date.get(date, 0) + qty

        # Players
        for pl in p['players']:
            name = pl['name']
            if name:
                if name not in players_count:
                    players_count[name] = {'plays': 0, 'wins': 0}
                players_count[name]['plays'] += qty
                if pl['win']:
                    players_count[name]['wins'] += qty

        # Locations
        loc = p['location']
        if loc:
            locations[loc] = locations.get(loc, 0) + qty

    # Sort games by play count
    top_games = sorted(by_game.items(), key=lambda x: -x[1]['count'])
    # Sort players by plays
    top_players = sorted(players_count.items(), key=lambda x: -x[1]['plays'])

    return {
        'top_games': [[g, v['count'], v['bgg_id'], v['total_time']] for g, v in top_games],
        'top_players': [[name, v['plays'], v['wins']] for name, v in top_players],
        'by_year': by_year,
        'by_month': by_month,
        'by_date': by_date,
        'locations': sorted(locations.items(), key=lambda x: -x[1]),
    }

def load_name_mapping():
    """Build a {bgg_play_id: [full_player_names_in_seat_order]} map from the BG Stats export.

    BGG's XML API only returns whatever text was typed into the `name` attribute (often just
    initials like 'N.' or 'I.'), losing the rich player names that BG Stats tracks. The
    BG Stats export has the ground truth with full names + emoji, keyed by BGG play id.

    Missing or absent `data/bgstats_export.json` is not fatal — plays simply keep BGG names.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'bgstats_export.json')
    if not os.path.exists(path):
        print('  (no bgstats_export.json — player names will come straight from BGG)')
        return {}
    try:
        with open(path) as f:
            bgs = json.load(f)
    except Exception as e:
        print(f'  WARNING: failed to parse bgstats_export.json ({e}) — skipping name mapping')
        return {}
    players_by_ref = {pl['id']: pl.get('name', '') for pl in bgs.get('players', [])}
    mapping = {}
    for play in bgs.get('plays', []):
        pid = play.get('bggId', 0)
        if not pid:
            continue  # play never synced to BGG
        scores = sorted(play.get('playerScores', []), key=lambda s: s.get('seatOrder', 0))
        names = [players_by_ref.get(s.get('playerRefId'), '') for s in scores]
        if any(names):
            mapping[pid] = names
    print(f'  Name mapping loaded: {len(mapping):,} BGG plays with full names from BG Stats export')
    return mapping

def apply_name_mapping(plays, mapping):
    """Override players[].name with full names from the BG Stats mapping where available.

    Positional match by seat order. Unmatched plays or players keep their BGG names (typically
    initials). "Anonymous player" entries from the BG Stats export are treated as no-mapping
    (user historically filtered those out of the dashboard). Returns (overridden_count, total_players_overridden).
    """
    if not mapping:
        return 0, 0
    overridden_plays = 0
    overridden_players = 0
    for p in plays:
        full_names = mapping.get(p.get('play_id', 0))
        if not full_names:
            continue
        if len(p['players']) != len(full_names):
            # Count mismatch — BGG and BG Stats disagree on seating. Skip to be safe.
            continue
        touched = False
        for i, player in enumerate(p['players']):
            new_name = full_names[i]
            # Don't override with "Anonymous player" — March 13 rebuild deliberately filtered these,
            # and BGG's initial (e.g. "A.") is more useful than a generic label.
            if not new_name or new_name == 'Anonymous player':
                continue
            if new_name != player.get('name'):
                player['name'] = new_name
                overridden_players += 1
                touched = True
        if touched:
            overridden_plays += 1
    return overridden_plays, overridden_players

def main():
    if not PASSWORD:
        print('ERROR: BGG_PASSWORD must be set')
        sys.exit(1)

    print('Fetching board game data from BGG...')
    session = requests.Session()
    session.headers.update({'User-Agent': 'IrisDashboard/1.0'})

    if not bgg_login(session):
        sys.exit(1)

    print('\n[Plays]')
    plays = fetch_plays(session)
    print(f'  Total: {len(plays)} plays')

    if not plays:
        print('No plays found!')
        return

    print('\n[Name mapping from BG Stats export]')
    mapping = load_name_mapping()
    op, opl = apply_name_mapping(plays, mapping)
    print(f'  Overrode names on {op:,} plays ({opl:,} player records)')

    print('\n[Aggregating...]')
    agg = build_aggregates(plays)

    # Recent plays for the feed
    recent = sorted(plays, key=lambda p: p['date'], reverse=True)[:30]

    output = {
        'total': sum(p['quantity'] for p in plays),
        'unique_games': len(set(p['game'] for p in plays)),
        'agg': agg,
        'recent': recent,
    }

    with open(OUT, 'w') as f:
        json.dump(output, f, separators=(',', ':'))
    print(f'\nSaved to {OUT} ({os.path.getsize(OUT):,} bytes)')
    print(f'Plays: {output["total"]}, Unique games: {output["unique_games"]}')
    if agg['top_games']:
        print(f'Top game: {agg["top_games"][0][0]} ({agg["top_games"][0][1]} plays)')

if __name__ == '__main__':
    main()
