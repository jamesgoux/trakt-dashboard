# Iris — Multi-User Architecture Plan

**Status:** Approved — Supabase (free tier) + GitHub Pages + GitHub Actions
**Decision date:** 2026-03-23
**Supersedes:** ITERATION_PLAN.md Priority 4

---

## Design Principles

1. **Zero data loss** — jamesgoux's data survives intact at every step
2. **No downtime** — live dashboard stays functional throughout migration
3. **Phased delivery** — each phase is independently shippable
4. **Graceful fallback** — if Supabase is down, embedded data blob still works

## Technology Stack

- **Auth + DB + Storage:** Supabase (free tier: 500MB DB, 1GB storage, 50K MAU)
- **Frontend hosting:** GitHub Pages (production), Vercel (staging previews)
- **Pipeline (jamesgoux):** GitHub Actions (unchanged during migration)
- **Pipeline (other users):** Supabase Edge Functions + manual trigger (Phase 5)

---

## Staging & Testing Strategy

Three layers, each with its own staging approach:

| Layer | Staging | Production | Switch |
|-------|---------|------------|--------|
| **Supabase** | `iris-staging` project (free tier allows 2) | `iris-production` project (created at go-live) | Change SUPABASE_URL env var |
| **Dashboard** | Vercel preview deployments (auto per branch) | GitHub Pages (unchanged, serves `main`) | Merge branch to `main` |
| **Pipeline** | `--dry-run` / `--target=staging` flags | GitHub Actions on `main` (unchanged) | Remove flags |

### Vercel Preview Deployments (free)
- Connect `jamesgoux/iris-stats` repo to Vercel (one-time, ~2 min)
- Every push to `feature/multi-user` branch auto-deploys to a preview URL
- URL format: `iris-stats-git-feature-multi-user-jamesgoux.vercel.app`
- Shareable — can test on mobile, show to others for feedback
- Does NOT touch GitHub Pages — production site stays on `main` branch

### Two Supabase Projects (both free)
- `iris-staging`: used during all development (Phases 0-5). Safe to wipe, rebuild, experiment.
- `iris-production`: created only at go-live. jamesgoux config migrated from staging.
- Dashboard template uses `IRIS_SUPABASE_URL` variable — switch between envs by changing one value

### Pipeline Dry-Run Mode
- All refactored scripts accept `--dry-run` (Phase 5)
- Reads data but writes to staging Supabase only
- `run_user_pipeline.py --user=testuser --target=staging`

### Testing at Each Phase

| Phase | How to Test |
|-------|-------------|
| 0 | Verify rebuild locally in sandbox |
| 1 | Query staging Supabase directly (SQL editor, API) |
| 2 | Vercel preview URL — test login/register/gate, verify public view |
| 3 | Vercel preview URL — test `?user=jamesgoux` (embedded) vs `?user=testuser` (API fetch) |
| 4 | Vercel preview URL — full settings flow with staging Supabase |
| 5 | Pipeline dry-run against staging, verify data in staging Storage |
| 6 | Vercel preview URL — sports/CSV writes hit staging, not GitHub |
| Go-live | Create production Supabase, migrate configs, merge to main, update GH Secrets |

---

## Integration Inventory

### User-Specific (13 integrations — each user needs their own)

| # | Service | Auth Type | Credentials | Scripts |
|---|---------|-----------|-------------|---------|
| 1 | **Trakt.tv** | OAuth2 (device code) | client_id, client_secret, access_token, refresh_token, username | refresh_data, refresh_trakt_token, refresh_upnext, refresh_upcoming, refresh_watchlist, client-side D._tc/D._tt |
| 2 | **Letterboxd** | Username (RSS) + scraping | username, CSV uploads | refresh_letterboxd, refresh_watchlist |
| 3 | **Last.fm** | API key + username | api_key, username | refresh_lastfm, backfill_lastfm_daily, refresh_data |
| 4 | **Goodreads** | User ID (RSS) | user_id | refresh_goodreads |
| 5 | **Pocket Casts** | Email + password | email, password | refresh_pocketcasts |
| 6 | **Serializd** | Email + password | email, password | refresh_serializd |
| 7 | **BoardGameGeek** | Username + password | username, password | refresh_boardgames |
| 8 | **Apple Health (Hadge)** | GitHub PAT (private repo) | gh_token, repo_path | refresh_health |
| 9 | **setlist.fm** | API key + curated data | api_key, CSV archives | refresh_setlist, backfill_setlist_songs |
| 10 | **GameTrack** | CSV import | file upload | import_gametrack, client-side CSV drop |
| 11 | **Mezzanine Theater** | CSV import | file upload | client-side CSV drop |
| 12 | **BG Stats** | JSON import | file upload | client-side CSV drop |
| 13 | **Sports Events** | Manual entry | teams tracked (user pref) | client-side + GitHub API |

