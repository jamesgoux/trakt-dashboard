# Iris — Iteration Plan

---

## Priority 1: Active Bugs & Feature Requests

1. ~~**"Watches" and "Days Watched" not filtering by year**~~ ✅ DONE
   Stats bar totals for watches and days watched now recalculate based on the selected year. Added per-month runtime tracking to Python pipeline and computed filtered totals in JS.

2. ~~**Show posters not obeying the 50% image fallback rule**~~ ✅ DONE
   Top Shows now falls back to side-by-side bar charts (By Duration + By Episodes) when fewer than 50% of shows have poster images.

3. ~~**Better image backfill catch-up strategy**~~ ✅ DONE
   Smarter backfill approach implemented — gaps get filled faster.

4. ~~**Prioritize visible empty posters on "All Time" for image backfill**~~ ✅ DONE
   Headshot/poster backfill now prioritizes people and shows visible on the "all time / all types" dashboard page before falling back to most-recent-first. Directors and writers also get a larger budget share.

---

## Priority 2: Quick Wins

5. ~~**Add `requirements.txt` with pinned versions**~~ ✅ DONE
   Added `requirements.txt` with `requests>=2.31,<3`. Both workflows now use `pip install -r requirements.txt`.

6. ~~**Replace bare `except:` clauses with specific exceptions**~~ ✅ DONE
   Replaced 23 bare `except:` with `except Exception:` across all scripts.

7. ~~**Add data validation before type conversions**~~ ✅ DONE
   Added `safe_int()` and `safe_float()` helpers to `refresh_data.py` and `refresh_lastfm.py`. All unguarded `int()`/`float()` conversions now use safe wrappers.

---

## Priority 3: Medium Effort / High Impact

8. ~~**Add retry logic with exponential backoff for API calls**~~ ✅ DONE
   Added shared `scripts/utils.py` with `retry_request()` (exponential backoff, rate limit handling). Integrated into `refresh_data.py` and `refresh_pocketcasts.py`. Fixed workflow concurrency to not cancel in-progress runs.

9. ~~**Refactor `refresh_data.py` into smaller functions**~~ ✅ DONE
   Extracted shared `scripts/utils.py` with retry logic. Fixed `sys.path` for imports. Reordered workflow: fast sources (Letterboxd, Goodreads, Concerts, Podcasts) run first, slow sources (Last.fm) last. Added `continue-on-error` so one failing source doesn't block the rest.

---

## Priority 4: Genericize Project (Multi-User)

> **This section has been superseded by [`MULTI_USER_PLAN.md`](MULTI_USER_PLAN.md)** — a comprehensive plan covering all 18 integrations, Supabase architecture, staging strategy, database schema, and 54 granular tasks across 7 phases with dependency/concurrency mapping.

The original requirements below are preserved for reference, but the implementation plan in `MULTI_USER_PLAN.md` is the source of truth.

Turn Iris from a single-user GitHub Pages site into a multi-user web application where anyone can sign up, connect their own media services, and get their own dashboard.

### Requirements

**R1. User Authentication & Accounts**
- Users can create an account (email + password or OAuth)
- Users can log in / log out
- Each user has their own isolated data store
- Session management with secure tokens
- Password reset flow

**R2. Service Connection UI**
- After login, users see a "Connect Services" settings page
- Each service (Trakt, Letterboxd, Last.fm, setlist.fm, Goodreads, Pocket Casts, TMDB) has a connect/disconnect toggle
- For API-key services (Trakt, Last.fm, setlist.fm, TMDB): user enters their own API key
- For username-based services (Letterboxd, Goodreads, setlist.fm): user enters their username
- For login-based services (Pocket Casts): user enters email + password (stored encrypted)
- Connection status shown per service (connected / disconnected / error)
- Validation: test the credentials on save and show success/failure

**R3. Per-User Data Pipeline**
- Each user's data is fetched and stored independently
- Data refresh runs per-user on a schedule (not a single global cron)
- Options: server-side scheduler, or user-triggered refresh button
- Data stored per-user (e.g., `data/{user_id}/` or database)
- Existing GitHub Actions pipeline needs to be replaced with a server-side process or cloud function

**R4. Remove Hardcoded User-Specific Values**
- Remove hardcoded `"jamesgoux"` fallback username from `refresh_letterboxd.py` and `refresh_setlist.py`
- Make timezone configurable per user (currently hardcoded `America/Los_Angeles`)
- Make the 2016 data exclusion configurable per user (or remove it — it's specific to one user's bulk import)
- All service credentials come from user config, not environment variables

**R5. Backend Infrastructure**
- Need a backend server (Python/Flask, Node, etc.) or serverless functions
- Database for user accounts and credentials (PostgreSQL, SQLite, or managed service)
- Encrypted storage for API keys and passwords
- API endpoints for: auth, service config, data refresh, dashboard data
- Rate limiting per user to prevent abuse

**R6. Dashboard Serving**
- Currently: single static HTML with all data embedded as JSON
- Multi-user: dashboard loads data dynamically via API (fetch user's data on page load)
- Or: generate per-user static HTML files (simpler but more storage)
- URL structure: `iris.app/{username}` or `iris.app/dashboard` (authenticated)

**R7. Migration Path**
- Existing single-user data should be importable as the first user
- GitHub Actions workflows become optional (for self-hosted single-user mode)
- Support both modes: self-hosted (current GitHub Pages approach) and hosted multi-user

**R8. Testing**
- Add a test suite covering data parsing, normalization, and API integration
- Unit tests for each refresh script's core logic
- Integration tests for the data pipeline
- Auth flow tests

**R9. Structured Logging**
- Replace print statements with proper logging (levels, timestamps, context)
- Per-user log context for debugging
- Error tracking for failed service connections

**R10. Frontend Modularity**
- Break `templates/dashboard.html` (1800+ lines) into manageable components
- Separate chart rendering, data loading, and UI logic
- Support dynamic data loading (fetch from API instead of embedded JSON)

### Implementation Phases (suggested order)

1. **Phase 1 — Clean up hardcoded values** (R4): Remove jamesgoux defaults, make timezone/exclusions configurable via env vars. This is prerequisite for everything else.

2. **Phase 2 — Add testing** (R8): Cover core data parsing with pytest before refactoring. Safety net for the bigger changes.

3. **Phase 3 — Backend + Auth** (R1, R5): Stand up a minimal backend with user accounts and credential storage. This is the biggest architectural change.

4. **Phase 4 — Service connection UI** (R2): Build the settings page where users connect their services.

5. **Phase 5 — Per-user pipeline** (R3): Migrate from GitHub Actions to server-side data refresh per user.

6. **Phase 6 — Dynamic dashboard** (R6, R10): Switch from embedded JSON to API-loaded data. Break up the monolithic template.

7. **Phase 7 — Logging + polish** (R9): Add structured logging, error tracking, monitoring.

---

## Priority 5: Maintenance

14. **Add cache invalidation for TMDB images**
    Images are cached forever — if a URL goes stale, the broken image persists.

---

## Completed

| # | Item | Status |
|---|------|--------|
| 1 | Watches/Days year filtering | ✅ |
| 2 | Show poster 50% fallback | ✅ |
| 4 | Visible priority for image backfill | ✅ |
| 5 | requirements.txt | ✅ |
| 6 | Replace bare except clauses | ✅ |
| 7 | Data validation helpers | ✅ |
| 8 | Retry logic with backoff | ✅ |
| 9 | Refactor workflow ordering | ✅ |
| 17 | CSV import validation | ✅ |
| 18 | Workflow concurrency guards | ✅ |
