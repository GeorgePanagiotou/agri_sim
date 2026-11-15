# AgriSim climate API

One request, several sources, one common format. Today: **NASA POWER** and **GPM IMERG**.

Common format: daily **UTC** dates, **canonical units** (mm/day, °C, ...), **WGS84** lon/lat. Every source is converted
in `app/variables.py`; nothing downstream knows about native names or units.

## Run

```bash
# Docker (from the repo root)
docker compose up --build            # http://localhost:8000/docs

# local (from the repo root)
python -m pip install -r service/requirements-dev.txt
python -m uvicorn app.main:app --reload
python -m pytest -q tests
```

Docker mounts `data/processed` read-only (IMERG and the POWER fallback come from there) and keeps the live-call cache
in the `climate-cache` volume.

## Use

```bash
# monthly rain, study area, all sources (best first)
curl "localhost:8000/v1/series/precipitation?area=study_area&start=2021-01-01&end=2021-12-31&aggregate=monthly"
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

`POWER_MODE` auto (live → local fallback) / live / local · `DATA_DIR` · `CACHE_DIR` · `CACHE_TTL_HOURS` (24) ·
`POWER_RETRIES` (3) · `HTTP_TIMEOUT` (60 s) · `MAX_DAYS` (18300).

## Limits (honest)

- **IMERG is served from the cached parquet** (lon 23.2–23.6, lat 38.6–39.1, 2001-01-01..2025-09-30): it needs an Earthdata login and GES DISC OPeNDAP is being retired (docs/DATA.md). Outside that extent it answers `no_data`.
- **POWER live** needs outbound internet; the local fallback only serves areas whose centroid is in the study area.
- POWER and IMERG can disagree a lot on single storm days (e.g. 2021-10-09: 76.7 vs 3.4 mm); that is the data, not the service. Use `comparison`.

## Add a source / variable

1. `app/providers/<name>.py`: class with `name`, `title`, `native_resolution`, `reference`, `fetch(var, area, start, end) -> Fetched` (daily UTC series, canonical unit). Raise `NoData` / `ProviderError`.
2. Register it in `app/providers/__init__.py`.
3. Add `SourceVar(native, factor)` to the variables it supports in `app/variables.py`.
