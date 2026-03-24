-- ============================================
-- Iris Storage Bucket + Policies — Phase 1
-- ============================================

-- Create the user-data bucket (public read for public profiles)
INSERT INTO storage.buckets (id, name, public)
VALUES ('user-data', 'user-data', true)
ON CONFLICT (id) DO NOTHING;

-- Anyone can read files in user-data (public dashboards)
CREATE POLICY "Public read access to user data"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'user-data');

-- Users can upload to their own folder: user-data/{user_id}/*
CREATE POLICY "Users can upload to own folder"
  ON storage.objects FOR INSERT
  WITH CHECK (
    bucket_id = 'user-data' AND
    (storage.foldername(name))[1] = auth.uid()::text
  );

-- Users can update files in their own folder
CREATE POLICY "Users can update own files"
  ON storage.objects FOR UPDATE
  USING (
    bucket_id = 'user-data' AND
    (storage.foldername(name))[1] = auth.uid()::text
  );

-- Users can delete files in their own folder
CREATE POLICY "Users can delete own files"
  ON storage.objects FOR DELETE
  USING (
    bucket_id = 'user-data' AND
    (storage.foldername(name))[1] = auth.uid()::text
  );
