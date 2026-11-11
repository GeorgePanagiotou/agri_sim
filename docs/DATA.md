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
| MODIS | MOD13Q1 NDVI/EVI, MOD16A2GF ET/PET, MOD11A2 LST | 250 m / 500 m / 1 km | Long NDVI record (2000+), actual ET, surface heat | AppEEARS |
| NASADEM / SRTM | DEM | 30 m | Slope, LS factor, flow direction | Earthdata login |
| ECOSTRESS | L3T JET daily ET | 70 m, irregular | Field-scale dry-season water use 2022–2025 | AppEEARS |
| GRACE / GRACE-FO | JPL mascon TWS; GRACE-DA drought percentiles | ~300 km / 0.25° (model) | Regional water-storage trend and drought weeks (context only) | Earthdata login |
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
| `data/processed/power_daily_1981_2026.parquet` | **done** · NASA POWER daily at the study-area cell (23.41 E, 38.85 N): T2M, T2M_MAX/MIN, T2MDEW, RH2M, PRECTOTCORR, WS2M, ALLSKY_SFC_SW_DWN, PS, GWETTOP, GWETROOT · `data_prep/download_power.py` | data |
| `data/processed/power_hourly_2021-10.parquet` | **done** · POWER hourly Oct 2021 (storm Athena): PRECTOTCORR, T2M, WS2M | data |
| `data/processed/landsat_ndvi_monthly_30m.nc` | **done, local only (130 MB, git-ignored)** · monthly median Landsat C2 L2 NDVI 1984–2025, study area, 30 m UTM 34N, uint8 (`ndvi = (v-1)/200 - 0.25`, 0 = no data) + `nobs` · `data_prep/landsat_ndvi_history.py` (~15 min, window reads only) | data |
| `data/processed/landsat_scenes.csv` | **done** · every Landsat scene used (id, date, platform, WRS path/row, cloud cover, valid share) | data |
| `data/processed/landsat_ndvi_harmonization.json` | **done** · NDVI offsets to Landsat 8 from near-same-day pairs: L5/L4 +0.052, L7 +0.030, L9 −0.003 (applied in the cube) · `data_prep/landsat_harmonize.py` | data |
| `data/processed/landsat_dnbr_2021_30m.tif` + `landsat_burn_scenes.csv` | **done** · Landsat 8/9 dNBR of the 2021 fire (3 pre + 3 post scenes) · `data_prep/landsat_burn_2021.py` | data |
| `data/processed/landsat_field_map_30m.tif` | **done** · band 1 land use 2013–2020, band 2 land use 1985–1995 (0 water/none, 1 rainfed field, 2 irrigated summer field, 3 woody, 4 herbaceous/shrub = grazing, 5 bare/built), band 3 burn 2021 (0–4) · water from Landsat QA · `data_prep/landsat_field_map.py` | data |
| `data/processed/landsat_field_years.nc` / `.csv` | **done** · per field pixel and agricultural year (Oct–Sep): 1 crop, 2 fallow/low, 3 summer crop, 9 no data; spring peak NDVI · yearly shares burned vs unburned | data |
| `data/processed/terrain_30m.tif` | **done** · NASADEM on the Landsat grid: elevation, slope, upslope cells, RUSLE LS, upslope burned share · `data_prep/terrain_nasadem.py` | data |
| `data/processed/modis_mcd64a1_2021_burndate.tif` | **done** · MODIS MCD64A1 burn day-of-year 2021 on the Landsat grid · `data_prep/modis_burned_area.py` | data |
| `data/processed/imerg_daily_2001_2025.parquet` / `imerg_daily_area_mean.parquet` / `imerg_monthly_normals_2001_2024.csv` | **done** · GPM IMERG Final daily 2001-01-01..2025-09-30 (9,039 days, 20 cells of 0.1°, 9 inside the area) via GES DISC OPeNDAP (~600 B per day); monthly normals, heavy-rain days, erosivity share · `data_prep/download_imerg_daily.py` | data |
| `data/processed/imagery/` | **done** · small Landsat true-colour GeoTIFF + PNG for 1987, Jul 2021, Aug 2021, Apr 2022, Jun 2025 · `data_prep/landsat_rgb.py` | data |
| `data/processed/imerg_vs_power_october.csv` | **done** · October rain 2000–2024, GPM IMERG monthly (mean / wettest cell) vs POWER | data |
| `data/processed/modis_vi_16day_250m.nc` + `modis_vi_16day_area.parquet` | **done** · MOD13Q1.061 NDVI + EVI, 16-day, 2000-02-18..2025-12-19 (595 steps, 97×88 px), pixel_reliability 0/1 only; area series: mean / p10 / p90 / valid share / cloud share · `data_prep/appeears.py` → `appeears_process.py` | data |
| `data/processed/modis_et_8day_500m.nc` + `modis_et_8day_area.parquet` | **done** · MOD16A2GF.061 (gap-filled) ET + PET, mm per 8-day composite (`days` = composite length; last one of the year is 5–6 days), 2000–2025, non-vegetated fill classes masked; area series + ET/PET ratio | data |
| `data/processed/modis_lst_8day_1km.nc` + `modis_lst_8day_area.parquet` | **done** · MOD11A2.061 day/night land surface temperature °C, 8-day, 2000–2025; QC good, or other-quality with LST error ≤ 2 K | data |
| `data/processed/ecostress_et_scenes.csv` + `ecostress_et_dryseason_70m.nc` | **done** · ECOSTRESS ECO_L3T_JET.002 ETdaily (mm/day; the GeoTIFF tag "W/m²" is wrong) May–Sep 2022–2025: 89 overpasses with UTC + local hour, clear share and stats; per-year May–Sep median at 70 m + `nobs`. Overpass time varies (07:00–19:30 local); early/late passes are less reliable for daily ET; filter on `local_hour` if needed | data |
| `data/processed/smap_l3_daily_9km.nc` + `smap_l3_daily_area.parquet` | **done** · SPL3SMP_E.006 AM/PM soil moisture (top ~5 cm, m³/m³), 2015-03-31..2025-12-31, 4×5 cells of 9 km (10 on land, value on ~48 % of days), `in_area` = cells overlapping the study area (series = their mean). **No retrieval over Evia has "recommended quality"** (coast, relief, forest), so we keep successful retrievals (flag 1, 9): use for seasonality and anomalies, not absolute values. Dry-season mean 0.15–0.18 in 2015–2023, 0.107 in 2024, 0.069 in 2025. **2025 is low-confidence:** SMAP is shifted low all year (wet months too) and its flag mix changed; POWER and GRACE-DA rank 2025 driest too, but put it at the 2024 level ([exploration/2026-11-11_smap_check](../exploration/2026-11-11_smap_check/SMAP_CHECK.md)) | data |
| `data/processed/smap_l4_daily_9km.nc` + `smap_l4_daily_area.parquet` | **pending** · SPL4SMGP.008 surface + root-zone soil moisture, 3-hourly → daily, 2015-03-31..2025. AppEEARS task still processing (2026-11-10); then `appeears.py download agrisim_spl4` + `appeears_process.py smap` | data |
| `data/processed/study_pack/` | **done** · for the team to explore ([README](../data/processed/study_pack/README.md)): vegetation / field-history / water-heat GeoTIFFs on the 30 m grid (before 2016–20 vs after 2022–25), `study_points.csv` (all layers at every field pixel + 300 m grid), `area_monthly_2000_2025.csv` / `area_yearly_…` (all series side by side), `atlas.png` · `data_prep/study_pack.py` | data |
| `data/processed/appeears_granules.csv` | **done** · every granule behind the AppEEARS products (task, granule name) | data |
| `data/processed/grace_mascon_tws_2002_2026.csv` | **done** · JPL GRACE/GRACE-FO mascon CRI RL06.3 v04, monthly terrestrial water storage anomaly (cm), 3×3 cells of 0.5° round Evia; `tws_land_cm` = × CRI gain factor on land (Evia mascon 801, gain 0.726). True resolution ~300 km: **context only** · `data_prep/grace.py mascon` | data |
| `data/processed/grace_da_weekly_2003_2026.parquet` | **done** · GRACE-DA drought indicators (GRACEDADM_CLSM025GL_7D v3.0), weekly percentiles of surface soil moisture, root-zone soil moisture, groundwater, 0.25°, 3×3 cells (4 on land), 2003-02-03..2026-08-31, via Earthdata Cloud OPeNDAP · `data_prep/grace.py da` | data |
| `data/processed/soil_30m.tif` + `soil_summary.csv` | **done** · SoilGrids 2.0 (supporting) 0–30 cm clay/sand/silt %, SOC g/kg, bulk density, stones %, pH, N; AWC 0–30 / 0–100 cm (Saxton & Rawls 2006); RUSLE K (Williams/EPIC) · `data_prep/soil_soilgrids.py` (~4 min, window reads) | data |
| `data/reference/crops.csv` | **draft** · 17 crops: FAO-56 stage lengths (T11), Kc (T12), root depth & p (T22), N-fixing, forage & bee value; each value has a status (fao56 / fao56_group / analog / team_estimate) · see `data/reference/SOURCES.md` | engine |
| `data/reference/rotations.csv` | **draft** · strategies A (current, from Landsat), B legume forage, C bee & soil, D low water, for rainfed fields | engine |
| `data/processed/climate_daily.parquet` | per demo point: date, tmax, tmin, precip, et0, … | data |
| `data/processed/grid_30m.nc` | AOI grid: elevation, slope, LS, NDVI stats, soil | data |
| `data/reference/crops.csv` | crop, Kc stages, season, N-fixing, root depth, cover by month, sources | engine |
| `data/reference/rotations.csv` | strategy id, sequence, notes | engine |
| `data/output/<field_id>.json` | indicators + per-strategy scores and explanations | engine |

**Rule (2026-11-09): imagery and observations in the product are NASA / USGS only** (Landsat, MODIS, GPM, SMAP,
POWER, NASADEM, …). **Supporting data allowed: SoilGrids (soil) and FAO tables (crops).** Sentinel-2, WorldCover and
EFFIS were used only in exploration (`exploration/2026-11-09_area_search/`), not in `data/processed/`.

**Access risk:** GES DISC is retiring its on-premises OPeNDAP (hydro1 already returns HTTP 410). GRACE-DA now uses
Earthdata Cloud OPeNDAP (`opendap.earthdata.nasa.gov`); IMERG still used `gpm1.gesdisc.eosdis.nasa.gov/opendap` on
2026-11-10. If that goes too, switch `download_imerg_daily.py` to the cloud endpoint. Processed files are in the repo,
so the app does not depend on either.

## Credentials

Earthdata Login (urs.earthdata.nasa.gov) for every member → `~/.netrc` (or `earthaccess.login()`). Never commit.
