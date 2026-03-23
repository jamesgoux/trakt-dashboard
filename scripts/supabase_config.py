"""
Iris Supabase Configuration Helper
Used by pipeline scripts to interact with Supabase (staging or production).

Environment variables:
  SUPABASE_URL         - Project URL (e.g. https://xxxxx.supabase.co)
  SUPABASE_ANON_KEY    - Public anon key (for client-side auth)
  SUPABASE_SERVICE_KEY  - Service role key (for server-side admin ops)

Usage:
  from supabase_config import get_client, get_admin_client, get_user_config

  # Public client (respects RLS)
  client = get_client()

  # Admin client (bypasses RLS, for pipeline scripts)
  admin = get_admin_client()

  # Get user's integration config
  config = get_user_config(admin, username='jamesgoux', service='trakt')
"""

import os
import json
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')


def _headers(key, extra=None):
    """Standard Supabase REST headers."""
    h = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }
    if extra:
        h.update(extra)
    return h


def _rest_url(table):
    return f'{SUPABASE_URL}/rest/v1/{table}'


def _storage_url(path=''):
    return f'{SUPABASE_URL}/storage/v1{path}'


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

class SupabaseClient:
    """Lightweight Supabase REST client (no SDK dependency)."""

    def __init__(self, url, key):
        self.url = url
        self.key = key

    def select(self, table, query_params=None):
        """SELECT from table. query_params is a dict of PostgREST filters."""
        r = requests.get(
            f'{self.url}/rest/v1/{table}',
            headers=_headers(self.key),
            params=query_params or {},
        )
        r.raise_for_status()
        return r.json()

    def insert(self, table, data):
        """INSERT row(s) into table."""
        r = requests.post(
            f'{self.url}/rest/v1/{table}',
            headers=_headers(self.key),
            json=data if isinstance(data, list) else [data],
        )
        r.raise_for_status()
        return r.json()

    def update(self, table, data, query_params):
        """UPDATE rows matching query_params."""
        r = requests.patch(
            f'{self.url}/rest/v1/{table}',
            headers=_headers(self.key),
            params=query_params,
            json=data,
        )
        r.raise_for_status()
        return r.json()

    def upsert(self, table, data):
        """UPSERT (insert or update on conflict)."""
        r = requests.post(
            f'{self.url}/rest/v1/{table}',
            headers=_headers(self.key, {'Prefer': 'resolution=merge-duplicates,return=representation'}),
            json=data if isinstance(data, list) else [data],
        )
        r.raise_for_status()
        return r.json()

    def rpc(self, function_name, params=None):
        """Call a Supabase Edge Function or database function."""
        r = requests.post(
            f'{self.url}/rest/v1/rpc/{function_name}',
            headers=_headers(self.key),
            json=params or {},
        )
        r.raise_for_status()
        return r.json()

    def upload_file(self, bucket, path, data, content_type='application/json'):
        """Upload a file to Supabase Storage."""
        r = requests.post(
            f'{self.url}/storage/v1/object/{bucket}/{path}',
            headers={
                'apikey': self.key,
                'Authorization': f'Bearer {self.key}',
                'Content-Type': content_type,
                'x-upsert': 'true',
            },
            data=data if isinstance(data, bytes) else data.encode('utf-8'),
        )
        r.raise_for_status()
        return r.json()

    def download_file(self, bucket, path):
        """Download a file from Supabase Storage."""
        r = requests.get(
            f'{self.url}/storage/v1/object/{bucket}/{path}',
            headers={
                'apikey': self.key,
                'Authorization': f'Bearer {self.key}',
            },
        )
        r.raise_for_status()
        return r.content

    def get_public_url(self, bucket, path):
        """Get public URL for a file in a public bucket."""
        return f'{self.url}/storage/v1/object/public/{bucket}/{path}'


def get_client():
    """Get a public client (respects RLS, uses anon key)."""
    assert SUPABASE_URL, 'SUPABASE_URL not set'
    assert SUPABASE_ANON_KEY, 'SUPABASE_ANON_KEY not set'
    return SupabaseClient(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_admin_client():
    """Get an admin client (bypasses RLS, uses service role key)."""
    assert SUPABASE_URL, 'SUPABASE_URL not set'
    assert SUPABASE_SERVICE_KEY, 'SUPABASE_SERVICE_KEY not set'
    return SupabaseClient(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------------------------------------------------------------------
# Convenience functions for pipeline scripts
# ---------------------------------------------------------------------------

def get_user_config(client, username=None, user_id=None, service=None):
    """
    Get a user's integration config.

    Args:
        client: SupabaseClient (admin recommended)
        username: lookup by username (requires join)
        user_id: lookup by user_id directly
        service: filter to specific service

    Returns:
        dict or list of integration configs
    """
    if username and not user_id:
        profiles = client.select('profiles', {'username': f'eq.{username}', 'select': 'id'})
        if not profiles:
            raise ValueError(f'No profile found for username: {username}')
        user_id = profiles[0]['id']

    params = {'user_id': f'eq.{user_id}'}
    if service:
        params['service'] = f'eq.{service}'

    rows = client.select('integrations', params)
    if service:
        return rows[0]['config'] if rows else None
    return {r['service']: r['config'] for r in rows}


def get_all_users(client):
    """Get all user profiles (admin client recommended)."""
    return client.select('profiles', {'select': 'id,username,timezone,is_public'})


def upload_user_data(client, user_id, filename, data):
    """
    Upload a user's data file to Supabase Storage.

    Args:
        client: SupabaseClient (admin or authenticated)
        user_id: UUID string
        filename: e.g. 'dashboard.json', 'trakt.json'
        data: string or bytes
    """
    path = f'{user_id}/{filename}'
    return client.upload_file('user-data', path, data)


def download_user_data(client, user_id, filename):
    """Download a user's data file from Supabase Storage."""
    path = f'{user_id}/{filename}'
    return client.download_file('user-data', path)
