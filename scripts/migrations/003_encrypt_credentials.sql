-- Migration 003: Encrypt sensitive integration credentials at rest
-- Uses pgcrypto with AES-256 symmetric encryption via pgp_sym_encrypt/decrypt
-- Encryption key stored in vault.secrets (Supabase Vault)

-- ============================================================
-- 1. Enable pgcrypto extension
-- ============================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- 2. Store encryption key in a config table (for non-Vault envs)
--    In production, prefer Supabase Vault (vault.secrets)
-- ============================================================
INSERT INTO global_config (key, value)
VALUES ('encryption', '{"key_source": "config"}')
ON CONFLICT (key) DO NOTHING;

-- NOTE: The actual encryption key is set via:
--   UPDATE global_config SET value = jsonb_set(value, '{encryption_key}', '"YOUR_KEY_HERE"')
--   WHERE key = 'encryption';
-- Or via Supabase Vault: SELECT vault.create_secret('iris_encryption_key', 'YOUR_KEY_HERE');

-- ============================================================
-- 3. Helper function: get encryption key
-- ============================================================
CREATE OR REPLACE FUNCTION _iris_get_encryption_key()
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  enc_key TEXT;
BEGIN
  -- Try Supabase Vault first
  BEGIN
    SELECT decrypted_secret INTO enc_key
    FROM vault.decrypted_secrets
    WHERE name = 'iris_encryption_key'
    LIMIT 1;
  EXCEPTION WHEN OTHERS THEN
    enc_key := NULL;
  END;

  -- Fallback to global_config
  IF enc_key IS NULL THEN
    SELECT value->>'encryption_key' INTO enc_key
    FROM global_config
    WHERE key = 'encryption';
  END IF;

  IF enc_key IS NULL THEN
    RAISE EXCEPTION 'Encryption key not configured. Set via Vault or global_config.';
  END IF;

  RETURN enc_key;
END;
$$;

-- ============================================================
-- 4. Define which fields are sensitive per service
-- ============================================================
CREATE OR REPLACE FUNCTION _iris_sensitive_fields(service_name TEXT)
RETURNS TEXT[]
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
  RETURN CASE service_name
    WHEN 'pocketcasts' THEN ARRAY['password']
    WHEN 'serializd'   THEN ARRAY['password']
    WHEN 'bgg'         THEN ARRAY['password']
    WHEN 'health'      THEN ARRAY['github_token']
    WHEN 'trakt'       THEN ARRAY['access_token', 'refresh_token']
    WHEN 'lastfm'      THEN ARRAY['api_key']
    WHEN 'setlistfm'   THEN ARRAY['api_key']
    ELSE ARRAY[]::TEXT[]
  END;
END;
$$;

-- ============================================================
-- 5. Encrypt sensitive fields in a config JSONB
-- ============================================================
CREATE OR REPLACE FUNCTION _iris_encrypt_config(service_name TEXT, config JSONB)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  enc_key TEXT;
  fields TEXT[];
  field_name TEXT;
  result JSONB;
  raw_val TEXT;
BEGIN
  fields := _iris_sensitive_fields(service_name);
  IF array_length(fields, 1) IS NULL THEN
    RETURN config;  -- No sensitive fields for this service
  END IF;

  enc_key := _iris_get_encryption_key();
  result := config;

  FOREACH field_name IN ARRAY fields LOOP
    raw_val := config->>field_name;
    IF raw_val IS NOT NULL AND raw_val != '' AND LEFT(raw_val, 4) != 'enc:' THEN
      -- Encrypt and prefix with 'enc:' marker
      result := jsonb_set(
        result,
        ARRAY[field_name],
        to_jsonb('enc:' || encode(pgp_sym_encrypt(raw_val, enc_key), 'base64'))
      );
    END IF;
  END LOOP;

  RETURN result;
END;
$$;

-- ============================================================
-- 6. Decrypt sensitive fields in a config JSONB
-- ============================================================
CREATE OR REPLACE FUNCTION _iris_decrypt_config(service_name TEXT, config JSONB)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  enc_key TEXT;
  fields TEXT[];
  field_name TEXT;
  result JSONB;
  enc_val TEXT;
