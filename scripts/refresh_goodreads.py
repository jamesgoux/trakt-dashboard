#!/usr/bin/env python3
"""Fetch Goodreads reading data via RSS feed and save to data/goodreads.json"""
import json, os, sys, time, re
from datetime import datetime
from xml.etree import ElementTree
import urllib.request

GOODREADS_USER_ID = os.environ.get("GOODREADS_USER_ID", "")
if not GOODREADS_USER_ID:
    print("Set GOODREADS_USER_ID environment variable")
    sys.exit(0)  # soft exit — don't break CI

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load existing data to merge
existing = {}
if os.path.exists("data/goodreads.json"):
    with open("data/goodreads.json") as f:
        existing = {b["book_id"]: b for b in json.load(f)}
    print(f"  Existing: {len(existing)} books")

print("=== Goodreads RSS Refresh ===")
books = dict(existing)  # start with existing, merge new
page = 1
new_count = 0

while True:
    url = f"https://www.goodreads.com/review/list_rss/{GOODREADS_USER_ID}?shelf=read&page={page}&per_page=100"
    print(f"  Fetching page {page}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"  Error fetching page {page}: {e}")
        break

    root = ElementTree.fromstring(xml_data)
    items = root.findall(".//item")
    if not items:
        print(f"  No items on page {page}, done.")
        break

    for item in items:
        # Extract fields from RSS
        title = item.findtext("title", "").strip()
        author = item.findtext("author_name", "").strip()
        book_id = item.findtext("book_id", "").strip()
        isbn = item.findtext("isbn", "").strip()
        # num_pages is inside nested <book> element
        book_el = item.find("book")
        num_pages = (book_el.findtext("num_pages", "") if book_el is not None else item.findtext("num_pages", "")).strip()
        avg_rating = item.findtext("average_rating", "").strip()
        user_rating = item.findtext("user_rating", "").strip()
        user_read_at = item.findtext("user_read_at", "").strip()
        user_date_added = item.findtext("user_date_created", "").strip()  # when originally shelved
        book_image = item.findtext("book_large_image_url", "") or item.findtext("book_image_url", "")
        book_published = item.findtext("book_published", "").strip()
        user_shelves = item.findtext("user_shelves", "").strip()
        shelves = [s.strip() for s in user_shelves.split(",") if s.strip()] if user_shelves else []

        # Parse dates
        def parse_date(s):
            if not s:
                return ""
            for fmt in ["%a, %d %b %Y %H:%M:%S %z", "%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
                except Exception:
                    continue
            # Try to extract year at least
            m = re.search(r'\d{4}', s)
            return m.group() if m else ""

        date_read = parse_date(user_read_at)
        date_added = parse_date(user_date_added)

        entry = {
            "book_id": book_id,
            "title": title,
            "author": author,
            "pages": int(num_pages) if num_pages and num_pages.isdigit() else 0,
            "avg_rating": float(avg_rating) if avg_rating else 0,
            "user_rating": int(user_rating) if user_rating and user_rating.isdigit() else 0,
            "date_read": date_read,
            "date_added": date_added,
            "year_read": date_read[:4] if date_read else "",
            "published": book_published,
            "shelves": shelves,
            "image": (book_image or "").strip(),
        }

        if book_id not in books:
            new_count += 1
        books[book_id] = entry

    print(f"  Page {page}: {len(items)} items")
    if len(items) < 100:
        break
    page += 1
    time.sleep(1)  # be polite

# Save
book_list = sorted(books.values(), key=lambda b: b.get("date_read", "") or "0000", reverse=True)
with open("data/goodreads.json", "w") as f:
    json.dump(book_list, f, separators=(",", ":"))

print(f"  Total: {len(book_list)} books ({new_count} new)")
print("Done!")
