# Iris 👁️

A personal media consumption dashboard aggregating data from **14 sources** into an auto-refreshing single-page web dashboard.

**Live:** [jamesgoux.github.io/iris-stats](https://jamesgoux.github.io/iris-stats/)

## What it does

- **Auto-refreshes every 10 minutes** — rebuilds from all data sources via GitHub Actions
- **Enrichment every 2 hours** — book genres, artist genres, daily scrobbles, health data
- **Headshots hourly** — TMDB images, sports schedules, per-episode crew credits
- **Mobile-first** — works as iOS home screen app with eye icon, orientation-aware
- **No manual intervention** — runs entirely on GitHub Actions
- **12 type filters** — All, Life, Movies & TV, Movies, Shows, Books, Music, Concerts, Podcasts, Theater, Board Games, Video Games, Sports, Workouts
- **Year filter** — all sections respect year selection
- **Multi-user** — Supabase auth, per-user data isolation, credential encryption

## Data Sources

| Source | Method | What it provides |
|---|---|---|
| **Trakt.tv** | Public API + OAuth | Watch history, cast, crew (23 roles), studios, networks, genres, countries, languages, air dates, Up Next progress |
| **Letterboxd** | RSS + CSV + scraping | Personal ratings, tags (people/locations/streaming/devices), TMDB IDs, watchlist |
| **Goodreads** | RSS | Books read, ratings, page counts, shelves, date read/added |
| **Last.fm** | API (incremental) | Scrobbles, top artists/albums/tracks, genres, weekly/monthly/yearly/daily activity |
| **setlist.fm** | API + archives CSV | Concert attendance, setlists, song counts, albums |
| **Pocket Casts** | Unofficial API + GDPR export | Podcast listening history, episode counts, series data |
| **Serializd** | Login API | TV show/season ratings |
| **Mezzanine** | CSV import | Theater diary (shows, venues, ratings, companions, tags) |
| **TMDB** | Official API + scraping | Headshot photos, poster images, network/studio logos, crew credits, box office data |
| **MusicBrainz** | API | Artist genres for concerts |
| **TheSportsDB** | Public API | Sports schedules for tracked teams (NFL, NHL, MLB, NBA) |
| **JustWatch** | GraphQL API | Streaming/rent/buy availability and prices |
| **GameTrack** | iOS export (CSV) | Video game history, playtime, platforms, PSN data |
| **Apple Health** | Via Hadge → GitHub | Workouts, calories, exercise minutes |

## Dashboard Sections

### Header
Iris logo, combined filter dialog (year + type), jump menu, ⏭️ Up Next button, 🔄 refresh. Year and type filters affect all sections globally.

### Stats Bar
Dynamic stat tiles based on active type filter. Includes: total watches, days watched, movies, shows, episodes, books, pages, scrobbles, artists, albums, concerts, sets, artists seen, songs, plays, podcasts, games, workouts. Zero-value tiles auto-hide.

### 📊 Timeline
Yearly view (all time) or monthly view (year selected). Stacked bars across all media types: Seasons, Movies, Books, Concerts, Theater, Podcasts, Games, Sports. Legend click isolates mediums. Click for top-5-per-medium detail.

### 🧬 Lifeline
30-day pulse display centered on x-axis. Watch activity (episodes, movies, books) goes up, listen/live (scrobbles, concerts, plays) goes down. Month selector when year is filtered. Click to expand into full chronological feed with timestamps, infinite scroll metro timeline.

### TV & Movies

- **🎭 Actors + Actresses** — Headshots, movies/shows/total counts with competition ranking (ties share rank, next skips). 🟢 Green climber highlights for fast-rising talent. Episode depth tiebreaker.
- **🎬 Directors + ✍️ Writers** — Same format with headshots and ranking.
- **🎥 Additional Crew** — 23 TMDB crew roles in masonry 2-column layout. Roles include: Co-Directors, Producers, Original Writers, Story, Casting, Editors, Cinematography, Composers, Lighting, Sound, Exec. Producers, Visual Effects, Camera Operators, Stunts, Asst. Directors, Costume Design, Set Decoration, Makeup & Hair, Production Design, Title Design, Art Direction, and more. Clickable names expand to show titles (accordion behavior). Year filter shows 2+ titles in that year with per-year title lists.
- **📺 Top Shows** — Poster grid with shuffle animation, toggle episodes/duration.
- **📺 Episodes Watched** — Yearly/monthly, toggle monthly/weekly.
- **⏱️ Time to Watch** + **📚 Catch-Up Shows**
- **🎞️ Movies** — By watch time + most rewatched.
- **💰 Box Office** — Stacked area chart (domestic vs worldwide). 3-way toggle: All / Budget Comparison / Worldwide. Click-to-detail per movie.
- **⭐ Ratings** — Letterboxd personal ratings + Serializd TV ratings + Trakt community highest/lowest.
- **🎯 Genres** + **📈 Genre Trends** — 100% stacked area chart.
- **📡 Networks** + **🏢 Studios** — With logos on bars.
- **🌍 Countries** + **💬 Languages**
- **📅 Release Years** — Year / Decade / New vs Old pie.
- **📅 Day of Week** + **🕐 Time of Day** — Radial clock (2016 excluded).
- **🖥️ How I Watch** — Watched With, Where (Home/Family/Theater/Travel), Streaming, Devices.
- **🌅 First Watches** + **👁️ Last Watches**

### 📚 Books (Goodreads)
Books Read (toggle books/pages), Time to Read (scrollable), Most Read Authors, Book Ratings, Longest/Shortest Books, Genres (community-scraped), My Shelves, Highest/Lowest Rated. All year-filterable.

### 🎧 Music (Last.fm)
Listening Activity (yearly/monthly, toggle Scrobbles/Artists/Albums), Top Artists (All Time/This Year/Last 90 Days), Top Albums, Top Tracks, Genres. Click activity bars for period detail.

### 🎸 Concerts (setlist.fm)
Concerts chart (toggle Shows/Sets/Songs), Most Seen Artists (clickable), Venues (clickable), Genres (MusicBrainz). All year-filterable.

### 🎙️ Podcasts (Pocket Casts)
Listening hours, episode counts, top series. Year-filterable.

### 🎭 Theater (Mezzanine)
Theater Ratings (clickable), Theater Tags, Top Theaters, Theater Companions. All year-filterable from imported CSV data.

### 🎲 Board Games (BGStats)
Games played, top games, win rates, player counts. Imported from BGStats JSON export.

### 🎮 Video Games (GameTrack)
Games by playtime, platform breakdown, completion status. 223 games across 7 platforms. Imported from GameTrack CSV.

### 🏟️ Sports (TheSportsDB)
Logged sporting events, team schedules with pre-cached data. Interactive team search, schedule browser. Tracked teams across NFL, NHL, MLB, NBA.

### 🏃 Workouts (Apple Health)
Exercise activity from Apple Health via Hadge → GitHub sync.

### 📤 CSV Importer
Drag-and-drop auto-detects Letterboxd diary CSV, Mezzanine theater CSV, or BGStats JSON export.

## Overlays & Full-Page Views

### ⏭️ Up Next
Full-page overlay for in-progress shows. Features:
- **Episode carousel** — Swipe through recent episodes with poster backgrounds, cast, ratings.
- **Companion tags** — Tag who you watch shows with, filter by companion, colored watch buttons.
- **Sort modes** — Default (sectioned), % Complete, Time Remaining. Dropdown picker.
- **Navigation stack** — Back/forward with swipe gestures, scroll position restore.

### 🔍 Search + Browse
Trakt-powered search within Up Next. Movie detail with mark-as-watched. Show pages with season list, progress tracking. Season pages with episode list and watched indicators.

### 📅 Upcoming Calendar
90-day upcoming episode calendar from Trakt. Date-grouped show tiles, expandable multi-episode bundles, infinite scroll, show page navigation.

### 📋 Watchlist
Letterboxd (266 films) + Trakt (4 shows) watchlists with JustWatch streaming/rent/buy prices. Movie/TV toggle, sort controls, runtime display.

### ⚙️ Settings
Multi-user settings overlay with 13 service configuration cards. Supabase-backed credential storage with pgcrypto AES-256 encryption. Trakt OAuth device code flow built in.

## Architecture

```
├── index.html                      ← Auto-generated (don't edit)
├── iris-icon.svg / .png            ← Eye logo (SVG + 180x180 PNG for iOS)
├── requirements.txt                ← Python deps (requests>=2.31)
├── vercel.json                     ← Static site config
├── templates/
│   └── dashboard.html              ← HTML template (~8,976 lines), all charts + JS
├── scripts/
│   ├── refresh_data.py             ← Main pipeline: all sources → index.html (~2,700 lines)
│   ├── refresh_headshots.py        ← TMDB image backfill (posters→logos→actors→dirs→writers)
│   ├── refresh_letterboxd.py       ← Letterboxd RSS + CSV tag import
│   ├── refresh_goodreads.py        ← Goodreads RSS feed
│   ├── refresh_lastfm.py           ← Last.fm incremental charts
│   ├── refresh_pocketcasts.py      ← Pocket Casts API
│   ├── refresh_serializd.py        ← Serializd login + ratings
│   ├── refresh_setlist.py          ← setlist.fm concerts + MusicBrainz albums
│   ├── refresh_upnext.py           ← Trakt progress + JustWatch + TMDB → Up Next
│   ├── refresh_upcoming.py         ← Trakt calendar (90 days ahead)
│   ├── refresh_watchlist.py        ← Letterboxd+Trakt watchlists + JustWatch prices
│   ├── refresh_book_genres.py      ← Goodreads page genre scraper
│   ├── refresh_artist_genres.py    ← MusicBrainz artist genre backfill
│   ├── refresh_sports_schedule.py  ← TheSportsDB schedule pre-cache
│   ├── refresh_health.py           ← Apple Health via Hadge → GitHub
│   ├── refresh_boardgames.py       ← BoardGameGeek collection
│   ├── refresh_trakt_token.py      ← Auto-refresh Trakt OAuth token
│   ├── backfill_lastfm_daily.py    ← Daily scrobble backfill
│   ├── backfill_crew_episodes.py   ← Per-episode TMDB crew credits
│   ├── fetch_box_office.py         ← TMDB revenue + Box Office Mojo scraping
│   ├── import_gametrack.py         ← GameTrack CSV → video games data
│   ├── import_pocketcasts_export.py ← Pocket Casts GDPR export
│   ├── import_letterboxd_watched.py ← Letterboxd watched.csv backfill
│   ├── trakt_auth.py               ← One-time OAuth device code flow
│   ├── utils.py                    ← Shared: retry_request(), get_trakt_access_token()
│   ├── supabase_config.py          ← Lightweight Supabase REST client
│   ├── user_config.py              ← Per-user config loader
│   ├── run_user_pipeline.py        ← Per-user pipeline orchestrator
│   ├── process_refresh_queue.py    ← Process pending user refresh requests
│   └── setup_encryption.py         ← Generate encryption key + verify setup
├── data/                           ← Cached JSON data (incrementally built)
│   ├── people.json                 ← 61K+ cast members
│   ├── headshots.json              ← 10K+ actor/director/writer photos
│   ├── posters.json                ← Show poster images
│   ├── logos.json                  ← Network/studio logos
│   ├── other_crew.json             ← 23 crew roles, ~10K people
│   ├── crew_episodes.json          ← Per-episode crew credits
│   ├── box_office.json             ← Movie box office (TMDB + BOM)
│   ├── goodreads.json              ← 318 books with ratings, pages, shelves
│   ├── book_genres.json            ← Community genres per book (scraped)
│   ├── lastfm.json                 ← Scrobbles, top lists, weekly/monthly/yearly
│   ├── lastfm_daily.json           ← Per-day scrobble counts
│   ├── setlist.json                ← Concert data
│   ├── artist_genres.json          ← MusicBrainz genres per artist
│   ├── pocketcasts.json            ← Podcast episodes + series
│   ├── serializd.json              ← TV show/season ratings
│   ├── letterboxd.json             ← Letterboxd ratings + tags
│   ├── gametrack.json              ← 223 games, 1,292 hours
│   ├── boardgames.json             ← Board game collection
│   ├── health.json                 ← Apple Health workouts
│   ├── sports.json                 ← Logged sporting events
│   ├── sports_schedule.json        ← 805 cached games, 7 teams
│   ├── up_next.json                ← In-progress show data
│   ├── upcoming.json               ← 90-day episode calendar
│   ├── watchlist.json              ← Letterboxd + Trakt watchlists
│   ├── tag_categories.json         ← Tag classification rules
│   ├── theater_companions.json     ← Companion name list
│   ├── slug_tmdb.json              ← 332 slug→TMDB ID mappings
│   ├── tmdb_credits_done.json      ← 3,091 slugs with credits fetched
│   ├── tmdb_trakt_cache.json       ← 3,065 TMDB→Trakt slug mappings
│   ├── trakt_auth.json             ← Trakt OAuth tokens (auto-refreshed)
│   ├── mezzanine.csv               ← Theater diary export
│   └── letterboxd_tags.csv         ← Letterboxd diary with tags
└── .github/workflows/
    ├── refresh-data.yml            ← Every 10 min: Core Build (all sources → rebuild index.html)
    ├── refresh-enrichment.yml      ← Every 2 hours: genres, daily scrobbles, health, full refresh
    ├── refresh-headshots.yml       ← Hourly: headshots, sports schedules, crew episodes
    ├── refresh-upnext.yml          ← Manual: standalone Up Next + Calendar refresh
    ├── refresh-watchlist.yml       ← Manual: standalone Watchlist + JustWatch refresh
    ├── refresh-boardgames.yml      ← Manual: BoardGameGeek collection refresh
    ├── refresh-trakt-token.yml     ← Manual: force Trakt token refresh
    ├── refresh-sources.yml         ← Manual: standalone external source refresh
    └── fetch-box-office.yml        ← Manual: TMDB + BOM box office scraping
```

## How it works

1. **GitHub Actions** runs `refresh_data.py` every 10 minutes
2. The pipeline fetches watch history from Trakt, ratings from Letterboxd, and data from all other sources
3. All data is cached incrementally in `data/*.json` — only new entries are fetched each run
4. The pipeline reads `templates/dashboard.html` and fills 5 placeholders:
   - `__DASHBOARD_DATA__` — JSON data blob with all aggregated data
   - `__BUILD_TIME__` — ISO timestamp
   - `__IRIS_EMBEDDED_USER__` — Username for multi-user
   - `__SUPABASE_URL__` / `__SUPABASE_ANON_KEY__` — Auth config
5. Output `index.html` is committed and deployed via GitHub Pages
6. Enrichment jobs (headshots, genres, crew credits) run on separate schedules to avoid slowing the core build

## Setup

1. Push to a public GitHub repo
2. Add repository secrets:
   - **Trakt:** `TRAKT_CLIENT_ID`, `TRAKT_CLIENT_SECRET`, `TRAKT_ACCESS_TOKEN`, `TRAKT_REFRESH_TOKEN`, `TRAKT_USERNAME`
   - **TMDB:** `TMDB_API_KEY`, `TMDB_BEARER_TOKEN`
   - **Last.fm:** `LASTFM_API_KEY`, `LASTFM_USER`
   - **setlist.fm:** `SETLIST_FM_API_KEY`
   - **Goodreads:** `GOODREADS_USER_ID`
   - **Pocket Casts:** `POCKETCASTS_EMAIL`, `POCKETCASTS_PASSWORD`
   - **Serializd:** `SERIALIZD_EMAIL`, `SERIALIZD_PASSWORD`
   - **Board Games:** `BGG_PASSWORD`
   - **Health:** `GH_HEALTH_TOKEN` (PAT for private health repo)
   - **Supabase:** `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`
3. Enable GitHub Pages (deploy from branch `main`, root `/`)
4. Run `trakt_auth.py` for initial Trakt OAuth device code flow
5. Run first refresh from the Actions tab
6. Bookmark the URL — add to iOS home screen for app-like experience

## CSV / JSON Imports

- **Letterboxd**: Export `diary.csv` from [letterboxd.com/settings/data](https://letterboxd.com/settings/data), drag-drop onto dashboard
- **Mezzanine**: Export theater diary CSV, drag-drop onto dashboard
- **BGStats**: Export board game JSON from the BGStats app, drag-drop onto dashboard
- All auto-detected by column headers / file structure

## Technical Notes

- Single HTML file (~8,976 lines) with embedded ECharts 5 (single CDN dependency), no build step
- All charts use ECharts — responsive, dark theme, consistent styling
- Poster shuffle uses FLIP animation
- Orientation change triggers full re-render (debounced)
- 2016 data zeroed across all charts (bulk-import outlier: 4,257 episodes)
- Lifeline scrobbles: exact for last 35 days (per-day API), approximated from weekly/monthly for older
- TMDB crew extraction: 40+ job titles mapped to 23 role keys, auto-detects new roles and triggers re-fetch
- Up Next navigation: full stack with back/forward, scroll position restore, swipe gestures
- Companion tags: localStorage + Supabase sync, targeted DOM updates (no full re-render)
- Trakt token: auto-refreshed every 10-min build when <2 days remaining, stored in `data/trakt_auth.json`
- TMDB→Trakt slug cache: 3,065 entries, saves ~11 minutes per full rebuild
- Box office: concurrent TMDB API + Box Office Mojo scraping for domestic/worldwide/budget data
