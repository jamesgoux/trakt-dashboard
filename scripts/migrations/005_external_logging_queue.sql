-- Migration 005: External logging sync queues (Letterboxd + Serializd)
-- Adds queue tables for movie → Letterboxd and season-finale → Serializd sync jobs.
-- Extends encryption coverage to include letterboxd.password.

-- ============================================================
-- 1. Extend sensitive-fields registry to cover letterboxd.password
--    Existing migration 003 defined _iris_sensitive_fields().
--    Letterboxd moves from read-only (RSS, no creds) to write (scrape, needs password).
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
    WHEN 'letterboxd'  THEN ARRAY['password']      -- NEW in 005
    WHEN 'health'      THEN ARRAY['github_token']
    WHEN 'trakt'       THEN ARRAY['access_token', 'refresh_token']
    WHEN 'lastfm'      THEN ARRAY['api_key']
    WHEN 'setlistfm'   THEN ARRAY['api_key']
    ELSE ARRAY[]::TEXT[]
  END;
END;
$$;

-- Force re-encrypt of any existing plaintext letterboxd.password values
-- (safe no-op if no letterboxd integration row exists yet, or if already encrypted)
DO $$
BEGIN
  PERFORM _iris_get_encryption_key();
  UPDATE integrations
     SET config = config, updated_at = now()
   WHERE service = 'letterboxd'
     AND config ? 'password'
     AND LEFT(config->>'password', 4) <> 'enc:';
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'Skipping letterboxd re-encrypt — encryption key not yet configured.';
END $$;

-- ============================================================
-- 2. Shared helper: updated_at trigger function
--    (may already exist from earlier migrations, safe to redefine)
-- ============================================================
CREATE OR REPLACE FUNCTION _iris_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- ============================================================
-- 3. letterboxd_queue — movie diary sync queue
--    One row per movie log from Iris. Pipeline drains this into
--    Letterboxd via POST /s/save-diary-entry.
-- ============================================================
CREATE TABLE IF NOT EXISTS letterboxd_queue (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,

  -- Source identification (from Iris / Trakt)
  tmdb_id                INTEGER,          -- TMDB movie ID — primary lookup
  film_slug              TEXT,             -- Letterboxd slug (resolved at sync)
  letterboxd_film_id     INTEGER,          -- Letterboxd internal ID (cached after first resolve)
  title                  TEXT,             -- display/debug only
  year                   INTEGER,          -- display/debug only

  -- Rating payload
  rating_half_stars      SMALLINT CHECK (rating_half_stars IS NULL
                                         OR rating_half_stars BETWEEN 0 AND 10),
  liked                  BOOLEAN NOT NULL DEFAULT false,
  watched_date           DATE NOT NULL,
  review_text            TEXT,             -- typically null for movies (no prompt)
  tags                   JSONB NOT NULL DEFAULT '[]'::jsonb,  -- array of strings
  contains_spoilers      BOOLEAN NOT NULL DEFAULT false,
  rewatch                BOOLEAN NOT NULL DEFAULT false,

  -- Sync state
  status                 TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'syncing', 'synced', 'failed', 'auth_failed', 'skipped')),
  error                  TEXT,
  retry_count            INTEGER NOT NULL DEFAULT 0,
  letterboxd_viewing_id  BIGINT,           -- returned after successful save-diary-entry; used for edits

  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  synced_at              TIMESTAMPTZ,
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS letterboxd_queue_user_status_idx
  ON letterboxd_queue (user_id, status);
CREATE INDEX IF NOT EXISTS letterboxd_queue_pending_idx
  ON letterboxd_queue (created_at) WHERE status = 'pending';

DROP TRIGGER IF EXISTS letterboxd_queue_set_updated_at ON letterboxd_queue;
CREATE TRIGGER letterboxd_queue_set_updated_at
  BEFORE UPDATE ON letterboxd_queue
  FOR EACH ROW EXECUTE FUNCTION _iris_set_updated_at();

