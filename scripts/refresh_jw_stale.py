#!/usr/bin/env python3
"""
Refresh stale JustWatch prices in data/watchlist.json.
Runs via enrichment workflow (every 2h). Re-fetches items whose jw_ts
is older than JW_STALE_HOURS, oldest first, up to JW_BUDGET per run.
"""
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refresh_watchlist import fetch_justwatch, slugify_for_jw, JW_STALE_HOURS

JW_BUDGET = 100  # max stale refreshes per enrichment run


def run():
    print("=== JustWatch Stale Price Refresh ===")

    if not os.path.exists("data/watchlist.json"):
        print("  No watchlist.json found, skipping")
        return

    with open("data/watchlist.json") as f:
        wl = json.load(f)

    now = int(time.time())
    stale_cutoff = now - JW_STALE_HOURS * 3600

    # Collect all items (movies + shows) with stale or missing jw_ts
    all_items = []
    for item in wl.get("movies", []):
        item["_media_type"] = "movie"
        all_items.append(item)
    for item in wl.get("shows", []):
        item["_media_type"] = "show"
        all_items.append(item)

    stale = [i for i in all_items if i.get("slug") and i.get("jw_ts", 0) < stale_cutoff]
    stale.sort(key=lambda x: x.get("jw_ts", 0))  # oldest first

    print(f"  Total items: {len(all_items)}, stale (>{JW_STALE_HOURS}h): {len(stale)}")

    refreshed = 0
    for item in stale:
        if refreshed >= JW_BUDGET:
            break

        slug = item["slug"]
        media_type = item["_media_type"]
        jw_data = fetch_justwatch(slug, media_type, tmdb_id=item.get("tmdb_id"),
                                  title=item.get("title"), year=item.get("year"))

        if jw_data:
            old_jw = item.get("jw", {})
            # Log price changes
            old_rent = (old_jw.get("r") or [{}])[0].get("p", "") if old_jw else ""
            new_rent = (jw_data.get("r") or [{}])[0].get("p", "") if jw_data else ""
            old_buy = (old_jw.get("b") or [{}])[0].get("p", "") if old_jw else ""
            new_buy = (jw_data.get("b") or [{}])[0].get("p", "") if jw_data else ""
            changes = []
            if old_rent != new_rent:
                changes.append(f"rent {old_rent or 'none'}\u2192{new_rent or 'none'}")
            if old_buy != new_buy:
                changes.append(f"buy {old_buy or 'none'}\u2192{new_buy or 'none'}")
            if changes:
                print(f"    {item.get('title','?')}: {', '.join(changes)}")

            item["jw"] = jw_data

        item["jw_ts"] = now
        refreshed += 1
        time.sleep(0.3)

    # Clean up temp keys before saving
    for item in all_items:
        item.pop("_media_type", None)

    if refreshed > 0:
        with open("data/watchlist.json", "w") as f:
            json.dump(wl, f, separators=(",", ":"))
        print(f"  Refreshed {refreshed} items, saved to data/watchlist.json")
    else:
        print(f"  No stale items to refresh")


if __name__ == "__main__":
    run()
