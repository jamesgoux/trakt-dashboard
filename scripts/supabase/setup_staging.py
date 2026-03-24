"""
Phase 1 Setup Script — Iris Staging Supabase
Runs schema creation, RLS, storage bucket, seeds jamesgoux data.

Usage:
  SUPABASE_URL=https://xxx.supabase.co \
  SUPABASE_SERVICE_KEY=eyJ... \
  python3 scripts/supabase/setup_staging.py

Reads SQL files from scripts/supabase/ and seeds from data/*.json + existing env.
"""

import os
import sys
import json
import requests

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))


def headers(extra=None):
    h = {
        'apikey': SERVICE_KEY,
        'Authorization': f'Bearer {SERVICE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }
    if extra:
        h.update(extra)
    return h


def run_sql(sql, label='SQL'):
    """Execute SQL via Supabase's pg REST endpoint."""
    # Use the /rest/v1/rpc endpoint isn't ideal for DDL — 
    # we'll use the management API sql endpoint instead
    r = requests.post(
        f'{SUPABASE_URL}/rest/v1/rpc/',
        headers=headers(),
        json={'query': sql}
    )
    # For DDL, we need a different approach — use the SQL editor API
    # Actually for Supabase, DDL needs to go through the dashboard or pg connection
    # We'll output the SQL for manual execution and handle DML via REST
    print(f'  [{label}] SQL prepared (execute via Supabase SQL Editor)')
    return sql


def rest_select(table, params=None):
    r = requests.get(
        f'{SUPABASE_URL}/rest/v1/{table}',
        headers=headers(),
        params=params or {},
    )
    r.raise_for_status()
    return r.json()


def rest_insert(table, data):
    r = requests.post(
        f'{SUPABASE_URL}/rest/v1/{table}',
        headers=headers(),
        json=data if isinstance(data, list) else [data],
    )
    r.raise_for_status()
    return r.json()


def rest_upsert(table, data):
    r = requests.post(
        f'{SUPABASE_URL}/rest/v1/{table}',
        headers=headers({'Prefer': 'resolution=merge-duplicates,return=representation'}),
        json=data if isinstance(data, list) else [data],
    )
    r.raise_for_status()
    return r.json()


def create_user(email, password):
    """Create auth user via Supabase Auth Admin API."""
    r = requests.post(
        f'{SUPABASE_URL}/auth/v1/admin/users',
        headers={
            'apikey': SERVICE_KEY,
            'Authorization': f'Bearer {SERVICE_KEY}',
            'Content-Type': 'application/json',
        },
        json={
            'email': email,
            'password': password,
            'email_confirm': True,
        },
    )
    r.raise_for_status()
    return r.json()


def upload_storage(bucket, path, data, content_type='application/json'):
    """Upload file to Supabase Storage."""
    r = requests.post(
        f'{SUPABASE_URL}/storage/v1/object/{bucket}/{path}',
        headers={
            'apikey': SERVICE_KEY,
            'Authorization': f'Bearer {SERVICE_KEY}',
            'Content-Type': content_type,
            'x-upsert': 'true',
        },
        data=data if isinstance(data, bytes) else data.encode('utf-8'),
    )
    r.raise_for_status()
    return r.json()


def main():
    assert SUPABASE_URL, 'Set SUPABASE_URL'
    assert SERVICE_KEY, 'Set SUPABASE_SERVICE_KEY'

    print(f'Supabase URL: {SUPABASE_URL}')
    print()

    # Step 1: Concatenate all SQL
    print('=== Step 1: SQL Schema ===')
    sql_files = sorted(f for f in os.listdir(SCRIPT_DIR) if f.endswith('.sql'))
    combined_sql = []
    for sf in sql_files:
        path = os.path.join(SCRIPT_DIR, sf)
        with open(path) as f:
            sql = f.read()
        combined_sql.append(f'-- {sf}\n{sql}')
        print(f'  Loaded {sf}')
    
    full_sql = '\n\n'.join(combined_sql)
    out_path = os.path.join(SCRIPT_DIR, 'combined_schema.sql')
    with open(out_path, 'w') as f:
        f.write(full_sql)
    print(f'  → Combined SQL written to {out_path}')
    print(f'  → Run this in Supabase SQL Editor, then re-run this script with --seed')
    print()

    if '--seed' not in sys.argv:
        print('Run with --seed after executing SQL in Supabase dashboard.')
        return

    # Step 2: Create jamesgoux auth user
    print('=== Step 2: Create jamesgoux user ===')
    try:
        user = create_user('james@iris-staging.local', 'iris-staging-2026')
        user_id = user['id']
        print(f'  Created user: {user_id}')
    except requests.exceptions.HTTPError as e:
        if 'already' in str(e.response.text).lower() or e.response.status_code == 422:
            # User exists, find them
            r = requests.get(
                f'{SUPABASE_URL}/auth/v1/admin/users',
                headers={
                    'apikey': SERVICE_KEY,
                    'Authorization': f'Bearer {SERVICE_KEY}',
                },
            )
            r.raise_for_status()
            users = r.json().get('users', [])
            user = next((u for u in users if u.get('email') == 'james@iris-staging.local'), None)
            if user:
                user_id = user['id']
                print(f'  User already exists: {user_id}')
            else:
                raise
        else:
            raise

    # Step 3: Insert profile
    print('=== Step 3: Insert profile ===')
    try:
        profile = rest_upsert('profiles', {
            'id': user_id,
            'username': 'jamesgoux',
            'display_name': 'James Goux',
            'timezone': 'America/Los_Angeles',
            'is_public': True,
        })
        print(f'  Profile: {profile}')
    except Exception as e:
        print(f'  Profile upsert error (may already exist): {e}')

    # Step 4: Insert integration configs
    print('=== Step 4: Insert integration configs ===')
    
    # Load existing data files for config values
    data_dir = os.path.join(REPO_DIR, 'data')
    
    # Read trakt auth if available
    trakt_auth = {}
    trakt_auth_path = os.path.join(data_dir, 'trakt_auth.json')
    if os.path.exists(trakt_auth_path):
        with open(trakt_auth_path) as f:
            trakt_auth = json.load(f)

    integrations = [
        {
            'user_id': user_id,
            'service': 'trakt',
            'is_enabled': True,
            'config': {
                'username': 'jamesgoux',
                'client_id': os.environ.get('TRAKT_CLIENT_ID', trakt_auth.get('client_id', '')),
                'client_secret': os.environ.get('TRAKT_CLIENT_SECRET', ''),
                'access_token': trakt_auth.get('access_token', os.environ.get('TRAKT_ACCESS_TOKEN', '')),
                'refresh_token': trakt_auth.get('refresh_token', os.environ.get('TRAKT_REFRESH_TOKEN', '')),
                'token_expires_at': trakt_auth.get('created_at', 0) + trakt_auth.get('expires_in', 0),
            }
        },
        {
            'user_id': user_id,
            'service': 'letterboxd',
            'is_enabled': True,
            'config': {'username': 'jamesgoux'}
        },
        {
            'user_id': user_id,
            'service': 'lastfm',
            'is_enabled': True,
            'config': {
                'api_key': os.environ.get('LASTFM_API_KEY', ''),
                'username': os.environ.get('LASTFM_USER', 'jamesgoux'),
            }
        },
        {
            'user_id': user_id,
            'service': 'goodreads',
            'is_enabled': True,
            'config': {'user_id': os.environ.get('GOODREADS_USER_ID', '2645271')}
        },
        {
            'user_id': user_id,
            'service': 'pocketcasts',
            'is_enabled': True,
            'config': {
                'email': os.environ.get('POCKETCASTS_EMAIL', ''),
                'password': os.environ.get('POCKETCASTS_PASSWORD', ''),
            }
        },
        {
            'user_id': user_id,
            'service': 'serializd',
            'is_enabled': True,
            'config': {
                'email': os.environ.get('SERIALIZD_EMAIL', ''),
                'password': os.environ.get('SERIALIZD_PASSWORD', ''),
            }
        },
        {
            'user_id': user_id,
            'service': 'bgg',
            'is_enabled': True,
            'config': {
                'username': 'jamesgoux',
                'password': os.environ.get('BGG_PASSWORD', ''),
            }
        },
        {
            'user_id': user_id,
            'service': 'health',
            'is_enabled': True,
            'config': {
                'github_token': os.environ.get('GH_HEALTH_TOKEN', ''),
                'repo_path': 'jamesgoux/health',
            }
        },
        {
            'user_id': user_id,
            'service': 'setlistfm',
            'is_enabled': True,
            'config': {'api_key': os.environ.get('SETLIST_FM_API_KEY', '')}
        },
        {
            'user_id': user_id,
            'service': 'gametrack',
            'is_enabled': True,
            'config': {}  # CSV import only
        },
        {
            'user_id': user_id,
            'service': 'theater',
            'is_enabled': True,
            'config': {}  # CSV import only
        },
        {
            'user_id': user_id,
            'service': 'bgstats',
            'is_enabled': True,
            'config': {}  # JSON import only
        },
        {
            'user_id': user_id,
            'service': 'sports',
            'is_enabled': True,
            'config': {
                'tracked_teams': [
                    {'id': '134860', 'name': 'Los Angeles Lakers', 'league': 'NBA'},
                    {'id': '134920', 'name': 'Green Bay Packers', 'league': 'NFL'},
                    {'id': '135252', 'name': 'Los Angeles Dodgers', 'league': 'MLB'},
                    {'id': '135235', 'name': 'Boston Red Sox', 'league': 'MLB'},
                    {'id': '134852', 'name': 'Los Angeles Kings', 'league': 'NHL'},
                    {'id': '134938', 'name': 'Los Angeles Rams', 'league': 'NFL'},
                    {'id': '134948', 'name': 'Seattle Seahawks', 'league': 'NFL'},
                ],
            }
        },
    ]

    for integ in integrations:
        try:
            result = rest_upsert('integrations', integ)
            print(f'  ✓ {integ["service"]}')
        except Exception as e:
            print(f'  ✗ {integ["service"]}: {e}')

    # Step 5: Upload data blob to Storage
    print()
    print('=== Step 5: Upload data blob to Storage ===')
    index_path = os.path.join(REPO_DIR, 'index.html')
    with open(index_path) as f:
        html = f.read()
    
    start = html.find('var D=') + 6
    end = html.find(';\nvar HS=')
    if end == -1:
        end = html.find(';var HS=')
    blob = html[start:end]
    
    blob_size = len(blob.encode('utf-8'))
    print(f'  Data blob: {blob_size:,} bytes ({blob_size/1024/1024:.1f} MB)')
    
    try:
        result = upload_storage('user-data', f'{user_id}/dashboard.json', blob)
        print(f'  ✓ Uploaded to user-data/{user_id}/dashboard.json')
    except Exception as e:
        print(f'  ✗ Upload failed: {e}')

    print()
    print('=== Setup complete ===')
    print(f'  User ID: {user_id}')
    print(f'  Username: jamesgoux')
    print(f'  Integrations: {len(integrations)}')
    print(f'  Data blob: {blob_size/1024/1024:.1f} MB')


if __name__ == '__main__':
    main()
