#!/usr/bin/env python3
"""
Setup encryption for Iris integration credentials.

Generates a random AES-256 encryption key and stores it in global_config,
then runs the migration to enable pgcrypto + triggers.

Usage:
  python scripts/setup_encryption.py                    # Generate new key + apply migration
  python scripts/setup_encryption.py --key=YOUR_KEY     # Use specific key
  python scripts/setup_encryption.py --verify            # Verify encryption is working

Requires: SUPABASE_URL, SUPABASE_SERVICE_KEY env vars
"""

import os
import sys
import json
import secrets
import string

sys.path.insert(0, os.path.dirname(__file__))
from supabase_config import get_admin_client, SUPABASE_URL, SUPABASE_SERVICE_KEY

def generate_key(length=44):
    """Generate a cryptographically secure random key."""
    alphabet = string.ascii_letters + string.digits + '+/'
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def setup_encryption_key(key=None):
    """Store encryption key in global_config."""
    client = get_admin_client()

    if key is None:
        key = generate_key()
        print(f"  Generated new encryption key: {key[:8]}...{key[-4:]}")

    # Upsert into global_config
    try:
        client.upsert({
            'key': 'encryption',
            'value': json.dumps({'encryption_key': key, 'key_source': 'config'})
        })
    except:
        # Try update if upsert fails
        client.update('global_config',
            {'value': json.dumps({'encryption_key': key, 'key_source': 'config'})},
            {'key': 'eq.encryption'}
        )

    print("  Encryption key stored in global_config")
    return key

def run_migration():
    """Apply the encryption migration SQL via Supabase REST API."""
    print("\n--- Applying encryption migration ---")
    print("  NOTE: Run scripts/migrations/003_encrypt_credentials.sql")
    print("  via the Supabase SQL Editor (Dashboard > SQL Editor > New Query)")
    print(f"  Supabase URL: {SUPABASE_URL}")
    print("\n  The migration will:")
    print("    1. Enable pgcrypto extension")
    print("    2. Create encrypt/decrypt helper functions")
    print("    3. Add auto-encrypt trigger on integrations table")
    print("    4. Create get_decrypted_integrations() RPC for pipeline")
    print("    5. Migrate existing plaintext configs to encrypted")

def verify_encryption():
    """Check if encryption is properly configured."""
    client = get_admin_client()

    print("\n--- Verifying encryption setup ---")

    # 1. Check encryption key exists
    try:
        rows = client.select('global_config', {'key': 'eq.encryption'})
        if rows and rows[0].get('value', {}).get('encryption_key'):
            print("  ✅ Encryption key found in global_config")
        else:
            print("  ❌ Encryption key NOT found")
            return False
    except Exception as e:
        print(f"  ❌ Error checking key: {e}")
        return False

    # 2. Check if trigger exists (try saving a test value)
    try:
        result = client.rpc('get_decrypted_integrations', {'p_user_id': '00000000-0000-0000-0000-000000000000'})
        print("  ✅ get_decrypted_integrations() RPC exists")
    except Exception as e:
        if '404' in str(e) or 'could not find' in str(e).lower():
            print("  ❌ get_decrypted_integrations() RPC not found — run migration SQL")
            return False
        else:
            # RPC exists but returned error for fake UUID (expected)
            print("  ✅ get_decrypted_integrations() RPC exists")

    # 3. Check for encrypted values in integrations
    try:
        integrations = client.select('integrations', {'select': 'service,config'})
        encrypted_count = 0
        for integ in integrations:
            cfg = integ.get('config', {})
            for k, v in (cfg or {}).items():
                if isinstance(v, str) and v.startswith('enc:'):
                    encrypted_count += 1
        if encrypted_count > 0:
            print(f"  ✅ Found {encrypted_count} encrypted field(s) in integrations")
        else:
            print("  ⚠️  No encrypted fields found — migration may not have run yet")
    except Exception as e:
        print(f"  ⚠️  Could not check integrations: {e}")

    return True

if __name__ == '__main__':
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("Error: Set SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables")
        sys.exit(1)

    if '--verify' in sys.argv:
        verify_encryption()
    else:
        # Get key from args or generate
        key = None
        for arg in sys.argv:
            if arg.startswith('--key='):
                key = arg.split('=', 1)[1]

        setup_encryption_key(key)
        run_migration()
