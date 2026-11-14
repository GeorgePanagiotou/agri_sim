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

## Other areas (next step)

The script reads the 30 m grids in `data/processed/` (field map, field years, soil, terrain, burn) and the IMERG
cells. For a user-selected area, the `data_prep/` chain must first build those grids for the new bounding box. That
is tomorrow's "select an area" work.
