# Study pack: every layer over the study area, for the team to explore (2026-11-11)

Built by `data_prep/study_pack.py` from the files in `data/processed/` (NASA/USGS data + SoilGrids). Rebuild:
`..\.venv\Scripts\python.exe data_prep\study_pack.py` from `agrisim/` (~2 min; needs the local Landsat NDVI cube).

**Start with `atlas.png`**: 16 key layers on one page.

**Periods:** *before* = 2016–2020, *after* = 2022–2025. The fire year 2021 is left out of both; `ndvi_autumn_2021`
shows it on its own.

**Grid:** every GeoTIFF is on the same 30 m grid as the other `data/processed/*_30m.tif` (UTM 34N, EPSG:32634,
754 × 541 px). Layers overlay exactly, and the same row/col means the same place in every file. Sea and no-data = NaN.

## Open in QGIS

Drag a `.tif` in → Properties → Symbology → *Singleband pseudocolor* → pick the band (band names are shown). Notes on
the bands are under Properties → Information. Put `../imagery/landsat_rgb_*.tif` underneath for context. For the
CSVs, use *Add Delimited Text Layer*, X = `lon`, Y = `lat`, CRS EPSG:4326.

**Coarse layers look blocky on purpose:** the MODIS ET cells are 500 m, MODIS LST 1 km and IMERG rain ~10 km. Each cell
has one value and was not smoothed. Don't read field-scale meaning into them. The 30 m layers (Landsat, NASADEM) and
the 70 m ECOSTRESS layer do resolve fields.

## GeoTIFFs

### `vegetation_landsat_30m.tif`: Landsat NDVI (30 m), 11 bands
Medians of the monthly harmonised Landsat NDVI (`landsat_ndvi_monthly_30m.nc`).

| Band | Meaning |
|---|---|
| `ndvi_summer_before` / `_after` | Jun–Aug |
| `ndvi_spring_before` / `_after` | Mar–May (winter crops, pasture peak) |
| `ndvi_autumn_before` / `_after` | Oct–Nov: how much cover the soil has when the autumn storms come |
| `ndvi_autumn_2021` | Oct–Nov 2021, just after the fire (storm Athena) |
| `bare_months_per_year_before` / `_after` | months a year with NDVI < 0.2 (share of clear months × 12) |
| `ndvi_summer_change`, `ndvi_autumn_change` | after − before (negative = less green) |

### `fields_history_30m.tif`: crop / fallow history (field pixels only), 6 bands
From `landsat_field_years.nc` (agricultural years Oct–Sep). *Before* here is 2013–2020, the period the field map was
built on.

| Band | Meaning |
|---|---|
| `crop_share_2013_2020` / `_2022_2025` | share of years classed crop or summer crop |
| `summer_crop_share_2013_2020` / `_2022_2025` | share of years with a summer (irrigated) crop |
| `fallow_share_2022_2025` | share of years fallow / low cover |
| `crop_share_change` | after − before (negative = cropped less often, possible abandonment) |

### `water_heat_30m.tif`: water and heat (coarse NASA products, nearest-resampled), 13 bands

| Band | Source, cell size | Meaning |
|---|---|---|
| `modis_et_mm_year_before` / `_after`, `modis_et_change` | MOD16A2GF, 500 m | actual evapotranspiration, mm/year |
| `modis_pet_mm_year_2016_2025` | MOD16A2GF, 500 m | potential ET, mm/year |
| `modis_et_pet_ratio_after` | | ET / PET after the fire (0.3 = water-limited) |
| `modis_lst_day_summer_c_before` / `_after`, `_change` | MOD11A2, 1 km | daytime land surface temperature Jun–Aug, °C |
| `modis_lst_night_summer_c_after` | MOD11A2, 1 km | night-time LST Jun–Aug, °C |
| `ecostress_et_mm_day_2022_2025` | ECOSTRESS L3T JET, 70 m | dry-season (May–Sep) daily ET, mm/day |
| `imerg_rain_mm_year_2001_2024` | GPM IMERG Final, 0.1° | mean annual rain, mm |
| `imerg_oct_dec_share` | | share of the year's rain falling Oct–Dec |
| `imerg_days_ge30mm_per_year` | | days with ≥ 30 mm (erosive storms) |

