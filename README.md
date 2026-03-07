# Iris 👁️

A personal media consumption dashboard aggregating data from **Trakt.tv** and **Letterboxd** into an auto-refreshing web dashboard.

**Live:** [jamesgoux.github.io/trakt-dashboard](https://jamesgoux.github.io/trakt-dashboard/)

## What it does

- **Auto-refreshes every 20 minutes** — Trakt watch history + Letterboxd RSS
- **Daily full refresh** — cast, studios, crew, headshot/poster/logo backfill
- **Mobile-first** — works as iOS home screen app with eye icon
- **No manual intervention** — runs entirely on GitHub Actions

## Data Sources

| Source | Method | What it provides |
|---|---|---|
| **Trakt.tv** | Public API | Watch history, cast, crew, studios, networks, genres, countries, languages, air dates |
| **Letterboxd** | RSS feed | Personal ratings, rewatches, likes, TMDB IDs (100 most recent) |
| **Letterboxd CSV** | Manual export | Full diary history with tags (quarterly upload via in-page importer) |
| **TMDB** | Website scraping | Headshot photos, poster images, studio logos (incremental daily) |

## Dashboard Sections

1. Stats tiles — total watches, movies, shows, episodes, days watched
2. 🎭 Actors + Actresses — headshots, movies/shows/total, click to expand
3. 🎬 Directors + ✍️ Writers — same format, all genders combined
4. 📺 Shows — by duration + by episodes (side-by-side)
5. ⏱️ Time to Watch — avg days between air date and your first watch
6. 📚 Catch-Up Shows — shows watched 1+ years after airing
7. 🎞️ Movies — by total watch time + most rewatched
8. 📊 Monthly Activity — stacked movie/episode timeline
9. 🎯 Genres + 📈 Genre Trends — 100% stacked area (year-over-year or monthly)
10. 📡 Networks + 🏢 Studios — stacked movie/show bars, clickable
11. 🌍 Countries + 💬 Languages — flag emojis, full language names
12. 📅 Content Release Years — toggle: Year / Decade / New vs Old pie
13. 📅 Day of Week + 🕐 Time of Day + 📈 Yearly
14. 🖥️ How I Watch — Watched With, Where, Streaming, Devices
15. ⭐ Ratings — personal + community highest/lowest
16. 🌅 First Watches + 👁️ Last Watches
17. 📤 CSV Importer — drag-and-drop Letterboxd diary.csv

## Architecture

```
├── index.html                 ← Auto-generated (don't edit)
├── iris-icon.svg / .png       ← Eye logo
├── templates/dashboard.html   ← HTML template
├── scripts/
│   ├── refresh_data.py        ← Main pipeline: Trakt → index.html
│   ├── refresh_headshots.py   ← Image backfill (posters→logos→actors→dirs→writers)
│   └── refresh_letterboxd.py  ← Letterboxd RSS + CSV import
├── data/                      ← Cached data (JSON files, incrementally built)
└── .github/workflows/         ← GitHub Actions (20-min + daily)
```

## Setup

1. Push to a public GitHub repo
2. Add secrets: `TRAKT_CLIENT_ID` + `TRAKT_USERNAME`
3. Enable GitHub Pages (deploy from branch main/root)
4. Run first refresh from Actions tab
5. Bookmark the URL on your phone

## Image Backfill Priority

Daily job fetches ~1,000 images: posters → logos → actors → directors → writers (most recent watches first). Full coverage in ~1 month.

## Letterboxd Tags

Export diary.csv from letterboxd.com/settings/data, then either drag-drop onto the dashboard CSV importer or push to data/letterboxd_tags.csv.