### Shared/Global (5 integrations — one set for all users)

| # | Service | Auth | Purpose |
|---|---------|------|---------|
| 14 | **TMDB** | API key (app-level) | Posters, headshots, cast/crew, episode data |
| 15 | **MusicBrainz** | None (rate-limited) | Artist genre metadata |
| 16 | **TheSportsDB** | Public key (3) | Sports schedules |
| 17 | **JustWatch** | None (GraphQL, CORS-blocked) | Streaming availability, prices |
| 18 | **Goodreads scraping** | None | Book genre metadata |

---

## Hardcoded Values to Remove

| File | Value | Fix |
|------|-------|-----|
| `refresh_letterboxd.py:14` | `"jamesgoux"` fallback | User config |
| `refresh_setlist.py:10` | `"jamesgoux"` fallback | User config |
| `refresh_watchlist.py:15` | `"jamesgoux"` fallback | User config |
| `refresh_boardgames.py:13` | `"jamesgoux"` fallback | User config |
| `refresh_health.py:15` | `'jamesgoux/health'` repo | User config |
| `refresh_data.py` | `America/Los_Angeles` timezone | User config |
| `refresh_data.py` | June 2016 bulk import exclusions | Per-user or remove |
| `refresh_artist_genres.py:34` | `"jamesgoux@github"` User-Agent | Generic |
| `backfill_posters.py:7` | Trakt client ID literal | Env var |
| `templates/dashboard.html` (5+ places) | `jamesgoux/iris-stats` GitHub API writes | Backend API |

## Client-Side State (localStorage)

| Key | Purpose | Multi-User Fix |
|-----|---------|---------------|
| `iris_gh_pat` | GitHub PAT for direct writes | Replace with backend API |
| `iris_sports_pending` | Pending sports events | Move to backend per-user |
| `iris_un_watched` | Mark-as-watched cache | Namespace `iris_{uid}_un_watched` |
| `iris_un_removed` | Removed from Up Next | Namespace `iris_{uid}_un_removed` |
| `iris_un_build` | Last build timestamp | Namespace `iris_{uid}_un_build` |
| `iris-wl-order` | Watchlist order (cached) | Namespace `iris_{uid}_wl_order` |

---

## Database Schema

```sql
-- profiles: extends Supabase auth.users
CREATE TABLE profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT,
  timezone TEXT DEFAULT 'America/Los_Angeles',
  is_public BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- integrations: per-user service connections
CREATE TABLE integrations (
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

-- user_preferences: per-user settings
CREATE TABLE user_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value JSONB NOT NULL DEFAULT '{}',
  UNIQUE(user_id, key)
);
```

### Integration Config JSONB Shapes

```
trakt:       { client_id, client_secret, access_token, refresh_token, username, token_expires_at }
letterboxd:  { username }
lastfm:      { api_key, username }
goodreads:   { user_id }
pocketcasts: { email, password }
serializd:   { email, password }
bgg:         { username, password }
health:      { github_token, repo_path }
setlistfm:   { api_key }
sports:      { tracked_teams: [{id, name, league}] }
```

### Supabase Storage

```
user-data/{user_id}/dashboard.json   ← Full data blob (~10MB)
user-data/{user_id}/trakt.json       ← Raw data (incremental updates)
user-data/{user_id}/letterboxd.json
user-data/{user_id}/...              ← Mirrors current data/*.json
```

---

## Execution Plan — Detailed Tasks with Dependencies

**Notation:** `‖` = concurrent, `→` = sequential dependency

---

### Phase 0 — Safety Net + Staging Setup

**Goal:** Protect existing data, set up development infrastructure.
**Estimate:** 20 min (part of Phase 1 session)

**Flow:** `[0.1] ‖ [0.2] ‖ [0.3] ‖ [0.5] → [0.4] → [0.6]`

| Task | Description | Depends On | Concurrent With |
|------|-------------|------------|-----------------|
| 0.1 | Backup all `data/*.json` (46 files, 37MB) — local snapshot + git tag | — | 0.2, 0.3, 0.5 |
| 0.2 | Create `feature/multi-user` branch from main | — | 0.1, 0.3, 0.5 |
| 0.3 | Document all keys in `var D` blob (types, sizes) | — | 0.1, 0.2, 0.5 |
| 0.4 | Verify local rebuild: template + data → index.html | 0.2 | — |
| 0.5 | Connect repo to Vercel (free tier): import jamesgoux/iris-stats, configure preview deployments | — | 0.1, 0.2, 0.3 |
| 0.6 | Push to `feature/multi-user` → verify Vercel preview URL works with current dashboard | 0.2, 0.4, 0.5 | — |

