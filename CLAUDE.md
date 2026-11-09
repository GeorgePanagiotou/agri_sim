# AgriSim — rules for Claude Code (whole repo)

**What we build:** a Streamlit decision-support tool for farmers in **North Evia, Greece**, after the August 2021
wildfires. For a field, it shows the local conditions from NASA data (climate, water balance, bare-soil months,
erosion risk, vegetation recovery) and compares **at least 3 crop rotations, including the current one**. For each:
why it is suggested, the evidence, the benefits, the information gaps and the risks that need local expert review.
It supports farmer judgment, never replaces it.

**Read first:** [docs/STORY.md](docs/STORY.md) (what the demo shows), then the doc for your part.

## Who works where

| Folder | What |
|---|---|
| `data_prep/` | Download and harmonize the data (NASA + soil + reference tables) |
| `data/raw/` | Downloads, git-ignored |
| `data/processed/` | Harmonized inputs on the common analysis grid (compact files in git, big files local) |
| `data/reference/` | Small hand-made tables: crop traits, rotations, sources (in git) |
| `engine/` | Indicators, water balance, erosion, rotation scoring (plain Python library, no Streamlit) |
| `data/output/` | Pre-computed engine results for the demo fields (small, in git) |
| `app/` | Streamlit app; reads `data/` and calls `engine/` functions, no downloads |
| `docs/` | Short docs; keep them current when something changes |
| `exploration/` | Dated data checks for the team: figures, small results, scripts (may use non-NASA data; not the product) |

If you need something in another part to change, write it in [docs/TASKS.md](docs/TASKS.md) under "Requests".

## Hard rules

1. **The formats in [docs/DATA.md](docs/DATA.md) are the contract** between data, engine and app. Change them only
   after agreeing, and update the doc in the same commit.
2. **No database, no separate backend.** The app never calls external APIs at runtime (except base-map tiles).
3. **Explainable first.** Every number the app shows must trace back to a dataset or a cited table. Show uncertainty
   and assumptions; flag what needs local review.
4. **Keep it simple.** A clear, working demo beats extra features. No feature unless it is in docs/STORY.md.
5. **Never commit large data or secrets.** Keep every committed file well under 50 MB. No Earthdata / API
   credentials in code (use `~/.netrc` or env vars).
6. **Never disable TLS verification.**
6b. **Product data = NASA/USGS only** (Landsat, MODIS, GPM, SMAP, POWER, NASADEM, ECOSTRESS, GRACE), plus supporting SoilGrids + FAO tables. Sentinel-2,
   WorldCover, EFFIS only in `exploration/`. Download small (windows/subsets), list scenes used, delete raw imagery.
7. Times in **UTC** (daily data: calendar dates). Coordinates **WGS84 lon/lat** (EPSG:4326) unless a file says otherwise.
8. Small commits with clear messages.

## Python environment

The virtual environment lives one level up: `..\.venv` (Python 3.11).
Run scripts from the repo root: `..\.venv\Scripts\python.exe data_prep\<script>.py`.
App: `..\.venv\Scripts\streamlit run app/streamlit_app.py`.
Add any new package to `requirements.txt`.
