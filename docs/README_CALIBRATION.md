# AgriSim AI — uncertainty calibration, phase 1 (March 1)

**This is a forward-in-time validation experiment on Landsat-derived proxy outcomes, not validation against farm records.** Do not replace the already-trained production models or show calibrated results as farm-verified confidence.

## Files included

- `src/agrisim/models/calibrate_satellite_proxies.py` — independent time-split calibration and evaluation command.
- `tests/test_satellite_calibration.py` — five offline regression/smoke tests.

This patch **requires** the existing `src/agrisim/models/train_satellite_proxies.py` from the previous ML training patch (used as a shared feature-policy, target, model and Parquet-validation module), plus training tables and JSON dictionaries already committed under `data/processed/ml/`.

## Install in PowerShell

```powershell
cd D:\AgriSim\agri_sim
Expand-Archive -Path "$env:USERPROFILE\Downloads\AgriSim_Uncertainty_Calibration_Patch.zip" -DestinationPath . -Force
uv sync --extra ml
uv run --extra ml pytest -q tests/test_satellite_calibration.py
uv run --extra ml python -m agrisim.models.calibrate_satellite_proxies --date 0301
```

Then optionally:

```powershell
uv run --extra ml python -m agrisim.models.calibrate_satellite_proxies --date 0401
```

For a rapid *code-only smoke check*, optionally set `--estimators 15`. **Do not report results from a 15-tree smoke test as the final evaluation.**

## Design: NO temporal calibration leakage

Default season partitions:

- **2002–2013:** learn fresh XGBoost base models (point NDVI, lower/upper NDVI quantiles, crop probability).
- **2014–2017:** fit isotonic regression to *out-of-training* crop probabilities and fit the conformal interval correction to *out-of-training* quantile forecasts.
- **2018–2026:** untouched evaluation; calculate metrics globally and by individual season. No decisions or fitting should use these years.

The script reads the decision-date feature list from the companion JSON, reuses the original training script's approved feature policy, excludes `rain_*`, `reg_*`, `sow_*`, `modis_*`, IDs, coordinates and targets, drops all-null features in the early training period, and retains legitimate `NaN`s.

Existing production models (`.../0301/vigour_xgb.json`, `.../0301/crop_xgb.json`) are trained through 2026. **Do not fit calibration on any 2018–2026 predictions from those models and call it holdout accuracy.** This experiment trains new base models only through 2013, so its point scores will differ from the existing train-through-2017 benchmark.

### Calibration definitions

**Crop probability:** `sklearn.isotonic.IsotonicRegression(y_min=0,y_max=1,out_of_bounds='clip')` fitted to predictions on 2014–2017; inspect raw versus calibrated Brier scores and AUC across 2018–2026. Calibration can make Brier score worse in novel seasons.

**Vigour NDVI:** separate XGBoost quantile models (`reg:quantileerror`, `quantile_alpha=0.1/0.9`), then a conservative **season-aware CQR offset**: compute the 80th empirical percentile of conformity residuals within each calibration season and take the maximum of these per-season cutoffs. Bound crossings are corrected. Compare interval coverage and average width globally and for each individual evaluation season. Target is 80% *empirical row coverage*, not a statistical guarantee for future seasons; adjacent pixels are correlated and seasons may shift.

## Output files

`artifacts/satellite_proxy_models/calibration_experiments/0301/`

- `calibration_manifest.json`: feature list, season split, aggregate raw/calibrated evaluation metrics, caveats, per-season CQR offsets.
- `calibration_by_season.csv`: 2018–2026 coverage/width and raw/calibrated crop Brier/AUC.
- `evaluation_predictions.csv.gz`: record-level evaluation predictions for diagnostic charts and reliability plots (no live deployment use).
- `crop_isotonic_calibrator.joblib`: isotonic fit against the *early* base classifier.
- `crop_base_calibration_split.json`: early base crop model.
- `vigour_point_calibration_split.json`: early base point model.
- `vigour_q10_calibration_split.json`, `vigour_q90_calibration_split.json`: early base quantile models.

### What to share next

```powershell
cd D:\AgriSim\agri_sim
Get-Content artifacts\satellite_proxy_models\calibration_experiments\0301\calibration_manifest.json
Import-Csv artifacts\satellite_proxy_models\calibration_experiments\0301\calibration_by_season.csv | Format-Table -AutoSize
```

Upload `calibration_manifest.json` and `calibration_by_season.csv` so we can check whether the 80% interval target holds for each held-out season, how wide it is, and whether isotonic calibration genuinely improves the 2026 Brier score.

## Next stage

After this calibration audit, prepare *out-of-season rolling-origin calibration* for a final model trained through 2026. That is how to enable calibrated live inference without fitting on an evaluation set or misapplying calibrators to differently trained production models. We should also audit historical crop-label hindsight and post-fire feature availability before finalizing deployment.
