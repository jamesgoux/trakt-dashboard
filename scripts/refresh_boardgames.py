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

        # Year/month counts
        if yr:
            by_year[yr] = by_year.get(yr, 0) + qty
        if mo:
            by_month[mo] = by_month.get(mo, 0) + qty

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
        'locations': sorted(locations.items(), key=lambda x: -x[1]),
    }

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
