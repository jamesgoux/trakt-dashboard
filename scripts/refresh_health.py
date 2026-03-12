#!/usr/bin/env python3
"""
Fetch health data from jamesgoux/health (private Hadge repo) via GitHub API.
Outputs flat workout array to data/health.json (consumed by refresh_data.py).

Requires GH_HEALTH_TOKEN environment variable (PAT with repo scope).
"""
import os, sys, json, csv, io, base64
try:
    import requests
except ImportError:
    print("ERROR: requests not installed"); sys.exit(1)

TOKEN = os.environ.get('GH_HEALTH_TOKEN', '')
REPO = 'jamesgoux/health'
API = 'https://api.github.com'
HEADERS = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'health.json')

def fetch_csv(path):
    r = requests.get(f'{API}/repos/{REPO}/contents/{path}', headers=HEADERS)
    if r.status_code != 200: return []
    return list(csv.DictReader(io.StringIO(base64.b64decode(r.json()['content']).decode('utf-8'))))

def fetch_dir(path):
    r = requests.get(f'{API}/repos/{REPO}/contents/{path}', headers=HEADERS)
    if r.status_code != 200: return []
    return [f['name'] for f in r.json() if f['name'].endswith('.csv')]

def main():
    if not TOKEN: print('ERROR: GH_HEALTH_TOKEN must be set'); sys.exit(1)
    print('Fetching health data from Hadge...')

    workouts = []
    for f in sorted(fetch_dir('workouts')):
        print(f'  workouts/{f}...')
        for r in fetch_csv(f'workouts/{f}'):
            try:
                start = r.get('Start Date', '')
                workouts.append({
                    'date': start[:10],
                    'type': r.get('Name', 'Unknown'),
                    'dur': round(float(r.get('Duration', 0) or 0)),
                    'dist': round(float(r.get('Distance', 0) or 0)),
                    'cal': round(float(r.get('Total Energy', 0) or 0)),
                    'elev': round(float(r.get('Elevation Ascended', 0) or 0)),
                })
            except (ValueError, TypeError): continue
    workouts.sort(key=lambda w: w['date'], reverse=True)
    print(f'  Total: {len(workouts)} workouts')

    with open(OUT, 'w') as f:
        json.dump(workouts, f, separators=(',', ':'))
    print(f'Saved to {OUT} ({os.path.getsize(OUT):,} bytes)')

if __name__ == '__main__':
    main()
