# AgriSim AI — satellite proxy ML training patch

This patch **does not replace** `src/agrisim/models/training.py`. That existing module intentionally trains on independently observed farm outcomes. The new module trains on a *different* set of targets created from satellite NDVI and does not claim verified farm outcomes.

## Status of this delivery

- Source and training-data documentation inspected.
- Five companion JSON metadata dictionaries checked; dates and feature selections agree.
- November 14 training JSON and the 2027 prediction JSON have identical ordered features and matching CRS.
- New model-training code tested end-to-end on **synthetic fixtures** (all three tasks).
- **Real Parquet files were not evaluated or used to fit models in the delivery environment.** The environment does not contain `pyarrow`/`fastparquet`, and installation was unavailable. No real-data scores or trained artifact claims are made.

## Installation in your local Windows repository

Your `agri_sim` architecture branch should already contain all the Parquet files under `data/processed/ml/`.

Unzip into the repository root, preserving paths. This adds:

- `src/agrisim/models/train_satellite_proxies.py`
- `tests/test_train_satellite_proxies.py`
- This README and `METADATA_AUDIT.md`

In PowerShell, from `D:\AgriSim\agri_sim`:

```powershell
uv sync --extra ml
uv run --extra ml pytest -q tests/test_train_satellite_proxies.py
```

### First run: March 1 model

```powershell
uv run --extra ml python -m agrisim.models.train_satellite_proxies --date 0301
```

The script **reads the Parquet and its JSON** from `data/processed/ml/`, checks schema, splits complete seasons (train 2002–2017; test 2018–2026), evaluates historical baselines, then refits production models on all labeled seasons. It saves to `artifacts/satellite_proxy_models/0301/`.

### Other decision dates

```powershell
# February 1 and April 1 separately
uv run --extra ml python -m agrisim.models.train_satellite_proxies --date 0201
uv run --extra ml python -m agrisim.models.train_satellite_proxies --date 0401

# November 14 plus live season 2027 predictions from its matching table
uv run --extra ml python -m agrisim.models.train_satellite_proxies --date 1114 --live-2027

# All five historic decision-date models (no live prediction)
uv run --extra ml python -m agrisim.models.train_satellite_proxies --all-dates

# Optional: leave-one-season-out diagnostic (many model fits; diagnostic, NOT future-only)
uv run --extra ml python -m agrisim.models.train_satellite_proxies --date 0301 --tasks vigour crop --loso
```

If the live table is updated later, regenerate it with its **own** matching decision date. Do not feed `predict_2027_1114` to the March or April models.

### Model output files (per decision date)

- `vigour_xgb.json` — XGBoost spring NDVI peak regression model.
- `crop_xgb.json` — XGBoost class-1-vs-rest classifier, raw **uncalibrated** probabilities.
- `class_xgb.json` — XGBoost three-class crop/fallow/summer classifier.
- `*_forward_metrics.json` — forward holdout metrics and historical-pixel baselines.
- `*_forward_by_season.csv` — metrics for each previously unseen evaluation season.
- `run_manifest.json` — model feature lists, train/holdout seasons, missing-data summary and limitations.
- With `--live-2027`: `*_live_2027.csv.gz` — per-pixel predictions and coordinates for demo mapping.
- With `--loso`: `*_loso_by_season.csv` — season-grouped diagnostic.

The production `.json` models are refitted after evaluation on **all labeled seasons** and have no clean 2027 labels yet. The forward test scores come from separate models fit to training seasons only.

## Data and evaluation safeguards

1. The script selects features **from the paired JSON** (not a manually fixed column list) and keeps only `hist_*`, `ndvi_prior_*`, `soil_*`, `terrain_*`, `burn_*` and `post_fire`.
2. It explicitly discards `rain_*`, `reg_*`, `sow_*`, `modis_*`, targets, coordinates, season and identifier columns. Weather and sowing-rule indicators can still be used *separately in the UI*.
3. `NaN` stays `NaN`; no zero filling. All-null-on-training features are excluded.
4. 2021 burn severity and burned-upslope features are **masked for seasons before 2022** to avoid exposing a future fire to earlier seasons.
5. Models are assessed by **forward seasons**, never randomly split neighboring pixels. The baseline is `hist_peak_mean_5y` for regression, `hist_crop_share_5y` for binary classification and last season's class for multiclass.
6. Binary target `target_crop=1` means class **1**; `target_crop=0` also includes class **3 summer crop**, not just fallow. Call it *class-1 crop vs others*, not universal crop absence detection.
7. These targets are **Landsat-derived satellite proxies**, not farmer-recorded sowing dates, yield, crop establishment, or verified crop types.
8. **Unresolved hindsight issue:** `ml_training_data.md` documents that class pseudo-label thresholds were recomputed over all years when 2026 was added. This may indirectly affect `hist_class_*` and strict historical backtesting. Fixing it requires regenerating labels season-causally from source data. The 2021 burn safeguard does **not** solve this older label issue.
9. XGBoost crop probabilities are **not calibrated** by this v1 patch. Do not represent them as verified confidence. Quantile regression, CQR and groupwise isotonic calibration should be evaluated next with season-disjoint calibration splits.
10. The handoff reports that pre-February seasonal models do not beat the historical baseline. **November 14 live predictions are experimental**, and should not be presented as reliable agronomic recommendations.

## What's next

Once you run the March 1 command locally, share `artifacts/satellite_proxy_models/0301/run_manifest.json` and the three `*_forward_by_season.csv` files. That will let us inspect which seasons fail, review holdout-vs-baseline metrics, and decide whether to tune features or use a different forward evaluation. This code is training infrastructure, not the rule-based sowing or risk engine.
