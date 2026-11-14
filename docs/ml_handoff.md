# ML engine handoff: what to feed the model (2026-11-14, night)

The data is ready. You don't need the 133 MB local NDVI cube or any download. Details and test results are in
[ml_training_data.md](ml_training_data.md); this page is the short version.

## 1. The files (in git, `data/processed/ml/`, Evia)

One row = one rainfed field pixel (30 m) × one season (Oct Y-1 … Sep Y). 4,911 pixels, seasons 2002–2026
(about 122 k rows). Each `.parquet` has a `.json` next to it listing `features`, targets, group columns and ID
columns. **Read the feature list from the JSON**; don't hard-code it.

| Train on | Predict with | Decision date | Use it for |
|---|---|---|---|
| `training_table_1114.parquet` | `predict_2027_1114.parquet` | 14 Nov (today) | the live demo now; expect baseline-level skill |
| `training_table_v1.parquet` | — | 1 Dec | pre-season reference |
| `training_table_0201.parquet` | (build on 1 Feb) | 1 Feb | first in-season model |
| `training_table_0301.parquet` | (build on 1 Mar) | 1 Mar | **main model** |
| `training_table_0401.parquet` | (build on 1 Apr) | 1 Apr | late in-season model |

**Train and predict with the same decision date.** The columns differ by date (e.g. `ndvi_prior_nov` exists
only from 1 Dec). `predict_2027_1114` has exactly the features of `training_table_1114`.

## 2. Targets

| Column | Task | Meaning |
|---|---|---|
| `target_spring_peak_ndvi` | regression | spring (Mar–May) peak NDVI = crop vigour |
| `target_crop` | binary | 1 crop, 0 fallow or low cover |
| `target_class` | 3-class | 1 crop, 2 fallow / low, 3 summer crop |

These are satellite stand-ins, not farm records. Say so in the app.

## 3. Features: use / drop

- **Use (recommended model):** `hist_*`, `ndvi_prior_*`, `soil_*`, `terrain_*`, `burn_*`, `post_fire`.
- **Drop `rain_*`, `reg_*`, `sow_*` from the model.** Leave-one-season-out on the 1 Mar table:

  | Features | Vigour RMSE | Crop AUC |
  |---|---|---|
  | Without weather | 0.110 | 0.821 |
  | With weather | 0.112 | 0.819 |
  | Baseline | 0.132 | — |

  - Without weather is better in 16 of 25 seasons.
  - In the unusually wet 2026 season it is much better: 0.099 vs 0.113 RMSE, 0.80 vs 0.77 AUC.
  - The weather is regional (one value per season) and shifts when the rain source changes.
  - Weather still reaches the farmer through the rule-based risk and sowing engines.
- **Drop:**
  - `modis_*`: they add no skill, and the files end Dec 2025, so they are empty for the live season.
  - The provenance flags `rain_includes_imerg_late` and `reg_rain_source_is_imerg`: keep them for display
    only.
- **Never use as features:**
  - `season`, `block_id`, `pixel_id`, `row`, `col`, `x_utm`, `y_utm`, `lon`, `lat`, `decision_date`,
    `land_use_2013_2020`.
  - Any `target_*`.
- NaN means missing. XGBoost handles it, so don't fill with 0.

## 4. Validation (what we found)

- **Split by season:** leave one season out, plus forward (train ≤ 2017, test 2018+). Random-row and
  spatial-block splits leak: neighbouring pixels are near-copies, and the regional features identify the year.
- **Always report against the baselines:**
  - Vigour: the pixel's 5-year mean, `hist_peak_mean_5y` (RMSE 0.134).
  - Crop: the pixel's 5-year crop share, `hist_crop_share_5y` (AUC 0.72).
- **Results on unseen seasons:**

  | Decision date | Vigour RMSE | Crop AUC |
  |---|---|---|
  | Before 1 Feb | no skill | no skill |
  | 1 Feb | 0.124 | 0.75 |
  | 1 Mar | 0.112 | 0.80 |
  | 1 Apr | 0.101 | 0.855 |

  All of the skill comes from the winter `ndvi_prior_*`. Weather adds nothing. **Frame it as in-season
  monitoring**, not a pre-season forecast.
- **Uncertainty:**
  - Quantile XGBoost (q10/q90) with a season-grouped conformal correction gives honest 80 % ranges.
  - Isotonic calibration, fitted on the other seasons, gives honest crop probabilities.
  - The method is in [ml_training_data.md](ml_training_data.md#uncertainty-honest-confidence-1-mar-table-unseen-seasons).
- SHAP per field (`pred_contribs=True`) gives the app its "why".

## 5. Known issues (read before trusting season 2026 / the live table)

- **IMERG Late Run rain is corrected to the Final level (since commit after 003f4ca).** Final ends 2025-09-30.
  After that, rain comes from IMERG Late, which is not gauge-adjusted.
  - **The bias drifts.** On the same days over Evia, Late/Final was about 1.0 in 2019–2022, but 1.2–1.5 in
    2023–2025.
  - **The correction:** Late days are multiplied by 0.73, from the last 3 years
    (`data/processed/imerg_late_to_final.csv`, `data_prep/imerg_late_calibration.py`).
  - **What changed:** only season 2026 and the live table. Seasons 2002–2025 are identical.
  - **Season 2026 is still out of range:** 619 mm of rain from 1 Sep to 1 Mar, against at most ~460 mm in
    2002–2025. Its rain features are out of range for the model.
- **Labels can change a little when a year is added.** Adding 2026 flipped ~1 % of the old crop/fallow labels.
  Spring peaks did not change.
- **Some seasons are surprises the features can't see** (2008, 2023). Interval coverage drops there, so show it.

## 6. Rebuilding

```powershell
python -m agrisim.pipelines.build_training_table --as-of 03-01 --out data/processed/ml/training_table_0301.parquet
python -m agrisim.pipelines.build_training_table --predict-season 2027 --as-of 03-01   # on/after 1 Mar 2027
```

Rebuilding needs the local Landsat cube and the raw IMERG caches. Ask George, or use the committed tables.
**Another area:** `python -m agrisim.pipelines.prepare_area --name <area> --bbox W E S N` builds everything,
including these tables ([area_pipeline.md](area_pipeline.md)).

XGBoost is in the `ml` extra: `pip install -e .[ml]`.
