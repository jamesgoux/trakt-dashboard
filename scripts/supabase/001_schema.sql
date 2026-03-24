-- ============================================
-- Iris Multi-User Schema — Phase 1
-- Run against iris-staging Supabase project
-- ============================================

-- 1. profiles: extends Supabase auth.users
CREATE TABLE IF NOT EXISTS profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT,
  timezone TEXT DEFAULT 'America/Los_Angeles',
  is_public BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER profiles_updated_at
  BEFORE UPDATE ON profiles
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 2. integrations: per-user service connections
CREATE TABLE IF NOT EXISTS integrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  service TEXT NOT NULL,
  is_enabled BOOLEAN DEFAULT true,
  config JSONB NOT NULL DEFAULT '{}',
  last_sync_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, service)
);

CREATE TRIGGER integrations_updated_at
  BEFORE UPDATE ON integrations
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 3. user_preferences: per-user settings
CREATE TABLE IF NOT EXISTS user_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value JSONB NOT NULL DEFAULT '{}',
  UNIQUE(user_id, key)
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_integrations_user_service ON integrations(user_id, service);
CREATE INDEX IF NOT EXISTS idx_user_preferences_user_key ON user_preferences(user_id, key);
CREATE INDEX IF NOT EXISTS idx_profiles_username ON profiles(username);
