# AgriSim AI — rolling-origin uncertainty evaluation (Phase 2)

This patch extends the original `calibrate_satellite_proxies.py` script **without removing the fixed-split experiment** and adds `calibrate_satellite_rolling.py` and tests. The underlying `train_satellite_proxies.py` from the earlier ML patch **must already be present**. Your existing `*_xgb.json` production models are **never overwritten**.

## Install (PowerShell)

```powershell
cd D:\AgriSim\agri_sim
Copy-Item src\agrisim\models\calibrate_satellite_proxies.py src\agrisim\models\calibrate_satellite_proxies.backup.py -Force
Expand-Archive -Path "$env:USERPROFILE\Downloads\AgriSim_Rolling_Calibration_Update.zip" -DestinationPath . -Force
uv sync --extra ml
uv run --extra ml pytest -q tests/test_satellite_rolling_calibration.py tests/test_satellite_calibration.py
```

If `tests/test_satellite_calibration.py` was not installed from the previous patch, simply run `pytest -q tests/test_satellite_rolling_calibration.py`.

## Run on your Evia March and April Parquet tables

**Quick check for just the hardest/latest year, 2026** (only to verify the executable works; **not** a complete evaluation):

```powershell
uv run --extra ml python -m agrisim.models.calibrate_satellite_proxies --rolling --date 0301 --start-season 2026 --end-season 2026 --estimators 50
```

**Full rolling-origin backtest (recommended):**

```powershell
uv run --extra ml python -m agrisim.models.calibrate_satellite_proxies --rolling --date 0301
uv run --extra ml python -m agrisim.models.calibrate_satellite_proxies --rolling --date 0401
```

Or invoke the new module directly:

```powershell
uv run --extra ml python -m agrisim.models.calibrate_satellite_rolling --date 0301
```

Default: **2018–2026** evaluations, 3 previous seasons for calibration, XGBoost 350 estimators, CPU. `--estimators 100` runs a faster benchmark with smaller models. `--device cuda` is optional if your XGBoost GPU installation supports it. `--calibration-seasons 4` uses four prior years instead of three. Do **not** compare runs with different estimator counts as if the models were identical.

The script **retrains fresh models each fold**; it does NOT load or modify the 15 `artifacts/satellite_proxy_models/{date}/*_xgb.json` production models.

## How the temporal split works

For a test season `T`, only outcomes from years before `T` are used:

| Test season | Base model training | Probability and NDVI calibration | Final evaluation |
|---|---|---|---|
| 2018 | 2002–2014 | 2015–2017 | 2018 |
| 2019 | 2002–2015 | 2016–2018 | 2019 |
| ... | ... | ... | ... |
| 2026 | 2002–2022 | 2023–2025 | 2026 |

This is a **prequential/rolling-origin experiment**: evaluation data from 2018 may become available for the **2019** calibration fold. It never influences a 2018 prediction. This differs from a permanently untouched 2018–2026 test set, but accurately simulates annual updating with past observed seasons. **Do not tune/select a method using these same evaluation seasons and subsequently present that method's reported numbers as an unbiased final score.**

XGBoost input features follow the companion table JSON and exclude `rain_*`, `reg_*`, `sow_*`, `modis_*`, target columns, year and IDs. Fire severity fields are masked before the 2021 fire; entirely missing training columns are dropped per fold. Dates must match table metadata. Missing values remain `NaN`.

### Calibration compared

- **Crop presence proxy:** raw XGBoost probabilities, Platt/sigmoid calibration (logistic regression on logit(p)), isotonic regression. Both calibrators fit only the immediately preceding three *calibration* seasons, weighted so each whole season has equal total influence. Score Brier, ROC-AUC and reliability curves. No method is automatically declared a winner by peeking at evaluation outcomes.
- **Spring peak NDVI proxy:** 10th/90th-quantile XGBoost regressors, plus season-aware conformal correction. The correction is the maximum (nonnegative) of the target-coverage conformity quantile computed separately for each calibration season. Score empirical interval coverage, average width and point RMSE. Coverage is **not guaranteed for each future season** under climate or label shift.

The target `target_crop` is 1 for satellite-defined crop and 0 for **fallow OR summer crop**. It is **not** a verified farm crop-presence label. Spring peak NDVI is derived from satellite observations; the April decision date includes part of March–May in its inputs (in-season monitoring).

## Where the results go

Each date is saved to:

```
artifacts/satellite_proxy_models/calibration_experiments/rolling/0301/
  rolling_manifest.json                    # exact folds, features, metrics, limitations
  rolling_by_season.csv                    # annual point errors, Brier/AUC, raw/CQR coverage and widths
  rolling_evaluation_predictions.csv.gz    # row-level out-of-season proxy labels and predictions
  reliability_bins.csv                     # aggregate calibration bins for raw/sigmoid/isotonic
  reliability_bins_by_season.csv           # calibration bins for each season
  crop_reliability_diagram.svg             # reliability curves, diagonal = perfect calibration
  ndvi_coverage_by_season.svg              # coverage across seasons vs 80% target
```

The same structure is used for `0401/`. SVG charts open directly in VS Code or a browser. No plotting dependency is required; the code produces SVG itself.

Optional `--save-fold-models` writes each fold's **experimental** crop/point/quantile XGBoost JSON and corresponding calibrated fit. The defaults avoid generating many large model files.

## How to interpret the outcome

1. Compare March vs April `rolling_manifest.json > aggregate_metrics` and **macro-season averages**, as well as `rolling_by_season.csv` for 2023/2026.
2. A probability calibrator is worth considering only if it improves Brier score **without breaking seasonal stability**. Inspect `crop_reliability_diagram.svg` and count of seasons improved. ROC-AUC should remain close, though isotonic can cause ties.
3. Prefer the narrowest NDVI intervals that achieve satisfactory coverage across seasons, not only high pooled coverage.
4. **No experiment calibrator is a drop-in replacement for the full-data models trained through 2026**. A production handoff needs a separate refit/calibration strategy that doesn't reuse in-sample predictions.
5. Limitations remain: pixel spatial dependence, satellite proxy targets, historic class thresholds using later years, modern soil layers for old seasons, and distribution shift.

After running both dates, share `rolling_manifest.json` and `rolling_by_season.csv` for `0301` and `0401`, plus a screenshot or the generated reliability SVGs. That is enough to choose the next calibration design.
