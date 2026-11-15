# AgriSim AI — Decision Engine milestone 1 (B + D → E)

**Architecture-first refactor.** The user's architecture image (Section 4: A vegetation time-series, B sowing, C crop rotation, D risk, E decision fusion) is the specification. Older `fusion.py` / `recommendations.py` interfaces are deliberately superseded rather than retained at the expense of correctness.

## What is implemented

| Architecture component | State after this patch |
| --- | --- |
| A — Time-Series Analysis | **Not yet integrated into fusion**. Existing vegetation/ML models remain separate and unchanged. |
| B — Sowing Window Model | **Regional heuristic v1**; live source-based and historical crop-week screening, with future-leakage fix for the SMAP reference median. |
| C — Crop Rotation Model | **Not yet integrated**. Existing candidate ranking/water simulation left alone. |
| D — Risk Assessment | **Regional heuristic v1**; existing five-hazard engine used as source of truth. |
| E — Decision Fusion | **Partial B+D implementation**; joins each candidate crop week to the region's same-date risk record and outputs explainable, strictly qualified field-check actions. |
| Application / UI | Not modified. It remains a synthetic demo until later integration. |

There is no farm-validated sowing success model, risk forecast, crop yield estimate or irrigation recommendation in this patch. The partial E engine never assigns a success probability or asserts a parcel boundary.

## Changes

- `src/agrisim/decision_engine/sowing_window.py`: replaces hindsight-contaminated constant SMAP median with **past-only expanding Sep–Jun median**, shifted one day. Requires at least 14 earlier valid days (configurable through `moisture.smap_min_baseline_days` if needed). Before SMAP starts, threshold is missing and rainfall-only fallback is explicit. Tracks `smap_baseline_days` and `smap_threshold_status`, and does not print a missing median as if known. Corrects `evidence_mode` to identify POWER versus IMERG rainfall.
- `src/agrisim/decision_engine/fusion.py`: **new canonical E contract**. Replaces older join on `field_id`+`candidate_week_start` and eliminates misleading rotation cross-join. Risk is unique per date and regional area, whereas sowing is crop-by-week. Joins by exact start date, validates area provenance (`evia_pilot`) and regional support, preserves missing risk/unknown hazards, and outputs decisions plus explanations.
- `src/agrisim/decision_engine/pipeline.py`: new CLI and Python API. Can reuse generated CSV outputs or recompute B/D from the *same* daily POWER/IMERG/SMAP source table. For `--as-of`, observation rows after the cutoff are discarded before features are computed.
- `src/agrisim/decision_engine/recommendations.py`: old cross-join entry point replaced with safe B+D wrapper. Passing rotations raises `NotImplementedError` until module C has been properly integrated.
- `tests/test_decision_engine_bd.py`: new offline checks for precise temporal join, no farm inference, missing hazards/risks, 2001-vs-2020 source coverage, history look-ahead, and synthetic end-to-end run.

### Important past-data caveats

1. **SMAP is not an early historical observation.** Your 2001 `sowing_weeks.csv` contained `smap_moist_threshold=0.280` and `smap_baseline_days=1890`: a threshold computed using future observations. With the patch those early rows have `smap_moist_threshold=NaN` and zero previous SMAP days. Only genuinely earlier observations enter future-date medians. The expanding median is a *short, changing heuristic*, not a scientific climatology; 14 days is a technical data sufficiency minimum, not an agronomic guarantee.
2. **Risk climatology pre-2021 is retrospective.** The risk engine uses fixed POWER 1991–2020 and IMERG 2001–2020 reference years. For weeks up to 2020 these reference periods include future years relative to the week. Fused output records `risk_reference_temporal_status=retrospective_climatology_...` rather than claiming faithful point-in-time reproduction. For 2021+ the fixed climatological periods precede the year.
3. **Risk CSV may not cover all sowing CSV years.** Your sample risk table begins 2020-09-01, while sowing table begins 2001. The fusion joins dates **exactly** and preserves earlier weeks with `risk_evidence_status=unavailable` — never substitutes `none` or the closest future risk row.
4. **Data publication lag is separate from acquisition date.** The source CSVs don't give per-row publication/availability timestamps for all datasets, so strict historical vintage replay is not yet demonstrated. SMAP L4 may be published days after acquisition. Avoid claiming real-time as-of validity beyond the checks implemented here.
5. **Regional, not field-level:** IMERG (~10 km), POWER (~50 km), SMAP (~9 km). The `evia_pilot` name denotes a provisional area reference point, not a measured field. Current B/D upstream loaders and reference crop rules are Evia-specific; this patch refuses to relabel them as another study area.

