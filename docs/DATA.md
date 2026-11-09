# Data (plan v0, 2026-11-09)

## Area and period

- **Analysis area (AOI):** North Evia, lon **22.80–23.70 E**, lat **38.60–39.05 N** (starting value; refine once we
  have the burn perimeter). Set in `data_prep/config.py`.
- **Climate baseline:** 1991–2020 (+ trends since 1981 where available).
- **Fire:** 3–14 Aug 2021. Pre-fire reference summer 2021 (July), post-fire Sept 2021 → today.

## Sources and what each is for

| Source | Product | Native resolution | Used for | Access |
|---|---|---|---|---|
| NASA POWER | Daily agro-climatology (T2M max/min, PRECTOTCORR, RH, wind, radiation) | ~0.5° × 0.625° | Climate calendar, ET0 (FAO-56), heat/frost days, trends | REST API, no login |
| GPM IMERG | Final run, daily / half-hourly | 0.1° | Rain extremes, rainfall erosivity (RUSLE R) | Earthdata login |
| SMAP | L3 enhanced (SPL3SMP_E) or L4 (SPL4SMGP) | 9 km | Soil-moisture seasonality and anomalies | Earthdata login |
| Landsat 5/7/8/9 | Collection 2 Level-2 surface reflectance | 30 m, 1984 onwards | Field history (crop/fallow/pasture per year), pre-fire baseline, dNBR | USGS EarthExplorer / M2M API, or cloud (STAC) |
| HLS (Landsat + Sentinel-2, NASA) | HLSL30 / HLSS30 v2.0 | 30 m | NDVI time series, bare months, dNBR burn severity, recovery | Earthdata login |
| MODIS | MOD13Q1 NDVI, MOD16A2 ET | 250 m / 500 m | Long NDVI record (2000+), actual ET | Earthdata / AppEEARS |
| NASADEM / SRTM | DEM | 30 m | Slope, LS factor, flow direction | Earthdata login |
| ECOSTRESS | LST, ET | 70 m, irregular | Heat-stress snapshots (optional) | Earthdata login |
| GRACE-FO | Mascon TWS | ~300 km | Regional water-storage trend (context only) | Earthdata login |
| SoilGrids (ISRIC) | Texture, SOC, bulk density | 250 m | Water holding capacity, RUSLE K | Public WCS |
| Crop traits | FAO-56 Kc / season lengths, FAO ECOCROP | table | `data/reference/crops.csv` | Hand-built, cited |

**More detailed / local data to search for:** EFFIS and Copernicus EMS fire perimeter and severity; ESA WorldCover
(10 m) and CORINE land cover; Sentinel-2 (10 m); ESDAC / LUCAS soil and RUSLE layers; ground stations (meteo.gr /
NOA, HNMS) to check satellite values; ELSTAT livestock and crop statistics; any apiary / pasture maps.

Resolution warning: the climate data (POWER, GPM, SMAP) is km-scale. A field is only resolved by 30 m data (HLS, DEM)
and 250 m soil. The app must say so.

## Files (the contract, to fill in as we build)

| File | Content | Owner |
|---|---|---|
| `data/processed/climate_daily.parquet` | per demo point: date, tmax, tmin, precip, et0, … | data |
| `data/processed/grid_30m.nc` | AOI grid: elevation, slope, LS, NDVI stats, soil | data |
| `data/reference/crops.csv` | crop, Kc stages, season, N-fixing, root depth, cover by month, sources | engine |
| `data/reference/rotations.csv` | strategy id, sequence, notes | engine |
| `data/output/<field_id>.json` | indicators + per-strategy scores and explanations | engine |

## Credentials

Earthdata Login (urs.earthdata.nasa.gov) for every member → `~/.netrc` (or `earthaccess.login()`). Never commit.