BEGIN
  fields := _iris_sensitive_fields(service_name);
  IF array_length(fields, 1) IS NULL THEN
    RETURN config;  -- No sensitive fields for this service
  END IF;

  enc_key := _iris_get_encryption_key();
  result := config;

  FOREACH field_name IN ARRAY fields LOOP
    enc_val := config->>field_name;
    IF enc_val IS NOT NULL AND LEFT(enc_val, 4) = 'enc:' THEN
      -- Strip 'enc:' prefix, decode base64, decrypt
      result := jsonb_set(
        result,
        ARRAY[field_name],
        to_jsonb(pgp_sym_decrypt(decode(substring(enc_val FROM 5), 'base64'), enc_key))
      );
    END IF;
  END LOOP;

  RETURN result;
END;
$$;

-- ============================================================
-- 7. Trigger: auto-encrypt on INSERT or UPDATE
-- ============================================================
CREATE OR REPLACE FUNCTION _iris_encrypt_integration_trigger()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  -- Only encrypt if config has content
  IF NEW.config IS NOT NULL AND NEW.config != '{}'::jsonb THEN
    NEW.config := _iris_encrypt_config(NEW.service, NEW.config);
  END IF;
  RETURN NEW;
END;
$$;

-- Drop existing trigger if any, then create
DROP TRIGGER IF EXISTS encrypt_integration_config ON integrations;
CREATE TRIGGER encrypt_integration_config
  BEFORE INSERT OR UPDATE OF config ON integrations
  FOR EACH ROW
  EXECUTE FUNCTION _iris_encrypt_integration_trigger();

-- ============================================================
-- 8. RPC function: get decrypted integrations for a user
--    Called by pipeline (service key) — not exposed to anon
-- ============================================================
CREATE OR REPLACE FUNCTION get_decrypted_integrations(p_user_id UUID)
RETURNS TABLE(service TEXT, config JSONB, is_enabled BOOLEAN, last_sync_at TIMESTAMPTZ, last_error TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY
    SELECT
      i.service,
      _iris_decrypt_config(i.service, i.config) AS config,
      i.is_enabled,
      i.last_sync_at,
      i.last_error
    FROM integrations i
    WHERE i.user_id = p_user_id
      AND i.is_enabled = true;
END;
$$;

-- Only service_role can call this (pipeline / admin)
REVOKE EXECUTE ON FUNCTION get_decrypted_integrations(UUID) FROM public;
REVOKE EXECUTE ON FUNCTION get_decrypted_integrations(UUID) FROM anon;
REVOKE EXECUTE ON FUNCTION get_decrypted_integrations(UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION get_decrypted_integrations(UUID) TO service_role;

-- ============================================================
-- 9. RPC function: check if a field is encrypted (for UI)
--    Returns field names that have encrypted values
-- ============================================================
CREATE OR REPLACE FUNCTION get_encrypted_field_status(p_user_id UUID, p_service TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  cfg JSONB;
  fields TEXT[];
  field_name TEXT;
  result JSONB := '{}';
  val TEXT;
BEGIN
  SELECT i.config INTO cfg
  FROM integrations i
  WHERE i.user_id = p_user_id AND i.service = p_service;

  IF cfg IS NULL THEN RETURN result; END IF;

  fields := _iris_sensitive_fields(p_service);
  FOREACH field_name IN ARRAY fields LOOP
    val := cfg->>field_name;
    result := jsonb_set(result, ARRAY[field_name],
      to_jsonb(val IS NOT NULL AND LEFT(val, 4) = 'enc:'));
  END LOOP;

  RETURN result;
END;
$$;

-- ============================================================
-- 10. Migrate existing plaintext credentials
-- ============================================================
-- This encrypts all existing integration configs in-place.
-- The trigger handles the actual encryption.
-- We force an UPDATE to fire the trigger on each row.
DO $$
DECLARE
  rec RECORD;
BEGIN
  -- Check if encryption key exists before migrating
  PERFORM _iris_get_encryption_key();

  FOR rec IN
    SELECT id, service, config FROM integrations
    WHERE config IS NOT NULL AND config != '{}'::jsonb
  LOOP
    UPDATE integrations
    SET config = rec.config, updated_at = now()
    WHERE id = rec.id;
  END LOOP;

  RAISE NOTICE 'Migrated existing integration configs to encrypted storage';
EXCEPTION
  WHEN OTHERS THEN
    RAISE NOTICE 'Skipping migration — encryption key not yet configured. Run migration again after setting the key.';
END;
$$;
