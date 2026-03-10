# Iris 👁️

A personal media consumption dashboard aggregating data from **7 sources** into an auto-refreshing web dashboard.

**Live:** [jamesgoux.github.io/iris-stats](https://jamesgoux.github.io/iris-stats/)

## What it does

- **Auto-refreshes every 20 minutes** — Trakt, Letterboxd, Goodreads, Last.fm, setlist.fm
- **Daily full refresh** — cast, studios, crew, headshot/poster/logo backfill, book genres, artist genres
- **Mobile-first** — works as iOS home screen app with eye icon, orientation-aware
- **No manual intervention** — runs entirely on GitHub Actions
- **Type filter** — switch between All, Movies, Shows, Books, Music, Concerts, Theater
- **Year filter** — all sections respect year selection

## Data Sources

| Source | Method | What it provides |
|---|---|---|
| **Trakt.tv** | Public API | Watch history, cast, crew, studios, networks, genres, countries, languages, air dates |
| **Letterboxd** | RSS feed + CSV | Personal ratings, tags (people/locations/streaming/devices), TMDB IDs |
| **Goodreads** | RSS feed | Books read, ratings, page counts, shelves, date read/added |
| **Last.fm** | API | Scrobbles, top artists/albums/tracks, genres, weekly/monthly/yearly activity |
| **setlist.fm** | API | Concert attendance, setlists, song counts, albums |
| **Mezzanine** | CSV import | Theater diary (shows, venues, ratings, companions, tags) |
| **TMDB** | Website scraping | Headshot photos, poster images, network/studio logos |
| **MusicBrainz** | API | Artist genres for concerts |

## Dashboard Sections

### Stats Bar
Total watches, days watched, movies, shows, episodes, books, pages, scrobbles, artists, albums, concerts, sets, artists seen, songs, plays — all year-filterable, zero-value tiles auto-hide.

### 🧬 Lifeline
30-day pulse display centered on x-axis. Watch activity (episodes, movies, books) goes up, listen/live (scrobbles, concerts, plays) goes down. Month selector when year is filtered. Click for chronological detail with timestamps.

### 📈 Timeline
Yearly view (all time) / Monthly view (year selected). Stacked bars: Seasons, Movies, Books, Concerts, Theater. Legend click isolates mediums. Click for top-5-per-medium detail.

### TV & Movies
- 🎭 **Actors + Actresses** — headshots, movies/shows/total
- 🎬 **Directors + ✍️ Writers** — same format
- 📺 **Top Shows** — poster grid with shuffle animation, toggle episodes/duration
- 📺 **Episodes Watched** — yearly/monthly, toggle monthly/weekly
- ⏱️ **Time to Watch** + 📚 **Catch-Up Shows**
- 🎞️ **Movies** — by watch time + most rewatched
- 🎯 **Genres** + 📈 **Genre Trends** — 100% stacked area
- 📡 **Networks** + 🏢 **Studios** — with logos on bars
- 🌍 **Countries** + 💬 **Languages**
- 📅 **Content Release Years** — Year / Decade / New vs Old pie
- 📅 **Day of Week** + 🕐 **Time of Day** (radial clock, 2016 excluded)
- 🖥️ **How I Watch** — Watched With, Where (Home/Family/Theater/Travel), Streaming, Devices
- ⭐ **Ratings** — Letterboxd personal + Trakt community highest/lowest
- 🌅 **First Watches** + 👁️ **Last Watches**

### 📚 Books (Goodreads)
Books Read (toggle books/pages), Time to Read (scrollable all books), Most Read Authors, Book Ratings, Longest/Shortest Books, Genres (Community), My Shelves, Highest/Lowest Rated. All year-filterable.

### 🎧 Music (Last.fm)
Listening Activity (yearly/monthly, toggle Scrobbles/Artists/Albums), Top Artists (All Time/This Year/Last 90 Days), Top Albums, Top Tracks, Genres. Click activity bars for period detail.

### 🎸 Concerts (setlist.fm)
Concerts chart (toggle Shows/Sets/Songs), Most Seen Artists (clickable), Venues (clickable), Genres (MusicBrainz). All year-filterable.

### 🎭 Theater (Mezzanine)
Theater Ratings (clickable), Theater Tags, Top Theaters, Theater Companions. All year-filterable from imported CSV data.

### 📤 CSV Importer
Drag-and-drop auto-detects Letterboxd diary or Mezzanine theater CSV.

## Architecture

```
├── index.html                    ← Auto-generated (don't edit)
├── iris-icon.svg / .png          ← Eye logo
├── templates/dashboard.html      ← HTML template (all charts + JS)
├── scripts/
│   ├── refresh_data.py           ← Main pipeline: all sources → index.html
│   ├── refresh_headshots.py      ← Image backfill (posters→logos→actors→dirs→writers)
│   ├── refresh_letterboxd.py     ← Letterboxd RSS + CSV import
│   ├── refresh_goodreads.py      ← Goodreads RSS feed
│   ├── refresh_lastfm.py         ← Last.fm API (scrobbles, charts, genres)
│   ├── refresh_setlist.py        ← setlist.fm concerts + MusicBrainz albums
│   ├── refresh_book_genres.py    ← Goodreads book page genre scraper
│   └── refresh_artist_genres.py  ← MusicBrainz artist genre backfill
├── data/                         ← Cached data (JSON files, incrementally built)
│   ├── people.json               ← 18K+ cast members
│   ├── headshots.json            ← Actor/director/writer photos
│   ├── posters.json              ← Show poster images
│   ├── logos.json                ← Network/studio logos
│   ├── goodreads.json            ← 318 books with ratings, pages, shelves
│   ├── book_genres.json          ← Community genres per book (scraped)
│   ├── lastfm.json               ← Scrobbles, top lists, weekly/monthly/yearly
│   ├── setlist.json              ← Concert data
│   ├── artist_genres.json        ← MusicBrainz genres per artist
│   ├── song_albums.json          ← Song → album lookups
│   ├── letterboxd.json           ← Letterboxd ratings
│   ├── tag_categories.json       ← Tag classification rules
│   ├── theater_companions.json   ← Companion name list
│   ├── mezzanine.csv             ← Theater diary export
│   └── letterboxd_tags.csv       ← Letterboxd diary with tags
└── .github/workflows/
    ├── refresh-data.yml          ← Every 20 min: Letterboxd + Goodreads + Last.fm + Concerts + Trakt
    └── refresh-headshots.yml     ← Daily 4:15am: full refresh + images + book genres + artist genres
```

## Setup

1. Push to a public GitHub repo
2. Add repository secrets:
   - `TRAKT_CLIENT_ID` — Trakt API client ID
   - `TRAKT_USERNAME` — Trakt username
   - `SETLIST_FM_API_KEY` — setlist.fm API key
   - `GOODREADS_USER_ID` — Goodreads user ID (from profile URL)
   - `LASTFM_API_KEY` — Last.fm API key
   - `LASTFM_USER` — Last.fm username
3. Enable GitHub Pages (deploy from branch main/root)
4. Run first refresh from Actions tab
5. Bookmark the URL on your phone

## Image Backfill

Daily job fetches ~1,000 images: posters → logos → actors → directors → writers (most recent watches first). Book genres scraped from Goodreads pages (100/day). Artist genres from MusicBrainz.

## CSV Imports

- **Letterboxd**: Export diary.csv from letterboxd.com/settings/data, drag-drop onto dashboard
- **Mezzanine**: Export theater diary CSV, drag-drop onto dashboard
- Both auto-detected by column headers

## Technical Notes

- Single HTML file with embedded ECharts, no build step
- All charts use ECharts 5 (single CDN dependency)
- Poster shuffle uses FLIP animation
- Orientation change triggers full re-render (debounced)
- 2016 data zeroed across all charts (bulk-import outlier: 4,257 episodes)
- Lifeline scrobbles: exact for last 35 days (per-day API), approximated from weekly/monthly for older
- Tag categories in data/tag_categories.json control location/streaming/device classification
- Theater companions in data/theater_companions.json separate from descriptive tags