-- ============================================================
-- 4. serializd_queue — season-finale diary sync queue
-- ============================================================
CREATE TABLE IF NOT EXISTS serializd_queue (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,

  -- Source identification
  tmdb_show_id           INTEGER NOT NULL,
  show_slug              TEXT,             -- display/debug
  show_title             TEXT,
  season_number          INTEGER NOT NULL,
  serializd_season_id    INTEGER,          -- resolved at submit or at sync

  -- Rating + review payload
  rating_half_stars      SMALLINT CHECK (rating_half_stars IS NULL
                                         OR rating_half_stars BETWEEN 0 AND 10),
  liked                  BOOLEAN NOT NULL DEFAULT false,
  review_text            TEXT,             -- optional diary text
  tags                   JSONB NOT NULL DEFAULT '[]'::jsonb,
  contains_spoilers      BOOLEAN NOT NULL DEFAULT false,
  is_rewatch             BOOLEAN NOT NULL DEFAULT false,
  watched_at             TIMESTAMPTZ NOT NULL,   -- minute-precision (Serializd backdate)

  -- Sync state
  status                 TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'syncing', 'synced', 'failed', 'auth_failed', 'skipped')),
  error                  TEXT,
  retry_count            INTEGER NOT NULL DEFAULT 0,
  serializd_review_id    INTEGER,          -- returned after successful /show/reviews/add

  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  synced_at              TIMESTAMPTZ,
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS serializd_queue_user_status_idx
  ON serializd_queue (user_id, status);
CREATE INDEX IF NOT EXISTS serializd_queue_pending_idx
  ON serializd_queue (created_at) WHERE status = 'pending';

DROP TRIGGER IF EXISTS serializd_queue_set_updated_at ON serializd_queue;
CREATE TRIGGER serializd_queue_set_updated_at
  BEFORE UPDATE ON serializd_queue
  FOR EACH ROW EXECUTE FUNCTION _iris_set_updated_at();

-- ============================================================
-- 5. Row-level security — users see only their own rows
--    service_role bypasses RLS automatically (pipeline path).
-- ============================================================
ALTER TABLE letterboxd_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE serializd_queue  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS lb_queue_owner_select  ON letterboxd_queue;
DROP POLICY IF EXISTS lb_queue_owner_insert  ON letterboxd_queue;
DROP POLICY IF EXISTS lb_queue_owner_update  ON letterboxd_queue;
DROP POLICY IF EXISTS lb_queue_owner_delete  ON letterboxd_queue;

CREATE POLICY lb_queue_owner_select ON letterboxd_queue
  FOR SELECT USING (user_id = auth.uid());
CREATE POLICY lb_queue_owner_insert ON letterboxd_queue
  FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY lb_queue_owner_update ON letterboxd_queue
  FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY lb_queue_owner_delete ON letterboxd_queue
  FOR DELETE USING (user_id = auth.uid());

DROP POLICY IF EXISTS sz_queue_owner_select  ON serializd_queue;
DROP POLICY IF EXISTS sz_queue_owner_insert  ON serializd_queue;
DROP POLICY IF EXISTS sz_queue_owner_update  ON serializd_queue;
DROP POLICY IF EXISTS sz_queue_owner_delete  ON serializd_queue;

CREATE POLICY sz_queue_owner_select ON serializd_queue
  FOR SELECT USING (user_id = auth.uid());
CREATE POLICY sz_queue_owner_insert ON serializd_queue
  FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY sz_queue_owner_update ON serializd_queue
  FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY sz_queue_owner_delete ON serializd_queue
  FOR DELETE USING (user_id = auth.uid());

-- ============================================================
-- 6. Convenience RPCs used by pipeline (service-role only).
--    Sync scripts fetch pending rows WITH decrypted creds in a single call.
-- ============================================================