Other layers already on the same grid, one folder up: `terrain_30m.tif` (elevation, slope, upslope cells, RUSLE LS,
upslope burned share), `soil_30m.tif` (SoilGrids texture, SOC, pH, N, AWC, RUSLE K), `landsat_field_map_30m.tif`
(land use 2013–2020 and 1985–1995, burn class 2021), `landsat_dnbr_2021_30m.tif`, `modis_mcd64a1_2021_burndate.tif`.

## CSVs

### `study_points.csv`: all layers at sample points (27,075 rows × 58 cols)
- `sample = field`: **every** field pixel (land use 2013–2020 or 1985–1995 = rainfed or irrigated field), 24,114
  pixels. The old 1985–1995 fields are included so abandoned fields can be studied.
- `sample = grid_300m`: one pixel every 300 m over all land (woods, grazing, …) for comparison.
- Columns: `row`, `col` (pixel in the grids), `x_utm34n`, `y_utm34n`, `lon`, `lat`, then every band of every GeoTIFF
  above. Codes: `land_use_*` 1 rainfed field, 2 irrigated summer field, 3 woody, 4 herbaceous/shrub (grazing),
  5 bare/built; `burn_class_2021` 0 unburned … 4 high (dNBR 0.10 / 0.27 / 0.44 / 0.66); `modis_burn_doy_2021` day of
  year (218 = 6 Aug).
- Opens in Excel; in pandas: `pd.read_csv("study_points.csv")`.

### `area_monthly_2000_2025.csv` (312 months × 25 series) and `area_yearly_2000_2025.csv`
Every time series side by side, one row per month (yearly: totals for `*_mm` and `days_*`, means for the rest).
- Weather (NASA POWER, the ~0.5° cell): `rain_power_mm`, `t2m_mean_c`, `tmax_mean_c`, `tmin_mean_c`,
  `days_tmax_ge_35c`, `rh2m_pct`, `wind2m_ms`, `power_soil_wetness_top` / `_root` (0–1).
- Rain (GPM IMERG, mean of the 0.1° cells in the area): `rain_imerg_mm`, to 2025-09. **Prefer IMERG for rain:**
  POWER is coarse and disagrees in some years (e.g. 2020–2021, see `../imerg_vs_power_october.csv`).
- MODIS area means: `modis_ndvi`, `modis_evi`, `modis_et_mm`, `modis_pet_mm` (8-day composites split into months by
  their daily rate), `modis_lst_day_c`, `modis_lst_night_c`.
- Water storage: `gracda_surface_sm_pct`, `gracda_rootzone_sm_pct`, `gracda_groundwater_pct` (GRACE-DA drought
  percentiles, 0.25° cell, from 2003), `grace_tws_anomaly_cm` (JPL mascon land cell, ~300 km, context only).
- Landsat NDVI, median by group: `landsat_ndvi_fields_burned` / `_unburned`, `landsat_ndvi_woody_burned` /
  `_unburned`, `landsat_ndvi_grazing_burned` (burned = dNBR ≥ 0.27; a month needs ≥ 30 % of the group clear).
- SMAP is left out on purpose (2025 values unreliable, see `exploration/2026-11-11_smap_check`).

## First things that stand out (to check, not conclusions)

- Burned woodland summer NDVI: about 0.71 before, 0.47 in 2022, 0.62 in 2025 (`area_yearly`). Recovering, not
  recovered.
- Burned and unburned *fields* look alike before and after (0.37–0.46). The fire changed the slopes above the fields
  more than the fields themselves, which fits the run-off story in `exploration/2026-11-09_terrain_burn`.
- Over the study area's land (median pixel), ET after vs before is down about 80 mm/year and summer daytime LST is up
  about 3 °C. The maps show the biggest changes over the most severely burned slopes in the north-west.
- Days ≥ 35 °C (POWER): 1–9 a year in 2016–2020, 11–14 in 2021 and 2023–2025.
