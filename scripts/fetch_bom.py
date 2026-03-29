#!/usr/bin/env python3
"""Scrape Box Office Mojo for domestic + worldwide box office data (concurrent).

Reads data/box_office.json (from TMDB fetch) for IMDB IDs,
then scrapes BOM for domestic/international/worldwide gross using 20 threads.

~2,800 movies in ~3-4 minutes with concurrent scraping.

Saves results back into data/box_office.json, adding bom_domestic, bom_international,
bom_worldwide, bom_opening, bom_budget fields.
"""
import json, os, re, sys, time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

BOM_BASE = "https://www.boxofficemojo.com/title"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
MAX_WORKERS = 20


def scrape_bom(imdb_id):
    """Scrape Box Office Mojo for a movie's box office data."""
    url = f"{BOM_BASE}/{imdb_id}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return {"_bom_status": "not_found"}
        if r.status_code == 429:
            time.sleep(5)
            r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        html = r.text

        # The first money spans in the summary section are:
        # [domestic, international, worldwide, opening, budget]
        spans = re.findall(r'<span class="money">\$([\d,]+)</span>', html)
        if len(spans) < 3:
            return {"_bom_status": "no_data"}

        def pm(s):
            return int(s.replace(",", ""))

        result = {
            "bom_domestic": pm(spans[0]),
            "bom_international": pm(spans[1]),
            "bom_worldwide": pm(spans[2]),
        }
        if len(spans) >= 4:
            result["bom_opening"] = pm(spans[3])
        if len(spans) >= 5:
            result["bom_budget"] = pm(spans[4])
        return result
    except Exception as e:
        return None


def main():
    bo_path = "data/box_office.json"
    if not os.path.exists(bo_path):
        print("ERROR: data/box_office.json not found. Run fetch_box_office.py first.")
        sys.exit(1)

    with open(bo_path) as f:
        bo = json.load(f)
    print(f"Loaded {len(bo)} movies from box_office.json")

    # Find movies with IMDB IDs but no BOM data yet
    to_scrape = []
    for slug, data in bo.items():
        imdb = data.get("imdb_id", "")
        if imdb and "bom_domestic" not in data and data.get("_bom_status") is None:
            to_scrape.append((slug, imdb))

    print(f"Movies to scrape from BOM: {len(to_scrape)}")
    if not to_scrape:
        print("Nothing to do.")
        return

    scraped = 0
    errors = 0
    not_found = 0
    start_time = time.time()

    def do_scrape(item):
        slug, imdb_id = item
        return slug, scrape_bom(imdb_id)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(do_scrape, item): item for item in to_scrape}
        done = 0
        for future in as_completed(futures):
            slug, result = future.result()
            done += 1
            if result:
                bo[slug].update(result)
                status = result.get("_bom_status")
                if status in ("not_found", "no_data"):
                    not_found += 1
                else:
                    scraped += 1
            else:
                errors += 1

            if done % 100 == 0:
                elapsed = time.time() - start_time
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(to_scrape) - done) / rate if rate > 0 else 0
                print(f"  Progress: {done}/{len(to_scrape)} ({rate:.1f}/sec, ETA {eta:.0f}s) — scraped={scraped}, not_found={not_found}, errors={errors}")

            # Save progress every 500
            if done % 500 == 0:
                with open(bo_path, "w") as f:
                    json.dump(bo, f, separators=(",", ":"))

    elapsed = time.time() - start_time
    print(f"Done in {elapsed:.1f}s: scraped={scraped}, not_found={not_found}, errors={errors}")

    # Save final
    with open(bo_path, "w") as f:
        json.dump(bo, f, separators=(",", ":"))
    print(f"Saved to {bo_path}")

    # Stats
    with_bom = sum(1 for v in bo.values() if v.get("bom_domestic", 0) > 0)
    print(f"Movies with BOM domestic data: {with_bom}/{len(bo)}")


if __name__ == "__main__":
    main()
