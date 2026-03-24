"""
Iris Per-User Configuration Loader

Loads user credentials from Supabase integrations table, with env var fallback
for backward compatibility (jamesgoux on GitHub Actions).

Usage:
    from user_config import load_user_config
    cfg = load_user_config("jamesgoux")  # or from --user CLI arg
    trakt_token = cfg["trakt"]["access_token"]
    lastfm_key = cfg["lastfm"]["api_key"]
"""

import os
import json
import sys

# Try importing supabase_config (may not be available in all envs)
try:
    from supabase_config import get_admin_client, SUPABASE_URL, SUPABASE_SERVICE_KEY
    HAS_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)
except ImportError:
    HAS_SUPABASE = False


def _load_from_supabase(username):
    """Load user config from Supabase integrations table.

    Uses the get_decrypted_integrations() RPC to retrieve credentials
    with sensitive fields decrypted server-side. Falls back to direct
    table read if the RPC is not available (pre-migration).
    """
    client = get_admin_client()

    # Resolve username → user_id
    profiles = client.select("profiles", {"username": f"eq.{username}", "select": "id,timezone"})
    if not profiles:
        return None, None

    user_id = profiles[0]["id"]
    timezone = profiles[0].get("timezone", "America/Los_Angeles")

    # Fetch all integrations with decrypted credentials via RPC
    try:
        integrations = client.rpc("get_decrypted_integrations", {"p_user_id": user_id})
        print(f"  [user_config] Using encrypted credential storage (decrypted via RPC)")
    except Exception as e:
        # Fallback: direct table read (pre-migration or RPC not available)
        print(f"  [user_config] RPC unavailable ({e}), falling back to direct read")
        integrations = client.select("integrations", {
            "user_id": f"eq.{user_id}",
            "select": "service,config,is_enabled"
        })
        integrations = [i for i in integrations if i.get("is_enabled")]

    config = {"_user_id": user_id, "_username": username, "_timezone": timezone}
    for integ in integrations:
        if integ.get("is_enabled", True):
            config[integ["service"]] = integ["config"] or {}

    return config, user_id


def _load_from_env():
    """Load config from environment variables (backward compat for GH Actions)."""
    # Load trakt auth from file if available
    trakt_auth = {}
    if os.path.exists("data/trakt_auth.json"):
        try:
            with open("data/trakt_auth.json") as f:
                trakt_auth = json.load(f)
        except:
            pass
    
    return {
        "_user_id": None,
        "_username": os.environ.get("TRAKT_USERNAME", "jamesgoux"),
        "_timezone": "America/Los_Angeles",
        "trakt": {
            "username": os.environ.get("TRAKT_USERNAME", "jamesgoux"),
            "client_id": os.environ.get("TRAKT_CLIENT_ID", trakt_auth.get("client_id", "")),
            "client_secret": os.environ.get("TRAKT_CLIENT_SECRET", ""),
            "access_token": trakt_auth.get("access_token", os.environ.get("TRAKT_ACCESS_TOKEN", "")),
            "refresh_token": trakt_auth.get("refresh_token", os.environ.get("TRAKT_REFRESH_TOKEN", "")),
        },
        "letterboxd": {
            "username": os.environ.get("LETTERBOXD_USERNAME", os.environ.get("TRAKT_USERNAME", "jamesgoux")),
        },
        "lastfm": {
            "api_key": os.environ.get("LASTFM_API_KEY", ""),
            "username": os.environ.get("LASTFM_USER", "jamesgoux"),
        },
        "goodreads": {
            "user_id": os.environ.get("GOODREADS_USER_ID", ""),
        },
        "pocketcasts": {
            "email": os.environ.get("POCKETCASTS_EMAIL", ""),
            "password": os.environ.get("POCKETCASTS_PASSWORD", ""),
        },
        "serializd": {
            "email": os.environ.get("SERIALIZD_EMAIL", ""),
            "password": os.environ.get("SERIALIZD_PASSWORD", ""),
        },
        "bgg": {
            "username": os.environ.get("BGG_USERNAME", "jamesgoux"),
            "password": os.environ.get("BGG_PASSWORD", ""),
        },
        "setlistfm": {
            "api_key": os.environ.get("SETLIST_FM_API_KEY", ""),
        },
        "health": {
            "github_token": os.environ.get("GH_HEALTH_TOKEN", ""),
            "repo_path": "jamesgoux/health",
        },
        "sports": {
            "tracked_teams": [],  # loaded from data/sports_teams.json
        },
        # Shared/global keys (not per-user but needed by scripts)
        "_tmdb": {
            "api_key": os.environ.get("TMDB_API_KEY", ""),
            "bearer_token": os.environ.get("TMDB_BEARER_TOKEN", ""),
        },
    }


def load_user_config(username=None):
    """
    Load configuration for a user.
    
    Priority:
    1. If username provided and Supabase is configured → load from Supabase
    2. Fall back to environment variables (GH Actions backward compat)
    
    Returns:
        dict with keys per service + _user_id, _username, _timezone, _tmdb
    """
    # Parse --user from CLI args if not provided
    if username is None:
        for i, arg in enumerate(sys.argv):
            if arg == "--user" and i + 1 < len(sys.argv):
                username = sys.argv[i + 1]
            elif arg.startswith("--user="):
                username = arg.split("=", 1)[1]
    
    # Try Supabase first
    if username and HAS_SUPABASE:
        config, user_id = _load_from_supabase(username)
        if config:
            # Add shared/global keys
            config["_tmdb"] = {
                "api_key": os.environ.get("TMDB_API_KEY", ""),
                "bearer_token": os.environ.get("TMDB_BEARER_TOKEN", ""),
            }
            print(f"  [user_config] Loaded from Supabase for {username} (uid: {user_id[:8]}...)")
            return config
        else:
            print(f"  [user_config] User '{username}' not found in Supabase, falling back to env vars")
    
    # Fall back to env vars
    config = _load_from_env()
    if username:
        config["_username"] = username
    print(f"  [user_config] Loaded from env vars for {config['_username']}")
    return config


def get_data_dir(config):
    """Get the data directory for a user. For now, always 'data/'."""
    return "data"


def upload_user_data(config, filename, data_str):
    """Upload a data file to Supabase Storage for this user."""
    if not HAS_SUPABASE or not config.get("_user_id"):
        return False
    try:
        client = get_admin_client()
        path = f'{config["_user_id"]}/{filename}'
        client.upload_file("user-data", path, data_str)
        print(f"  [user_config] Uploaded {filename} to Supabase ({len(data_str)//1024}KB)")
        return True
    except Exception as e:
        print(f"  [user_config] Upload failed (non-fatal): {e}")
        return False


# Convenience: get a specific service config with defaults
def get_service(config, service, key=None, default=""):
    """Get a service config value. Returns default if not configured."""
    svc = config.get(service, {})
    if key:
        return svc.get(key, default)
    return svc
