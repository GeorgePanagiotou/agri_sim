# ML training data v1 (2026-11-14)

Data prepared for the ML engine (Stylianos). One row = **one rainfed field pixel (30 m) × one agricultural season**
(Oct Y-1 … Sep Y), 2002–2025.

```powershell
python -m agrisim.pipelines.build_training_table                 # decision date 1 Dec (default)
python -m agrisim.pipelines.build_training_table --as-of 03-01 --out data/processed/ml/training_table_mar.parquet
```

Output: `data/processed/ml/training_table_v1.parquet` with a `.json` data dictionary (feature list, targets, group
columns, rules). 117,272 rows × 64 columns: 50 features, 4,911 pixels, 95 spatial blocks, 24 seasons.

## Targets: satellite stand-ins, not farm outcomes

No farm records exist (sowing dates, emergence, yields). The targets come from our Landsat field history
(`landsat_field_years.nc`, built from the monthly harmonised Landsat NDVI cube):

| Target | Meaning |
|---|---|
| `target_spring_peak_ndvi` | highest NDVI in Mar–May of the season: crop vigour proxy (regression) |
| `target_class` | 1 crop, 2 fallow / low cover, 3 summer crop, from the yearly NDVI curve |
| `target_crop` | 1 if crop, else 0 (classification) |

Say this in the app and the pitch: *"trained on satellite-observed field outcomes; not validated against farm
records"*.

## Features (known at the decision date, default 1 Dec of Y-1)

| Group | Columns | Varies by |
|---|---|---|
| Rotation history | `hist_class_lag1..3`, `hist_peak_lag1..2`, `hist_crop_share_5y`, `hist_peak_mean_5y`, `hist_years_since_fallow` | pixel × season |
| Autumn NDVI | `ndvi_prior_sep`, `ndvi_prior_oct`, `ndvi_prior_nov` (months completed before the date) | pixel × season |
| MODIS, nearest cell (optional) | `modis_lst_day_prev_summer_c`, `modis_lst_day_since_sep1_c`, `modis_lst_night_since_sep1_c` (MOD11A2, 1 km); `modis_et_prev_summer_mm_day`, `modis_et_since_sep1_mm_day`, `modis_et_pet_ratio_since_sep1` (MOD16A2GF, 500 m). An 8-day composite counts only once it ended before the date | cell × season (~170 values per season in Evia) |
| Rain (IMERG 0.1° cell) | `rain_prior_30/60/90d_mm`, `rain_since_sep1_mm`, `rain_prev_summer_jja_mm` | cell × season |
| Regional | `reg_rain_90d_percentile`, `reg_dry_spell_days`, `reg_drought_level`, `reg_heavy_rain_level`, `reg_temp_mean_since_sep1_c`, `reg_gdd0_since_sep1`, `reg_frost_days_since_sep1`, `reg_hot_days_prev_summer_ge35c` | season |
| Sowing window | `sow_{winter_wheat,barley}_weeks_assessed / _weeks_check_worthy / _days_to_first_check_worthy` | season |
| Static | `soil_*` (SoilGrids: texture, SOC, pH, N, AWC, RUSLE K), `terrain_*` (elevation, slope, upslope, LS), `burn_dnbr_2021`, `burn_class_2021`, `post_fire` | pixel |

Group / ID columns, **not features**: `season`, `block_id` (50 × 50 px = 1.5 km spatial blocks), `pixel_id`, `row`,
`col`, coordinates, `decision_date`.

## Rules for training

- **No future data:** every feature uses data before `decision_date`. `hist_*` uses earlier seasons only. Never use
  `target_*` or NDVI after the decision date as a feature.
- **Cross-validation:**
  - Leave one season out (new years).
  - GroupKFold on `block_id` (new places).
  - A forward split (train ≤ 2017, test ≥ 2018).
  - Random row splits leak, because neighbouring pixels are near-copies.
