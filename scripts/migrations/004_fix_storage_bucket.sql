-- Migration 004: Fix Supabase Storage bucket and RLS policies
--
-- Root cause: The user-data bucket exists but has no RLS policies allowing
-- authenticated users to INSERT/UPDATE objects. Client-side writes (sports,
-- CSV imports) fail with HTTP 400 ("new row violates row-level security policy").
--
-- Run this in the Supabase SQL Editor (https://supabase.com/dashboard → SQL Editor)
--
-- Safe to run multiple times (uses IF NOT EXISTS / OR REPLACE).

-- 1. Ensure the bucket exists
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('user-data', 'user-data', false, 52428800, NULL)
ON CONFLICT (id) DO NOTHING;

-- 2. Ensure RLS is enabled on storage.objects
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- 3. Drop any stale policies for this bucket (safe cleanup)
DROP POLICY IF EXISTS "Users can upload to own folder" ON storage.objects;
DROP POLICY IF EXISTS "Users can update own files" ON storage.objects;
DROP POLICY IF EXISTS "Users can read own files" ON storage.objects;
DROP POLICY IF EXISTS "Users can delete own files" ON storage.objects;
DROP POLICY IF EXISTS "Service role full access" ON storage.objects;

-- 4. Allow authenticated users to INSERT objects in their own {user_id}/ folder
CREATE POLICY "Users can upload to own folder" ON storage.objects
FOR INSERT TO authenticated
WITH CHECK (
  bucket_id = 'user-data'
  AND (storage.foldername(name))[1] = auth.uid()::text
);

-- 5. Allow authenticated users to UPDATE their own objects
CREATE POLICY "Users can update own files" ON storage.objects
FOR UPDATE TO authenticated
USING (
  bucket_id = 'user-data'
  AND (storage.foldername(name))[1] = auth.uid()::text
)
WITH CHECK (
  bucket_id = 'user-data'
  AND (storage.foldername(name))[1] = auth.uid()::text
);

-- 6. Allow authenticated users to SELECT (read) their own objects
CREATE POLICY "Users can read own files" ON storage.objects
FOR SELECT TO authenticated
USING (
  bucket_id = 'user-data'
  AND (storage.foldername(name))[1] = auth.uid()::text
);

-- 7. Allow authenticated users to DELETE their own objects
CREATE POLICY "Users can delete own files" ON storage.objects
FOR DELETE TO authenticated
USING (
  bucket_id = 'user-data'
  AND (storage.foldername(name))[1] = auth.uid()::text
);

-- 8. Allow service_role full access (for pipeline scripts)
CREATE POLICY "Service role full access" ON storage.objects
FOR ALL TO service_role
USING (bucket_id = 'user-data')
WITH CHECK (bucket_id = 'user-data');
