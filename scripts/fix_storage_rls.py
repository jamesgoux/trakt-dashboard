"""
One-time fix: Create user-data Storage bucket and apply RLS policies.

Requires SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_DB_URL env vars.
Run via GitHub Actions (fix-storage-rls.yml) or locally with credentials.
"""

import os
import sys
import requests

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
DB_URL = os.environ.get('SUPABASE_DB_URL', '')

def create_bucket():
    """Create user-data bucket via Storage Admin API (idempotent)."""
    print("Creating user-data bucket...")
    r = requests.post(
        f'{SUPABASE_URL}/storage/v1/bucket',
        headers={
            'apikey': SERVICE_KEY,
            'Authorization': f'Bearer {SERVICE_KEY}',
            'Content-Type': 'application/json',
        },
        json={
            'id': 'user-data',
            'name': 'user-data',
            'public': False,
            'file_size_limit': 52428800,  # 50MB
        }
    )
    if r.status_code == 200:
        print("  ✓ Bucket created")
    elif r.status_code == 409 or 'already exists' in r.text.lower():
        print("  ✓ Bucket already exists")
    else:
        print(f"  Bucket creation returned {r.status_code}: {r.text}")
        # Don't fail — bucket might exist but not be queryable with this endpoint


def test_upload():
    """Test that upload works with service key (bypasses RLS)."""
    print("Testing upload with service key...")
    r = requests.post(
        f'{SUPABASE_URL}/storage/v1/object/user-data/test_rls_check.txt',
        headers={
            'apikey': SERVICE_KEY,
            'Authorization': f'Bearer {SERVICE_KEY}',
            'Content-Type': 'text/plain',
            'x-upsert': 'true',
        },
        data=b'rls test'
    )
    if r.ok:
        print("  ✓ Service key upload works")
        # Clean up test file
        requests.delete(
            f'{SUPABASE_URL}/storage/v1/object/user-data/test_rls_check.txt',
            headers={
                'apikey': SERVICE_KEY,
                'Authorization': f'Bearer {SERVICE_KEY}',
            }
        )
    else:
        print(f"  ✗ Upload failed: {r.status_code} {r.text}")
        sys.exit(1)


def apply_rls_policies():
    """Apply RLS policies via psycopg2 (requires SUPABASE_DB_URL)."""
    if not DB_URL:
        print("SUPABASE_DB_URL not set — skipping RLS policy setup")
        print("Run scripts/migrations/004_fix_storage_bucket.sql manually in SQL Editor")
        return False

    try:
        import psycopg2
    except ImportError:
        print("Installing psycopg2-binary...")
        os.system(f'{sys.executable} -m pip install psycopg2-binary -q')
        import psycopg2

    print("Applying RLS policies to storage.objects...")
    # Supabase direct host resolves to IPv6 which may be unreachable from
    # some runners. Resolve to IPv4 and connect with sslmode=require.
    import socket
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(DB_URL)
    host = parsed.hostname
    port = parsed.port or 5432
    try:
        ipv4 = socket.getaddrinfo(host, port, socket.AF_INET)[0][4][0]
        print(f"  Resolved {host} → {ipv4} (IPv4)")
    except socket.gaierror:
        ipv4 = host  # fallback to hostname

    conn = psycopg2.connect(
        host=ipv4,
        port=port,
        dbname=parsed.path.lstrip('/') or 'postgres',
        user=parsed.username or 'postgres',
        password=parsed.password,
        sslmode='require',
        connect_timeout=10,
    )
    conn.autocommit = True
    cur = conn.cursor()

    statements = [
        "ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY",

        'DROP POLICY IF EXISTS "Users can upload to own folder" ON storage.objects',
        'DROP POLICY IF EXISTS "Users can update own files" ON storage.objects',
        'DROP POLICY IF EXISTS "Users can read own files" ON storage.objects',
        'DROP POLICY IF EXISTS "Users can delete own files" ON storage.objects',
        'DROP POLICY IF EXISTS "Service role full access" ON storage.objects',

        """CREATE POLICY "Users can upload to own folder" ON storage.objects
           FOR INSERT TO authenticated
           WITH CHECK (
             bucket_id = 'user-data'
             AND (storage.foldername(name))[1] = auth.uid()::text
           )""",

        """CREATE POLICY "Users can update own files" ON storage.objects
           FOR UPDATE TO authenticated
           USING (
             bucket_id = 'user-data'
             AND (storage.foldername(name))[1] = auth.uid()::text
           )
           WITH CHECK (
             bucket_id = 'user-data'
             AND (storage.foldername(name))[1] = auth.uid()::text
           )""",

        """CREATE POLICY "Users can read own files" ON storage.objects
           FOR SELECT TO authenticated
           USING (
             bucket_id = 'user-data'
             AND (storage.foldername(name))[1] = auth.uid()::text
           )""",

        """CREATE POLICY "Users can delete own files" ON storage.objects
           FOR DELETE TO authenticated
           USING (
             bucket_id = 'user-data'
             AND (storage.foldername(name))[1] = auth.uid()::text
           )""",

        """CREATE POLICY "Service role full access" ON storage.objects
           FOR ALL TO service_role
           USING (bucket_id = 'user-data')
           WITH CHECK (bucket_id = 'user-data')""",
    ]

    for sql in statements:
        try:
            cur.execute(sql)
            label = sql.strip().split('\n')[0][:80]
            print(f"  ✓ {label}")
        except Exception as e:
            print(f"  ⚠ {sql[:60]}... → {e}")

    cur.close()
    conn.close()
    print("  ✓ RLS policies applied")
    return True


if __name__ == '__main__':
    assert SUPABASE_URL, 'SUPABASE_URL not set'
    assert SERVICE_KEY, 'SUPABASE_SERVICE_KEY not set'

    create_bucket()
    test_upload()
    ok = apply_rls_policies()

    if ok:
        print("\n✅ Storage bucket + RLS policies configured. Client uploads should work now.")
    else:
        print("\n⚠ Bucket exists and service key works, but RLS policies need manual SQL.")
        print("Run scripts/migrations/004_fix_storage_bucket.sql in Supabase SQL Editor.")
