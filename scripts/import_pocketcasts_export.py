#!/usr/bin/env python3
"""
One-time import: Parse Pocket Casts data export (data/data.txt) to build
accurate listening history with real timestamps.
Replaces init/pub entries in pocketcasts_history.json with export data.
"""

import os, json
from datetime import datetime, timezone
from collections import defaultdict

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXPORT_FILE = "data/data.txt"
if not os.path.exists(EXPORT_FILE):
    print("No data/data.txt found, skipping"); exit(0)

# Skip if already imported
if os.path.exists("data/.pc_export_imported"):
    print("Pocket Casts export already imported, skipping"); exit(0)

print("=== Importing Pocket Casts Export ===")

lines = open(EXPORT_FILE, encoding="utf-8").readlines()

# Parse Podcasts section to build UUID -> name map
podcast_names = {}
section = None
for line in lines:
    stripped = line.strip()
    if stripped == "Podcasts":
        section = "podcasts_header"
        continue
    if stripped == "Episodes":
        section = "episodes_header"
        continue
    if stripped == "History":
        section = "history_header"
        continue
    if stripped.startswith("--------"):
        if section == "podcasts_header":
            section = "podcasts_cols"
        elif section == "episodes_header":
            section = "episodes_cols"
        elif section == "history_header":
            section = "history_cols"
        continue
    if section == "podcasts_cols":
        section = "podcasts"
        continue  # skip column header
    if section == "episodes_cols":
        section = "episodes"
        continue
    if section == "history_cols":
        section = "history"
        continue
    if stripped == "":
        section = None
        continue

# Re-parse properly — need podcast names from the API data
# The export only has UUIDs. Load existing pocketcasts.json for names.
pc_data = {}
if os.path.exists("data/pocketcasts.json"):
    with open("data/pocketcasts.json") as f:
        pc_data = json.load(f)

# Build UUID -> name from the "all" list
uuid_to_name = {}
for pod in pc_data.get("all", []) + pc_data.get("top", []):
    if pod.get("uuid") and pod.get("title"):
        uuid_to_name[pod["uuid"]] = pod["title"]

print(f"  Known podcast names: {len(uuid_to_name)}")

# Parse History section
history_entries = []
in_history = False
past_header = False
for line in lines:
    stripped = line.strip()
    if stripped == "History":
        in_history = True
        continue
    if in_history and stripped.startswith("--------"):
        continue
    if in_history and stripped.startswith("uuid,"):
        past_header = True
        continue
    if in_history and past_header and stripped == "":
        break
    if in_history and past_header and "," in stripped:
        parts = stripped.split(",", 5)
        if len(parts) >= 5:
            ep_uuid = parts[0]
            modified_ms = parts[1]
            podcast_uuid = parts[2]
            published_ts = parts[3]
            title = parts[4] if len(parts) > 4 else ""
            # Remove URL if it's appended
            if title and ",http" in title:
                title = title[:title.index(",http")]
            
            try:
                listen_date = datetime.fromtimestamp(int(modified_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                podcast_name = uuid_to_name.get(podcast_uuid, f"Unknown ({podcast_uuid[:8]})")
                history_entries.append({
                    "uuid": ep_uuid,
                    "d": listen_date,
                    "p": podcast_name,
                    "t": title,
                    "src": "export",
                })
            except Exception:
                pass

print(f"  Parsed {len(history_entries)} history entries from export")

# Load existing history
existing = {}
if os.path.exists("data/pocketcasts_history.json"):
    with open("data/pocketcasts_history.json") as f:
        existing = json.load(f)

# Replace init/pub entries with export data, keep poll entries
replaced = 0
added = 0
for entry in history_entries:
    uid = entry["uuid"]
    if uid in existing:
        if existing[uid].get("src") == "poll":
            continue  # keep real polled data
        existing[uid] = {
            "p": entry["p"],
            "t": entry["t"],
            "d": entry["d"],
            "dur": existing[uid].get("dur", 0),
            "played": existing[uid].get("played", 0),
            "src": "export",
        }
        replaced += 1
    else:
        existing[uid] = {
            "p": entry["p"],
            "t": entry["t"],
            "d": entry["d"],
            "dur": 0,
            "played": 0,
            "src": "export",
        }
        added += 1

with open("data/pocketcasts_history.json", "w") as f:
    json.dump(existing, f, separators=(",", ":"))

# Rebuild pocketcasts.json yearly/monthly from updated history
yearly = defaultdict(lambda: {"hrs": 0, "eps": 0})
monthly = defaultdict(lambda: {"hrs": 0, "eps": 0})
for ev in existing.values():
    d = ev.get("d", "")
    if len(d) < 7:
        continue
    yr = d[:4]
    mo = d[:7]
    dur_hrs = (ev.get("played", 0) or ev.get("dur", 0)) / 3600
    yearly[yr]["hrs"] = round(yearly[yr]["hrs"] + dur_hrs, 1)
    yearly[yr]["eps"] += 1
    monthly[mo]["hrs"] = round(monthly[mo]["hrs"] + dur_hrs, 1)
    monthly[mo]["eps"] += 1

pc_data["yearly"] = [{"yr": y, **d} for y, d in sorted(yearly.items())]
pc_data["monthly"] = [{"month": m, **d} for m, d in sorted(monthly.items())]

with open("data/pocketcasts.json", "w") as f:
    json.dump(pc_data, f, separators=(",", ":"))

# Mark as done
with open("data/.pc_export_imported", "w") as f:
    f.write(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))

# Stats
sources = defaultdict(int)
for v in existing.values():
    sources[v.get("src", "?")] += 1
print(f"  Replaced: {replaced}, Added: {added}")
print(f"  Total history: {len(existing)} entries")
print(f"  Sources: {dict(sources)}")

# Date range
dates = sorted(set(v["d"] for v in existing.values() if v.get("d")))
if dates:
    print(f"  Date range: {dates[0]} to {dates[-1]}")
print("Done!")
