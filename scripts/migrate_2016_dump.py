#!/usr/bin/env python3
"""
Migrate June 30 2016 episode dump to dateless watches on Trakt.

Strategy:
1. Fetch all history entries from 2016-06-30
2. Collect their 64-bit history IDs for precise removal
3. Remove them from history
4. Re-add them without watched_at (Trakt unknown/no date)

Uses TRAKT_CLIENT_ID and TRAKT_ACCESS_TOKEN from environment.
Run with --dry-run to preview without making changes.
"""
import os, sys, json, time, requests

CLIENT_ID = os.environ.get('TRAKT_CLIENT_ID', '')
ACCESS_TOKEN = os.environ.get('TRAKT_ACCESS_TOKEN', '')
BASE = 'https://api.trakt.tv'
HEADERS = {
    'Content-Type': 'application/json',
    'trakt-api-version': '2',
    'trakt-api-key': CLIENT_ID,
    'Authorization': f'Bearer {ACCESS_TOKEN}'
}
DUMP_DATE = '2016-06-30'
DRY_RUN = '--dry-run' in sys.argv

def api_call(method, url, **kwargs):
    """Make API call with rate limit handling."""
    for attempt in range(3):
        r = method(url, headers=HEADERS, **kwargs)
        if r.status_code == 429:
            wait = int(r.headers.get('Retry-After', 5))
            print(f'  Rate limited, waiting {wait}s...')
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()

def get_history(item_type='episodes'):
    all_items, page = [], 1
    while True:
        r = api_call(requests.get, f'{BASE}/sync/history/{item_type}', params={
            'start_at': f'{DUMP_DATE}T00:00:00.000Z',
            'end_at': f'{DUMP_DATE}T23:59:59.999Z',
            'page': page, 'limit': 100
        })
        items = r.json()
        if not items: break
        all_items.extend(items)
        total_pages = int(r.headers.get('X-Pagination-Page-Count', 1))
        print(f'  Page {page}/{total_pages}: {len(items)} items (total: {len(all_items)})')
        if page >= total_pages: break
        page += 1
        time.sleep(0.5)
    return all_items

def remove_history(history_ids, batch_size=100):
    removed = 0
    for i in range(0, len(history_ids), batch_size):
        batch = history_ids[i:i+batch_size]
        if DRY_RUN:
            print(f'  [DRY RUN] Would remove batch {i//batch_size+1}: {len(batch)} entries')
            removed += len(batch); continue
        r = api_call(requests.post, f'{BASE}/sync/history/remove', json={'ids': batch})
        d = r.json().get('deleted', {})
        n = d.get('movies', 0) + d.get('episodes', 0)
        removed += n
        print(f'  Batch {i//batch_size+1}: removed {n} (total: {removed})')
        time.sleep(1)
    return removed

def add_without_date(trakt_ids, media_type='episodes', batch_size=100):
    added = 0
    for i in range(0, len(trakt_ids), batch_size):
        batch = trakt_ids[i:i+batch_size]
        body = {media_type: [{'ids': {'trakt': tid}} for tid in batch]}
        if DRY_RUN:
            print(f'  [DRY RUN] Would re-add batch {i//batch_size+1}: {len(batch)} {media_type}')
            added += len(batch); continue
        r = api_call(requests.post, f'{BASE}/sync/history', json=body)
        result = r.json()
        n = result.get('added', {}).get(media_type, 0)
        added += n
        nf = result.get('not_found', {}).get(media_type, [])
        if nf: print(f'  Warning: {len(nf)} not found in batch {i//batch_size+1}')
        print(f'  Batch {i//batch_size+1}: added {n} (total: {added})')
        time.sleep(1)
    return added

def main():
    if not CLIENT_ID or not ACCESS_TOKEN:
        print('ERROR: TRAKT_CLIENT_ID and TRAKT_ACCESS_TOKEN must be set')
        sys.exit(1)
    if DRY_RUN:
        print('=== DRY RUN — no changes will be made ===\n')

    print(f'Step 1: Fetching history from {DUMP_DATE}...')
    episodes = get_history('episodes')
    movies = get_history('movies')
    print(f'\nFound: {len(episodes)} episodes, {len(movies)} movies\n')
    if not episodes and not movies:
        print('Nothing to migrate!'); return

    if episodes:
        print('Sample:')
        for ep in episodes[:5]:
            s = ep.get('show',{}).get('title','?')
            sn = ep.get('episode',{}).get('season','?')
            en = ep.get('episode',{}).get('number','?')
            print(f'  {s} S{sn:02d}E{en:02d} (id: {ep["id"]})')
        if len(episodes)>5: print(f'  ... and {len(episodes)-5} more\n')

    hist_ids = [i['id'] for i in episodes + movies]
    ep_ids = [i['episode']['ids']['trakt'] for i in episodes if i.get('episode',{}).get('ids',{}).get('trakt')]
    mv_ids = [i['movie']['ids']['trakt'] for i in movies if i.get('movie',{}).get('ids',{}).get('trakt')]

    print(f'Step 2: Removing {len(hist_ids)} history entries...')
    removed = remove_history(hist_ids)
    print(f'Removed: {removed}\n')

    print(f'Step 3: Re-adding {len(ep_ids)} episodes without date...')
    added = add_without_date(ep_ids, 'episodes')
    print(f'Re-added: {added} episodes\n')

    if mv_ids:
        print(f'Step 3b: Re-adding {len(mv_ids)} movies without date...')
        added_mv = add_without_date(mv_ids, 'movies')
        print(f'Re-added: {added_mv} movies\n')

    print(f'=== Done: {removed} removed, {added} episodes + {len(mv_ids)} movies re-added without dates ===')

if __name__ == '__main__':
    main()
