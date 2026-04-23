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

import re as _re_names

def _base_name(n):
    """Return the full name with emoji/decorations stripped, for comparing 'James Goux' vs 'James Goux 🧔🏻'."""
    if not n:
        return ''
    # Keep word chars, spaces, apostrophes, periods, hyphens; drop everything else (emoji, etc.)
    return _re_names.sub(r'[^\w\s\'\.\-]', '', n, flags=_re_names.UNICODE).strip()

def _looks_like_initial(n):
    """BGG often stores player names as initials like 'A.' or 'N.' — short + ends with a period."""
    return bool(n) and len(n) <= 3 and n.endswith('.')

def _build_canonical_names(mapping):
    """From the positional mapping, build {base_name: preferred_display_name}.

    Prefer the longer form (which usually includes the emoji) so that
    'James Goux' gets canonicalized to 'James Goux 🧔🏻' everywhere, even in
    plays where positional mapping didn't apply.
    """
    canon = {}
    for _, names in mapping.items():
        for n in names:
            if not n or n == 'Anonymous player':
                continue
            base = _base_name(n)
            if not base or _looks_like_initial(base):
                continue
            existing = canon.get(base)
            if existing is None or len(n) > len(existing):
                canon[base] = n
    return canon

def apply_name_mapping(plays, mapping):
    """Override players[].name with full names from the BG Stats mapping.

    Three passes per play:
      1. Full-name base match — for BGG players already named (e.g. 'James Goux'),
         upgrade to the mapping's full form (e.g. 'James Goux 🧔🏻'). Robust to order.
      2. Letter-grouped initial match — for BGG players stored as initials ('I.', 'M.'),
         match within-play against BG Stats full names starting with the same letter. When
         counts align (e.g. 1 'I.' in BGG and 1 I-named player in BGS) assign positionally
         within that letter group. BG Stats seat orders are often all-zero (user didn't set
         them), so this first-letter approach sidesteps that.
      3. Canonical normalization — any BGG full name whose base matches a known person
         gets the emoji'd canonical form (fallback for plays with no mapping or partial
         matches). Prevents top_players from splitting 'James Goux' across emoji'd and
         non-emoji'd rows.

    Anonymous player entries are never used as overrides (March 13 rebuild filtered those).

    Returns (overridden_plays_count, total_player_records_touched).
    """
    if not mapping:
        return 0, 0
    canonical = _build_canonical_names(mapping)
    overridden_plays = 0
    overridden_players = 0
    for p in plays:
        touched = False
        full_names = mapping.get(p.get('play_id', 0), []) or []
        usable = [n for n in full_names if n and n != 'Anonymous player']

        # Pass 1 — upgrade already-named BGG players when a same-base full name exists in BGS.
        # Track which BGS names have been consumed so we don't double-assign them in pass 2.
        consumed = set()
        for player in p['players']:
            cur = player.get('name', '')
            if not cur or _looks_like_initial(cur):
                continue
            base = _base_name(cur)
            # Prefer the longest matching full name for this base
            match = None
            for idx, cand in enumerate(usable):
                if idx in consumed:
                    continue
                if _base_name(cand) == base:
                    if match is None or len(cand) > len(usable[match]):
                        match = idx
            if match is not None:
                if usable[match] != cur:
                    player['name'] = usable[match]
                    overridden_players += 1
                    touched = True
                consumed.add(match)

        # Pass 2 — assign BGG initials to remaining BGS full names by first-letter grouping.
        # Available pool: BGS names not already consumed AND that aren't initials themselves.
        remaining = [(idx, usable[idx]) for idx in range(len(usable)) if idx not in consumed and not _looks_like_initial(usable[idx])]
        remaining_by_letter = {}
        for idx, n in remaining:
            remaining_by_letter.setdefault(n[:1].upper(), []).append((idx, n))
        # Collect BGG initial players per-letter (preserving order)
        bgg_initials_by_letter = {}
        for i, player in enumerate(p['players']):
            cur = player.get('name', '')
            if _looks_like_initial(cur):
                bgg_initials_by_letter.setdefault(cur[:1].upper(), []).append(i)
        # For each letter, pair up within BGG order ↔ BGS order. Assign as many as we have candidates for.
        for letter, bgg_positions in bgg_initials_by_letter.items():
            cands = remaining_by_letter.get(letter, [])
            pair_count = min(len(bgg_positions), len(cands))
            for k in range(pair_count):
                bgg_i = bgg_positions[k]
                bgs_idx, bgs_name = cands[k]
                if p['players'][bgg_i].get('name') != bgs_name:
                    p['players'][bgg_i]['name'] = bgs_name
                    overridden_players += 1
                    touched = True
                consumed.add(bgs_idx)

        # Pass 3 — canonical normalization for any full names not already matched above.
        for player in p['players']:
            cur = player.get('name', '')
            if _looks_like_initial(cur) or not cur:
                continue
            canon = canonical.get(_base_name(cur))
            if canon and canon != cur:
                player['name'] = canon
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
