# AgriSim AI — wildfire-feature ablation + 2027 calibration bundle

**Status:** code tested with synthetic data. Full Evia Parquet training runs must be performed locally with your `uv` environment. No official model validation, no farm outcomes, and no 2027 March/April forecasts yet.

## 1. Install

Copy/extract this package **into your cloned Git project root**, preserving `src/agrisim/models/` and `tests/`. The updated `calibrate_satellite_rolling.py` retains the old CLI and adds an optional `--fixed-features` flag. The new modules do not overwrite the original XGBoost production models.

```powershell
cd D:\AgriSim\agri_sim
Copy-Item src\agrisim\models\calibrate_satellite_rolling.py src\agrisim\models\calibrate_satellite_rolling.backup.py -Force
Expand-Archive -Path "$env:USERPROFILE\Downloads\AgriSim_2027_Calibration_Ablation_Patch.zip" -DestinationPath . -Force
uv sync --extra ml
uv run --extra ml pytest -q tests/test_satellite_rolling_calibration.py tests/test_satellite_2027_bundle.py
```

## 2. Fixed-feature ablation: March/April 2026

This isolates the only rolling evaluation season in which the dynamic-feature training pipeline gained the three 2021-wildfire fields. It reruns **dynamic** and **fixed/no-fire** with the same random seed, estimator count, and seasons. Both variants retain `post_fire`, a valid calendar flag; only `burn_class_2021`, `burn_dnbr_2021`, `terrain_upslope_burned_share` are held out. The fixed feature set excludes these across all seasons.

```powershell
uv run --extra ml python -m agrisim.models.ablate_satellite_fire --date 0301 --start-season 2026 --end-season 2026
uv run --extra ml python -m agrisim.models.ablate_satellite_fire --date 0401 --start-season 2026 --end-season 2026
```

Outputs per date:

```
artifacts/satellite_proxy_models/calibration_experiments/fire_ablation/
  0301/
    ablation_manifest.json
    ablation_by_season.csv
    dynamic_fire/rolling_manifest.json
    dynamic_fire/rolling_by_season.csv
    fixed_no_fire/rolling_manifest.json
    fixed_no_fire/rolling_by_season.csv
  0401/...
```

In `ablation_by_season.csv`, **delta = fixed − dynamic**. For RMSE/Brier, a negative delta means fixed-feature performs better; for ROC-AUC, positive means fixed-feature performs better. For interval coverage, closeness to the nominal 0.80 matters; higher coverage can reflect overly wide intervals.

Optional full fixed-feature rolling audit, if desired:

```powershell
uv run --extra ml python -m agrisim.models.calibrate_satellite_rolling --date 0301 --fixed-features --output-dir artifacts/satellite_proxy_models/calibration_experiments/rolling_fixed
```

The original rolling results are not overwritten by `ablate_satellite_fire`.

## 3. Self-contained 2027 **staging** bundles

Train 2002–2023, calibrate on **2024–2026**. The 2027 season cannot enter the fit or calibration. March uses sigmoid-adjusted binary crop proxy probabilities, April retains raw binary crop proxy probabilities. These were *preselected using the retrospective 2018–2026 rolling results*, which is not prospective confirmation. Both dates produce quantile XGBoost models with season-aware 80%-target conformal NDVI intervals. Both omit 2021 wildfire severity features to keep features fixed.

```powershell
uv run --extra ml python -m agrisim.models.satellite_bundle_2027 --date 0301
uv run --extra ml python -m agrisim.models.satellite_bundle_2027 --date 0401
```

Files:

```
artifacts/satellite_proxy_models/deployment_staging/2027/
  0301/
    bundle_manifest.json
    crop_xgb.json
    vigour_xgb.json
    vigour_q10_xgb.json
    vigour_q90_xgb.json
    crop_sigmoid_calibrator.joblib
    crop_isotonic_reference.joblib
  0401/...
```

These models do **not** modify or calibrate the older models under `artifacts/satellite_proxy_models/0301` or `/0401`, which were fitted on seasons through 2026. The staging bundles intentionally reserve 2024–2026 as untouched base-model calibration seasons. The manifest's calibration-set diagnostics are **not** forward test scores.

### Inference, **only after the matching 2027 as-of date**

After your team builds the matching 2027 feature table and its JSON dictionary (on/after March 1 / April 1, 2027 respectively):

```powershell
uv run --extra ml python -m agrisim.models.satellite_bundle_2027 --date 0301 --skip-train --predict-table data/processed/ml/predict_2027_0301.parquet
uv run --extra ml python -m agrisim.models.satellite_bundle_2027 --date 0401 --skip-train --predict-table data/processed/ml/predict_2027_0401.parquet
```

The inference command checks: matching `as_of`, area, 2027 season, all expected features, and missing outcome targets. **Do not use** the existing `predict_2027_1114.parquet` for March or April: its feature set and decision date are different. Results are saved as `predict_2027.csv.gz` in the matching staging folder.

## 4. Recommended evaluation and disclosure

1. Compare March and April `fire_ablation/{date}/ablation_by_season.csv` (especially 2026) with the same estimator settings.
2. For NDVI intervals, report both coverage and mean width by year; your prior experiments showed undercoverage in 2023 and some other seasons.
3. For crop probability, compare Brier, AUC and reliability curves; sigmoid marginally helped March but *hurt April* in the previous rolling evaluation.
4. Keep the 2027 staging bundle distinct from the evaluated rolling models. After a new season, retrain/recalibrate with a truly prospective test.
5. UI text: “Satellite-derived vegetation proxy; model has **not** been validated against independent farm outcomes. 80% is an historical marginal interval target, not a guarantee for every season.”

All models in this patch predict satellite-derived `target_spring_peak_ndvi` or `target_crop`; they do **not** predict crop yield, actual planting, successful germination, or a suitable sowing date. Those decisions belong to the separate agronomic and environmental rule engines.
