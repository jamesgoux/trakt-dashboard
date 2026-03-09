# Iris — Iteration Plan

---

## Priority 1: Active Bugs & Feature Requests

1. **"Watches" and "Days Watched" not filtering by year**
   Stats bar totals for watches and days watched are not respecting the year filter selection. They should recalculate based on the selected year.

2. **Show posters not obeying the 50% image fallback rule**
   The Top Shows section should fall back to bar graphs when fewer than 50% of shows have poster images. Currently it renders the poster grid regardless of coverage.

3. **Better image backfill catch-up strategy**
   Need a smarter approach to backfilling missing images so gaps get filled faster.

4. **Prioritize visible empty posters on "All Time" for image backfill**
   Change the headshot/poster backfill priority so that shows appearing in the "All Time" view with missing images are fetched first, rather than the current most-recent-first approach.

---

## Priority 2: Quick Wins

5. **Add `requirements.txt` with pinned versions**
   Only dependency is `requests`, but it should be pinned to avoid surprise breakage.

6. **Replace bare `except:` clauses with specific exceptions**
   7+ instances across scripts silently swallow errors. Catch specific exceptions and log them.

7. **Add data validation before type conversions**
   Guard against crashes on malformed API responses (e.g., `int(num_pages)` in goodreads without a check).

---

## Priority 3: Medium Effort / High Impact

8. **Add retry logic with exponential backoff for API calls**
   Transient failures currently skip data silently. Add retries so temporary outages don't leave gaps.

9. **Refactor `refresh_data.py` into smaller functions**
   Currently 1,417 lines. Break into testable, maintainable modules.

10. **Make timezone configurable**
    Hardcoded `America/Los_Angeles` — should be an env var or auto-detected.

11. **Make the 2016 data exclusion configurable**
    Currently hardcoded skip of year 2016 (bulk-import outlier). Should be a config option.

12. **Remove hardcoded `"jamesgoux"` fallback username**
    `refresh_letterboxd.py` and `refresh_setlist.py` default to `"jamesgoux"` — require explicit config instead.

---

## Priority 4: Bigger Lifts

13. **Add a test suite**
    At minimum, cover data parsing and normalization functions with pytest.

14. **Add structured logging**
    Replace print statements with proper logging (levels, timestamps, context).

15. **Break `templates/dashboard.html` into manageable pieces**
    The monolithic template is hard to maintain and debug.

16. **Add cache invalidation for TMDB images**
    Images are cached forever — if a URL goes stale, the broken image persists.

---

## Priority 5: Security & Reliability

17. **Validate CSV imports before processing**
    Drag-drop CSV import doesn't check file format or sanitize input.

18. **Prevent workflow overlap conflicts**
    The 20-min refresh and daily headshot workflow could collide. Add concurrency guards or file locking.