- **Always compare with baselines:** "same as last season" (`hist_peak_lag1`, `hist_class_lag1`) and the pixel's
  5-year mean.
- **Weather is regional.** Within one season every field shares the regional and sowing values, and the rain values
  differ only between 0.1° cells. The weather signal is therefore mostly a year effect.
- **Missing = NaN**, never 0. XGBoost handles NaN.
- Autumn-NDVI columns need the local monthly cube (`landsat_ndvi_monthly_30m.nc`, 150 MB, not in git). Without it,
  the table is built without them.

## First XGBoost results: which decision date (2026-11-14)

The model is scored on unseen seasons (leave-one-season-out). The baseline is the pixel's own 5-year mean, which
scores RMSE 0.134 for vigour and AUC 0.72 for crop.

| Decision date | 1 Oct – 1 Jan | 1 Feb | 1 Mar | 1 Apr |
|---|---|---|---|---|
| Spring vigour RMSE | 0.134–0.136 (no skill) | 0.124 | 0.112 | **0.101** |
| Crop vs fallow AUC | 0.69–0.71 (no skill) | 0.75 | 0.80 | **0.855** |

- **All the skill comes from the winter NDVI.** Without the `ndvi_*` columns, every date stays at the baseline.
  Weather, sowing-window and MODIS features add nothing on unseen seasons. They are regional, and spring depends on
  rain after the decision date.
- **So the ML engine is an in-season monitor, not a pre-season forecast.** Train one model per decision date
  (`--as-of 02-01`, `03-01`, `04-01`) and show "which fields look on track / likely fallow", updated monthly from
  February.
- **Use leave-one-season-out and a forward split.** Spatial-block CV looks better but misleads: the regional
  features identify the season.

## Prediction table (the season in progress)

```powershell
python -m agrisim.pipelines.build_training_table --predict-season 2027 --as-of 11-14
```

This writes `data/processed/ml/predict_2027_1114.parquet`: one row per field pixel with the same feature columns
and empty targets. Season 2027 runs Oct 2026 … Sep 2027. It needs:

- **Last season's class and peak (2026):** the Landsat cube must reach Sep 2026 (`landsat_ndvi_history.py 2026
  2026`, then `landsat_field_map.py`).
- **Recent rain:** IMERG Final ends about 3.5 months back. `data_prep/download_imerg_late.py` fills the gap up to
  yesterday with the IMERG Late Run (`raw/imerg_late/<year>_Q<n>.parquet`). `rain_includes_imerg_late` = 1 marks
  rows whose 90-day window uses Late days. The risk and sowing engines read the Late quarters too, and Final wins
  wherever both exist.

Coordinates are `x_utm`, `y_utm` in the area's UTM CRS (named in the JSON). `post_fire` follows the area's fire
date (Evia: seasons from 2022).

## Other areas

`python -m agrisim.pipelines.prepare_area --name <area> --bbox ...` builds every input and then this table for any
box ([area_pipeline.md](area_pipeline.md)). Without a burn map, `burn_dnbr_2021` is NaN. The MODIS columns appear
only where the MODIS files exist.

## What the record says about rotation (Evia, 2002–2025, rainfed pixels)

- **No measurable fallow benefit.** Spring peak NDVI after a fallow season vs after a crop, within the same pixel
  and season: **−0.012** (SE 0.001). In crop seasons only: −0.004.
- **Fallow persists.** After a fallow season, 43 % stay fallow (21 % after a crop). P(crop) rises with the years
  since the last fallow, from 0.57 (1 year) to 0.94 (≥ 10 years).
- **"Fallow" here is mostly multi-year idle or grazed land, not a managed one-year break.** The rotation engine
  should not assume a yield bonus after fallow without local evidence.
- **The 2021 fire did not reduce cropping.** The crop share per burn class is about the same before and after
  2021, e.g. 70 % → 72 % on unburned fields.