CREATE OR REPLACE FUNCTION get_pending_letterboxd_jobs(p_limit INT DEFAULT 100)
RETURNS TABLE (
  queue_id            UUID,
  user_id             UUID,
  lb_username         TEXT,
  lb_password         TEXT,
  tmdb_id             INTEGER,
  film_slug           TEXT,
  letterboxd_film_id  INTEGER,
  title               TEXT,
  year                INTEGER,
  rating_half_stars   SMALLINT,
  liked               BOOLEAN,
  watched_date        DATE,
  review_text         TEXT,
  tags                JSONB,
  contains_spoilers   BOOLEAN,
  rewatch             BOOLEAN,
  retry_count         INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY
    SELECT
      q.id,
      q.user_id,
      (_iris_decrypt_config('letterboxd', i.config))->>'username'  AS lb_username,
      (_iris_decrypt_config('letterboxd', i.config))->>'password'  AS lb_password,
      q.tmdb_id, q.film_slug, q.letterboxd_film_id,
      q.title, q.year,
      q.rating_half_stars, q.liked, q.watched_date, q.review_text, q.tags,
      q.contains_spoilers, q.rewatch, q.retry_count
    FROM letterboxd_queue q
    JOIN integrations i
      ON i.user_id = q.user_id
     AND i.service = 'letterboxd'
     AND i.is_enabled = true
    WHERE q.status = 'pending'
      AND (i.config->>'username') IS NOT NULL
      AND (i.config->>'password') IS NOT NULL
    ORDER BY q.created_at ASC
    LIMIT p_limit;
END;
$$;

REVOKE EXECUTE ON FUNCTION get_pending_letterboxd_jobs(INT) FROM public;
REVOKE EXECUTE ON FUNCTION get_pending_letterboxd_jobs(INT) FROM anon;
REVOKE EXECUTE ON FUNCTION get_pending_letterboxd_jobs(INT) FROM authenticated;
GRANT  EXECUTE ON FUNCTION get_pending_letterboxd_jobs(INT) TO service_role;

CREATE OR REPLACE FUNCTION get_pending_serializd_jobs(p_limit INT DEFAULT 100)
RETURNS TABLE (
  queue_id             UUID,
  user_id              UUID,
  sz_email             TEXT,
  sz_password          TEXT,
  tmdb_show_id         INTEGER,
  show_slug            TEXT,
  show_title           TEXT,
  season_number        INTEGER,
  serializd_season_id  INTEGER,
  rating_half_stars    SMALLINT,
  liked                BOOLEAN,
  review_text          TEXT,
  tags                 JSONB,
  contains_spoilers    BOOLEAN,
  is_rewatch           BOOLEAN,
  watched_at           TIMESTAMPTZ,
  retry_count          INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  RETURN QUERY
    SELECT
      q.id,
      q.user_id,
      (_iris_decrypt_config('serializd', i.config))->>'email'    AS sz_email,
      (_iris_decrypt_config('serializd', i.config))->>'password' AS sz_password,
      q.tmdb_show_id, q.show_slug, q.show_title,
      q.season_number, q.serializd_season_id,
      q.rating_half_stars, q.liked, q.review_text, q.tags,
      q.contains_spoilers, q.is_rewatch, q.watched_at, q.retry_count
    FROM serializd_queue q
    JOIN integrations i
      ON i.user_id = q.user_id
     AND i.service = 'serializd'
     AND i.is_enabled = true
    WHERE q.status = 'pending'
      AND (i.config->>'email') IS NOT NULL
      AND (i.config->>'password') IS NOT NULL
    ORDER BY q.created_at ASC
    LIMIT p_limit;
END;
$$;

REVOKE EXECUTE ON FUNCTION get_pending_serializd_jobs(INT) FROM public;
REVOKE EXECUTE ON FUNCTION get_pending_serializd_jobs(INT) FROM anon;
REVOKE EXECUTE ON FUNCTION get_pending_serializd_jobs(INT) FROM authenticated;
GRANT  EXECUTE ON FUNCTION get_pending_serializd_jobs(INT) TO service_role;

-- ============================================================
-- 7. Status-update RPC for sync scripts
--    Scripts call this to mark sync results without needing direct table write.
-- ============================================================
CREATE OR REPLACE FUNCTION update_letterboxd_sync_result(
  p_queue_id            UUID,
  p_status              TEXT,
  p_error               TEXT DEFAULT NULL,
  p_letterboxd_film_id  INTEGER DEFAULT NULL,
  p_film_slug           TEXT DEFAULT NULL,
  p_letterboxd_viewing_id BIGINT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  UPDATE letterboxd_queue
     SET status              = p_status,
         error               = p_error,
         retry_count         = CASE WHEN p_status IN ('failed', 'auth_failed')
                                    THEN retry_count + 1
                                    ELSE retry_count END,
         synced_at           = CASE WHEN p_status = 'synced' THEN now() ELSE synced_at END,
         letterboxd_film_id  = COALESCE(p_letterboxd_film_id, letterboxd_film_id),
         film_slug           = COALESCE(p_film_slug,          film_slug),
         letterboxd_viewing_id = COALESCE(p_letterboxd_viewing_id, letterboxd_viewing_id),
         updated_at          = now()
   WHERE id = p_queue_id;
END;
$$;

REVOKE EXECUTE ON FUNCTION update_letterboxd_sync_result(UUID, TEXT, TEXT, INTEGER, TEXT, BIGINT) FROM public;
REVOKE EXECUTE ON FUNCTION update_letterboxd_sync_result(UUID, TEXT, TEXT, INTEGER, TEXT, BIGINT) FROM anon;
REVOKE EXECUTE ON FUNCTION update_letterboxd_sync_result(UUID, TEXT, TEXT, INTEGER, TEXT, BIGINT) FROM authenticated;
GRANT  EXECUTE ON FUNCTION update_letterboxd_sync_result(UUID, TEXT, TEXT, INTEGER, TEXT, BIGINT) TO service_role;

CREATE OR REPLACE FUNCTION update_serializd_sync_result(
  p_queue_id             UUID,
  p_status               TEXT,
  p_error                TEXT DEFAULT NULL,
  p_serializd_season_id  INTEGER DEFAULT NULL,
  p_serializd_review_id  INTEGER DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  UPDATE serializd_queue
     SET status               = p_status,
         error                = p_error,
         retry_count          = CASE WHEN p_status IN ('failed', 'auth_failed')
                                     THEN retry_count + 1
                                     ELSE retry_count END,
         synced_at            = CASE WHEN p_status = 'synced' THEN now() ELSE synced_at END,
         serializd_season_id  = COALESCE(p_serializd_season_id, serializd_season_id),
         serializd_review_id  = COALESCE(p_serializd_review_id, serializd_review_id),
         updated_at           = now()
   WHERE id = p_queue_id;
END;
$$;

REVOKE EXECUTE ON FUNCTION update_serializd_sync_result(UUID, TEXT, TEXT, INTEGER, INTEGER) FROM public;
REVOKE EXECUTE ON FUNCTION update_serializd_sync_result(UUID, TEXT, TEXT, INTEGER, INTEGER) FROM anon;
REVOKE EXECUTE ON FUNCTION update_serializd_sync_result(UUID, TEXT, TEXT, INTEGER, INTEGER) FROM authenticated;
GRANT  EXECUTE ON FUNCTION update_serializd_sync_result(UUID, TEXT, TEXT, INTEGER, INTEGER) TO service_role;

-- ============================================================
-- 8. Queue summary RPC for UI (authenticated users — own counts only)
-- ============================================================
CREATE OR REPLACE FUNCTION get_my_sync_queue_summary()
RETURNS TABLE (
  service    TEXT,
  pending    INTEGER,
  failed     INTEGER,
  synced_24h INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  uid UUID := auth.uid();
BEGIN
  IF uid IS NULL THEN RETURN; END IF;

  RETURN QUERY
    SELECT 'letterboxd'::TEXT,
           COUNT(*) FILTER (WHERE status = 'pending')::INT,
           COUNT(*) FILTER (WHERE status IN ('failed','auth_failed'))::INT,
           COUNT(*) FILTER (WHERE status = 'synced' AND synced_at >= now() - INTERVAL '24 hours')::INT
      FROM letterboxd_queue WHERE user_id = uid
    UNION ALL
    SELECT 'serializd'::TEXT,
           COUNT(*) FILTER (WHERE status = 'pending')::INT,
           COUNT(*) FILTER (WHERE status IN ('failed','auth_failed'))::INT,
           COUNT(*) FILTER (WHERE status = 'synced' AND synced_at >= now() - INTERVAL '24 hours')::INT
      FROM serializd_queue WHERE user_id = uid;
END;
$$;

REVOKE EXECUTE ON FUNCTION get_my_sync_queue_summary() FROM public;
REVOKE EXECUTE ON FUNCTION get_my_sync_queue_summary() FROM anon;
GRANT  EXECUTE ON FUNCTION get_my_sync_queue_summary() TO authenticated;
GRANT  EXECUTE ON FUNCTION get_my_sync_queue_summary() TO service_role;