## Install (PowerShell)

Work in your existing repository:

```powershell
cd D:\AgriSim\agri_sim

# Optional: snapshot the 3 files being replaced.
Copy-Item src\agrisim\decision_engine\sowing_window.py src\agrisim\decision_engine\sowing_window.before_bd.py
Copy-Item src\agrisim\decision_engine\fusion.py src\agrisim\decision_engine\fusion.before_bd.py
Copy-Item src\agrisim\decision_engine\recommendations.py src\agrisim\decision_engine\recommendations.before_bd.py

Expand-Archive -Path "$env:USERPROFILE\Downloads\AgriSim_Decision_Engine_BDE_Patch.zip" -DestinationPath . -Force

uv run --extra ml pytest -q tests/test_decision_engine_bd.py tests/test_sowing_window.py tests/test_environmental_risk.py
```

The ZIP intentionally doesn't bundle your historical data, configs, model weights, or Streamlit app. It uses the real upstream `risk_rules.yaml`, `sowing_rules.yaml`, and `sowing_windows.csv` already in your repo.

## Run using existing B and D outputs (no data download)

Recommended **first smoke test**:

```powershell
uv run --extra ml python -m agrisim.decision_engine.pipeline `
    --sowing-csv outputs/sowing_weeks.csv `
    --risk-csv outputs/risk_daily.csv `
    --crop winter_wheat `
    --season 2025-2026 `
    --output outputs/decision_engine_bd_wheat_2025.csv
```

This produces both a CSV and a same-basename `.json` report. If risk and sowing outputs differ in their date coverage, the missing matches remain explicitly missing. Regenerate the sowing CSV using the patched engine to fix its old hindsight-derived SMAP baseline:

```powershell
uv run --extra ml python -m agrisim.decision_engine.sowing_window
```

**IMPORTANT:** The old `outputs/sowing_weeks.csv` already on disk still contains the previous future-based SMAP median until regenerated. The patch does not silently rewrite it.

## Run from the source datasets (recompute B, D, E)

```powershell
uv run --extra ml python -m agrisim.decision_engine.pipeline `
    --crop winter_wheat `
    --season 2026-2027 `
    --as-of 2026-11-15 `
    --output outputs/decision_engine_bd_wheat_2026.csv
```

The existing NASA/ESA caches must be present for `er.load_inputs()` to work; the code does not download them. The `--as-of` cutoff prevents future rows from contributing to current-day input windows. To use this for a different area, the upstream B and D pipelines must be properly parameterized and independently validated rather than merely changing a label.

## Output schema highlights

One row per `(area_id, crop_id, season, week_start)`:

- `sowing_verdict`, `sowing_verdict_long_record`, `sowing_explanation`
- `risk_overall_level`, `risk_overall_label`, `risk_hazards_flagged`, `risk_hazards_unknown`, `risk_evidence_status`
- `risk_drought_level`, `risk_heat_level`, `risk_heavy_rain_level`, etc., including source explanations where available
- `decision_priority` (e.g. `field_check_required`, `regional_risk_warning`, `candidate_for_field_check`, `field_check_with_data_gaps`, `insufficient_evidence`)
- `recommended_action`, `decision_explanation`, `spatial_support`, `risk_reference_temporal_status`
- `component_a_vegetation_status=not_integrated`, `component_c_rotation_status=not_integrated`, `component_e_fusion_status=partial_B_D_only`
- `is_forecast=False`; `probability_of_establishment` is missing, not fabricated.

The companion JSON records row counts, missing risk coverage, priority distribution, and what remains unfinished.

## Validation and next steps

Offline: **24 tests passed** in the isolated test harness — the previously uploaded sowing/risk test suites plus 8 new B/D/E tests, including a synthetic end-to-end run. The harness used a minimal stand-in for the unprovided `agrisim.area` file only to resolve imports; your actual `agrisim.area` is left unchanged. **No real Evia data were reprocessed in this runtime.** Please rerun tests and the real source pipeline in your own repo.

Next milestones, aligned to the *image* rather than old file organization:

1. **C Crop Rotation:** actual crop data/GAEZ, explicit scenario generation, water-accounting and agronomic rules, then connect it to E. Farm-level outcomes remain absent.
2. **A Time-Series + ML:** attach observed phenology and calibrated staging XGBoost inference as distinct evidence inputs, not as false sowing success or rotation probabilities.
3. **Complete E:** structured cross-component evidence synthesis, time/spatial provenance and calibrated uncertainty where available.
4. **Streamlit:** consume E's output contract instead of the synthetic `demo_data.py` decisions.

No data/model files were overwritten by the patch itself. Its changes are limited to code and tests.