---

### Phase 1 — Supabase Staging Foundation

**Goal:** Auth system + DB + storage exist, pre-loaded with jamesgoux config.
**Estimate:** 1 session

**Flow:** `[1.1] → [1.2] ‖ [1.3] ‖ [1.6] ‖ [1.8] → [1.4] → [1.5] ‖ [1.7] → [1.9] → [1.10]`

| Task | Description | Depends On | Concurrent With |
|------|-------------|------------|-----------------|
| 1.1 | Create `iris-staging` Supabase project (free tier), note URL + anon key + service key | Phase 0 | — |
| 1.2 | Create profiles, integrations, user_preferences tables via SQL editor | 1.1 | 1.3, 1.6, 1.8 |
| 1.3 | Enable email/password auth provider in Supabase dashboard | 1.1 | 1.2, 1.6, 1.8 |
| 1.4 | Apply Row-Level Security policies | 1.2 | — |
| 1.5 | Create jamesgoux user → insert profile → insert all 13 integration configs | 1.2, 1.3, 1.4 | 1.7 |
| 1.6 | Create `user-data` Storage bucket with per-user folder policy | 1.1 | 1.2, 1.3, 1.8 |
| 1.7 | Create `scripts/supabase_config.py` (Python helper for pipeline) | 1.1 | 1.5 |
| 1.8 | Add SUPABASE_URL (staging), SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY to GitHub Secrets | 1.1 | 1.2, 1.3, 1.6 |
| 1.9 | Upload jamesgoux's complete data blob to staging Storage | 1.5, 1.6 | — |
| 1.10 | Smoke test: query profiles, integrations, download blob via staging API | 1.9 | — |

---

### Phase 2 — Auth Layer on Dashboard

**Goal:** Login/logout works. Write operations gated. Public view unchanged.
**Estimate:** 1-2 sessions

**Flow:** `[2.1] → [2.2] ‖ [2.3] → [2.4] ‖ [2.5] ‖ [2.7] → [2.6] → [2.8]`

| Task | Description | Depends On | Concurrent With |
|------|-------------|------------|-----------------|
| 2.1 | Add Supabase JS client to dashboard template (CDN script tag + init with staging URL) | 1.1 | — |
| 2.2 | Build login/register modal: email + password, error handling, toggle | 2.1 | 2.3 |
| 2.3 | Session persistence: `onAuthStateChange()`, store session, auto-refresh | 2.1 | 2.2 |
| 2.4 | User menu when logged in: username, Settings, Refresh, Logout | 2.2, 2.3 | 2.5, 2.7 |
| 2.5 | Gate write ops behind `_irisUser` check: mark-watched, watchlist, sports, CSV | 2.3 | 2.4, 2.7 |
| 2.6 | Verify on Vercel preview: unauthenticated visitor sees full read-only dashboard unchanged | 2.1-2.5 | — |
| 2.7 | Logged-in user: fetch Trakt token from Supabase integrations, use instead of `D._tt` | 2.3, 1.5 | 2.4, 2.5 |
| 2.8 | E2E on Vercel preview: register → login → write → verify gate → logout → verify public | 2.1-2.7 | — |

---

### Phase 3 — Dynamic Data Loading

**Goal:** Dashboard loads any user's data from Supabase. jamesgoux embedded blob = fast fallback.
**Estimate:** 1-2 sessions

**Flow:** `[3.1] ‖ [3.2] → [3.3] → [3.4] ‖ [3.5] ‖ [3.6] → [3.7]`

| Task | Description | Depends On | Concurrent With |
|------|-------------|------------|-----------------|
| 3.1 | Supabase Edge Function: `GET /user-data/{username}` → Storage → return blob | 1.6, 1.9 | 3.2 |
| 3.2 | Verify jamesgoux data in staging Storage, accessible via Edge Function | 1.9 | 3.1 |
| 3.3 | Dashboard bootstrap: parse `?user=X` → embedded match? use it : fetch from API → `D = response` → `render()`. Loading spinner. | 3.1, 3.2 | — |
| 3.4 | URL routing: `?user={username}` shows that user. Default = jamesgoux | 3.3 | 3.5, 3.6 |
| 3.5 | Keep embedded `var D` for jamesgoux (zero-latency fallback) | 3.3 | 3.4, 3.6 |
| 3.6 | Pipeline update: `refresh_data.py` also uploads blob to Supabase after build | 1.7, 3.1 | 3.4, 3.5 |
| 3.7 | Test on Vercel preview: jamesgoux = instant (embedded), testuser = API load (~1-2s), Supabase down = still works | 3.3-3.6 | — |

