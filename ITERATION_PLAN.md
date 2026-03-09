# Iris — Iteration Plan

---

## Priority 1: Active Bugs & Feature Requests

1. ~~**"Watches" and "Days Watched" not filtering by year**~~ ✅ DONE
   Stats bar totals for watches and days watched now recalculate based on the selected year. Added per-month runtime tracking to Python pipeline and computed filtered totals in JS.

2. ~~**Show posters not obeying the 50% image fallback rule**~~ ✅ DONE
   Top Shows now falls back to side-by-side bar charts (By Duration + By Episodes) when fewer than 50% of shows have poster images.

3. **Better image backfill catch-up strategy**
   Need a smarter approach to backfilling missing images so gaps get filled faster.

4. ~~**Prioritize visible empty posters on "All Time" for image backfill**~~ ✅ DONE
   Headshot/poster backfill now prioritizes people and shows visible on the "all time / all types" dashboard page before falling back to most-recent-first. Directors and writers also get a larger budget share.

---

## Priority 2: Quick Wins

5. ~~**Add `requirements.txt` with pinned versions**~~ ✅ DONE
   Added `requirements.txt` with `requests>=2.31,<3`. Both workflows now use `pip install -r requirements.txt`.

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
