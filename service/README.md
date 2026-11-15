# AgriSim climate API

One request, several sources, one common format. Today: **NASA POWER** and **GPM IMERG**.

Common format: daily **UTC** dates, **canonical units** (mm/day, °C, ...), **WGS84** lon/lat. Every source is converted
in `app/variables.py`; nothing downstream knows about native names or units.

## Run

```bash
# Docker (from the repo root)
docker compose up --build            # http://localhost:8000/docs

# local: run from service/ (from the repo root, `app` would be the Streamlit folder)
cd service
python -m pip install -r requirements-dev.txt   # pins need Python 3.12 (the Docker image);
                                                 # in the project venv (3.11): pip install fastapi uvicorn httpx
python -m uvicorn app.main:app --reload
python -m pytest -q                              # offline tests: fake repo + mocked POWER (tests/test_api.py)
```

Docker mounts `configs/` and `data/` read-only (area registry, IMERG files, POWER fallback) and keeps the live-call
cache in the `climate-cache` volume. Locally the service finds the repo by walking up to `configs/areas`; set
`REPO_ROOT` to point elsewhere.

The Streamlit app's **Area explorer** page (`app/area_explorer.py`) uses this API at `AGRISIM_API_URL`
(default `http://localhost:8000`). When the API is down it runs the same code in-process.

## Areas

Named areas come from the data pipeline's registry, `configs/areas/<name>.yaml`, re-read on every request:

| Name | What |
|---|---|
| `<name>` | the area's study box (where its data was downloaded) |
| `<name>_aoi` | the wider analysis box, if the config has one |
| `<name>_pilot` | the pilot point |
| `study_area`, `aoi`, `istiaia_plain`, `mantoudi_valley`, `limni_slope` | older Evia names, kept as aliases |

A new area appears as soon as `python -m agrisim.pipelines.prepare_area --name <name> --bbox W E S N` writes its
config. IMERG and the POWER fallback come from that area's files once its pipeline steps have run. A `bbox` or
point inside a prepared study box uses that area's files. Anywhere else, only live POWER answers.

## Use

```bash
# monthly rain, Evia study area, all sources (best first); 2025-10 onward = IMERG Late scaled to Final
curl "localhost:8000/v1/series/precipitation?area=evia&start=2025-01-01&end=2026-10-31&aggregate=monthly"
# which areas exist (configs/areas) and which local files each has
curl "localhost:8000/v1/areas"
# a point, only IMERG, as CSV
curl "localhost:8000/v1/series/precipitation?lon=23.47&lat=38.80&start=2021-10-01&end=2021-10-31&sources=imerg&format=csv"
# a bbox (west,south,east,north), POWER first
curl "localhost:8000/v1/series/temperature_max?bbox=23.3,38.7,23.5,38.9&start=2021-07-01&end=2021-07-31&sources=power"
```

| Endpoint                                        |                                                                                                                                                                             |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /v1/series/{variable}`                     | the data. Area: `area=` name, or `lon`+`lat`, or `bbox=`. `start`, `end` required. `sources=a,b` (order = priority), `aggregate=daily\|monthly\|yearly`, `format=json\|csv` |
| `GET /v1/variables`, `/v1/sources`, `/v1/areas` | what exists                                                                                                                                                                 |
| `GET /health`                                   | status + which local files are present                                                                                                                                      |

Response: `data[]` with `value` (chosen), `selected_source`, `values{source: x}`; `sources{}` with origin, native
resolution, cells used, coverage, notes; `comparison[]` (overlap days, bias, RMSE, correlation between sources).

## Harmonization rules

- **Time:** both sources are UTC calendar days. Checked on the repo data (9,039 overlapping days): correlation is highest at lag 0 (0.63 daily, 0.73 monthly), so no day shift.
- **Area → one value:** IMERG = mean of the 0.1° cells overlapping the area (same rule as `data_prep`, matches `imerg_daily_area_mean.parquet`). POWER = the single 0.5°×0.625° cell at the area centroid, so it cannot resolve anything smaller than ~55 km.
- **`value`:** first source with data, in `sources_priority`. A series can therefore switch source over time (see `selected_source`); pass a single source for a homogeneous series.
- **Monthly / yearly:** sums need 100 % of the calendar days, means 90 %; otherwise `null` (also for partial months at the edges of the range).
- **Missing:** `null`, never 0.

## Config (env)

`POWER_MODE` auto (live → local fallback) / live / local · `REPO_ROOT` · `CACHE_DIR` · `CACHE_TTL_HOURS` (24) ·
`POWER_RETRIES` (3) · `HTTP_TIMEOUT` (60 s) · `MAX_DAYS` (18300).

## Limits (honest)

- **IMERG is served from each prepared area's files.** No live call: IMERG needs an Earthdata login.
  - **Final** (gauge-adjusted) covers 2001 to about 3.5 months ago (`imerg_daily_2001_2025.parquet`).
  - **After that, the Late Run** (`imerg_late_daily.parquet`, refreshed by `data_prep/download_imerg_late.py`).
    Late is not gauge-adjusted and read 20–50 % wetter than Final over Evia in 2023–2025, so Late days are
    multiplied by the monthly factors in `imerg_late_to_final.csv` (`data_prep/imerg_late_calibration.py`).
  - Final always wins where both exist. The `imerg` source notes say from which day Late is used (`final_until`,
    `late_days`). Treat Late values as provisional.
  - Outside every prepared area, IMERG answers `no_data`.
- **POWER live** needs outbound internet. TLS is checked against the OS certificate store when `truststore` is
  installed (works behind TLS-inspecting proxies); verification is never disabled. The local fallback serves
  prepared areas only.
- POWER and IMERG can disagree a lot on single storm days (e.g. 2021-10-09: 76.7 vs 3.4 mm); that is the data, not the service. Use `comparison`.

## Add a source / variable

1. `app/providers/<name>.py`: class with `name`, `title`, `native_resolution`, `reference`, `fetch(var, area, start, end) -> Fetched` (daily UTC series, canonical unit). Raise `NoData` / `ProviderError`.
2. Register it in `app/providers/__init__.py`.
3. Add `SourceVar(native, factor)` to the variables it supports in `app/variables.py`.