---

### Phase 4 — Integration Settings UI

**Goal:** Users configure their own service connections.
**Estimate:** 2 sessions

**Flow:** `[4.1] → [4.2a] ‖ [4.2b] ‖ [4.2c] ‖ [4.2d] ‖ [4.2e] → [4.3] → [4.4] → [4.5]`

| Task | Description | Depends On | Concurrent With |
|------|-------------|------------|-----------------|
| 4.1 | Settings overlay shell: service card grid, opens from user menu | 2.4 | — |
| 4.2a | Trakt config: device code flow in-dashboard → store tokens in staging Supabase | 4.1 | 4.2b-e |
| 4.2b | Username services: Letterboxd, Goodreads, Last.fm input forms | 4.1 | 4.2a,c,d,e |
| 4.2c | Password services: Pocket Casts, Serializd, BGG forms | 4.1 | 4.2a,b,d,e |
| 4.2d | CSV imports: GameTrack, Theater, BG Stats file upload | 4.1 | 4.2a,b,c,e |
| 4.2e | Sports team picker (reuse TheSportsDB search) | 4.1 | 4.2a-d |
| 4.3 | Validation: test credentials on save, show success/failure | 4.2a-e | — |
| 4.4 | Status indicators: green=connected, red=error, gray=not configured | 4.3 | — |
| 4.5 | E2E on Vercel preview: new user → Settings → connect Trakt → green status → disconnect → gray | 4.4 | — |

---

### Phase 5 — Per-User Pipeline

**Goal:** Any user's data can be refreshed, not just jamesgoux.
**Estimate:** 2-3 sessions

**Flow:** `[5.1a-l all parallel] → [5.2] → [5.3] ‖ [5.4] ‖ [5.5] ‖ [5.6] → [5.7] → [5.8]`

| Task | Description | Depends On | Concurrent With |
|------|-------------|------------|-----------------|
| 5.1a | Refactor `refresh_data.py`: user_config dict, Supabase creds, no hardcoded values, `--dry-run` | 1.7 | 5.1b-l |
| 5.1b | Refactor `refresh_letterboxd.py` (+ `--dry-run`) | 1.7 | 5.1a,c-l |
| 5.1c | Refactor `refresh_lastfm.py` (+ `--dry-run`) | 1.7 | 5.1a-b,d-l |
| 5.1d | Refactor `refresh_goodreads.py` (+ `--dry-run`) | 1.7 | 5.1a-c,e-l |
| 5.1e | Refactor `refresh_pocketcasts.py` (+ `--dry-run`) | 1.7 | 5.1a-d,f-l |
| 5.1f | Refactor `refresh_serializd.py` (+ `--dry-run`) | 1.7 | 5.1a-e,g-l |
| 5.1g | Refactor `refresh_setlist.py` (+ `--dry-run`) | 1.7 | 5.1a-f,h-l |
| 5.1h | Refactor `refresh_boardgames.py` (+ `--dry-run`) | 1.7 | 5.1a-g,i-l |
| 5.1i | Refactor `refresh_health.py` (+ `--dry-run`) | 1.7 | 5.1a-h,j-l |
| 5.1j | Refactor `refresh_upnext.py` (+ `--dry-run`) | 1.7 | 5.1a-i,k-l |
| 5.1k | Refactor `refresh_upcoming.py` (+ `--dry-run`) | 1.7 | 5.1a-j,l |
| 5.1l | Refactor `refresh_watchlist.py` (+ `--dry-run`) | 1.7 | 5.1a-k |
| 5.2 | Create `run_user_pipeline.py` orchestrator: `--target=staging/production` flag | 5.1a-l | — |
| 5.3 | "Refresh Now" button in user menu → calls Edge Function | 5.2, 2.4 | 5.4, 5.5, 5.6 |
| 5.4 | Edge Function: `POST /refresh/{user_id}` → triggers pipeline | 5.2 | 5.3, 5.5, 5.6 |
| 5.5 | Rate limiting: max 1 refresh per user per 10 min | 5.4 | 5.3, 5.6 |
| 5.6 | Shared enrichment: TMDB/MusicBrainz/TheSportsDB in global cache bucket | 5.2 | 5.3, 5.4, 5.5 |
| 5.7 | jamesgoux dual-mode: GH Actions continues + uploads to Supabase | 5.2, 3.6 | — |
| 5.8 | E2E with staging: test user → connect Trakt → Refresh → dashboard loads their data | 5.3 | — |

---

### Phase 6 — Replace Client-Side Direct Writes

**Goal:** All writes go through backend. No more client → GitHub API.
**Estimate:** 1 session

**Flow:** `[6.1a] ‖ [6.1b] ‖ [6.1c] → [6.2] ‖ [6.3] → [6.4] → [6.5]`

| Task | Description | Depends On | Concurrent With |
|------|-------------|------------|-----------------|
| 6.1a | Edge Function: `POST/DELETE /sports/events` (per-user) | 1.2 | 6.1b, 6.1c |
| 6.1b | Edge Function: `PUT /sports/teams` (per-user) | 1.2 | 6.1a, 6.1c |
| 6.1c | Edge Function: `POST /import/csv` (per-user Storage) | 1.2, 1.6 | 6.1a, 6.1b |
| 6.2 | Dashboard: replace all GitHub API write calls with Supabase Edge Function calls | 6.1a-c, 2.3 | 6.3 |
| 6.3 | Namespace localStorage keys: `iris_{user_id}_*` | 2.3 | 6.2 |
| 6.4 | Remove `iris_gh_pat` pattern + GitHub write code from template | 6.2 | — |
| 6.5 | Test on Vercel preview: sports add, CSV import — verify in staging Supabase, not GitHub | 6.4 | — |

---

### Go-Live — Staging → Production Cutover

**Flow:** `[GL.1] → [GL.2] ‖ [GL.3] → [GL.4] ‖ [GL.5] → [GL.6]`

| Task | Description | Depends On | Concurrent With |
|------|-------------|------------|-----------------|
| GL.1 | Create `iris-production` Supabase project (uses 2nd free project slot) | Phases 2-6 tested on staging | — |
| GL.2 | Replicate schema from staging to production (tables, RLS, Storage buckets) | GL.1 | GL.3 |
| GL.3 | Migrate jamesgoux config from staging to production (profile + integrations) | GL.1 | GL.2 |
| GL.4 | Update dashboard template: `IRIS_SUPABASE_URL` → production URL | GL.2, GL.3 | GL.5 |
| GL.5 | Update GitHub Secrets: `SUPABASE_URL` → production URL | GL.2, GL.3 | GL.4 |
| GL.6 | Merge `feature/multi-user` → `main` (deploys to GitHub Pages) + final verification | GL.4, GL.5 | — |

---

### Phase 7 — Polish & Harden

**Goal:** Production-ready multi-user experience.
**Estimate:** Ongoing, 1-2 sessions

All tasks parallelizable:

| Task | Description | Depends On |
|------|-------------|------------|
| 7.1 | User profile page: display name, timezone, public/private toggle | 2.4, 1.2 |
| 7.2 | Auto-refresh scheduling for non-jamesgoux users | 5.4 |
| 7.3 | Password reset flow (Supabase Auth built-in, need UI) | 2.2 |
| 7.4 | Structured logging in pipeline (per-user context) | 5.2 |
| 7.5 | Rate limiting + abuse prevention | 5.4, 6.1 |
| 7.6 | Global enrichment caches in Supabase | 5.6 |

---

## Phase Safety Matrix

| Phase | jamesgoux Dashboard | GitHub Actions | Public View | Rollback |
|-------|-------------------|---------------|-------------|----------|
| 0 | Untouched | Running | Public | N/A |
| 1 | Untouched | Running | Public | Delete staging Supabase |
| 2 | Untouched (Vercel preview only) | Running | Public | Revert branch |
| 3 | Untouched (Vercel preview only) | Running | Public | Revert branch |
| 4 | Untouched (Vercel preview only) | Running | Public | Revert branch |
| 5 | Untouched (--dry-run) | Running | Public | Revert branch |
| 6 | Untouched (Vercel preview only) | Running | Public | Revert branch |
| Go-live | Merge → new features live | Running + Supabase | Multi-user | Revert merge |
| 7 | Polish | Optional | Multi-user | Per-feature revert |

## Milestones

- **Milestone 1 (Phases 0-2):** Auth works on preview, writes protected → Demo on Vercel
- **Milestone 2 (Phase 3):** Other users can view dashboards on preview → Shareable preview
- **Milestone 3 (Phase 4):** Self-service config on preview → Beta testing on Vercel
- **Milestone 4 (Phases 5-6):** Per-user pipelines + backend writes → Ready for go-live
- **Milestone 5 (Go-live):** Merge to main, cut to production Supabase → Live multi-user
- **Milestone 6 (Phase 7):** Polish → Public launch
