# AgriSim AI — Implementation Gap Analysis & Development Roadmap

**Date:** 14 November 2026  
**Scope:** Comparison of the *AgriSim AI — Decision Engine: End-to-End Pipeline* architecture diagram with the implementation and validation results reported to date.  
**Status basis:** Reported local project runs and tests; **not** a fresh inspection of the current Windows repository.

## Executive summary

AgriSim AI has made substantial progress in **data acquisition, preprocessing, and environmental feature integration**. The strongest remaining work is in the **Decision Engine** and **Application & Outputs** layers.

The current multisource dataset contains:

| Metric | Current result |
|---|---:|
| Daily records | **1,819** |
| Columns | **56** |
| Growing seasons | **6** |
| Duplicate field/date rows | **0** |
| Multisource pipeline automated tests | **10 passed** |

The prototype is ready for **environmental feature engineering and an interpretable, rule-based risk engine**. It is not yet ready to claim trained sowing-success probabilities or validated crop-rotation predictions because field-level agricultural labels are unavailable.

## 1. Implementation status against the architecture

| Architecture component | Current status | Remaining work |
|---|---|---|
| **1. Data Sources** | Mostly complete | ERA5-Land optional; ECOSTRESS ET extraction, quality verification and integration; historical Sentinel-2 expansion |
| **2. Data Preprocessing** | Mostly implemented | Sensor harmonization, verified field polygons, final quality checks |
| **3. Feature Engineering** | Partially implemented | Higher-level vegetation, soil-water, weather and agronomic indicators |
| **4A. Time-Series Analysis** | Partially implemented | Sentinel-2-only PELT, multisensor sensitivity tests, detection validation |
| **4B. Sowing Window Model** | Not implemented | Agronomic rules, crop-specific thresholds; supervised model once labels exist |
| **4C. Crop Rotation Model** | Not implemented | Rotation constraints, crop-history inputs, ranking/recommendation algorithm |
| **4D. Risk Assessment** | Not implemented | Drought, heat, excess-water and water-stress scoring |
| **4E. Decision Fusion** | Not implemented | Combine recommendations and risk assessments with explanations and uncertainty |
| **5. Application & Outputs** | App scaffold exists | Connect processed data and actual decision outputs to maps, dashboards, recommendations, and alerts |
| **ML Models & Training** | Not trained | Verified agricultural targets, baseline comparisons, training and evaluation |

> **Interpretation:** These statuses are based on reported work and tests, not a code-by-code audit of the user's latest local Git repository.

## 2. Dataset readiness and limitations

The integrated dataset is located at:

```text
data/processed/features/environment_multisource_daily.parquet
```

Other relevant outputs include:

```text
data/processed/features/environment_multisource_coverage.csv
data/processed/features/environment_multisource_gaez_crops.csv
data/processed/features/environment_multisource_manifest.json
```

### Available inputs

- **NASA POWER:** Air temperature, humidity, radiation, wind, precipitation and related weather variables.
- **GPM IMERG:** Daily regional precipitation, with Final and Late Run provenance retained. January–June 2026 rainfall is missing from the current integrated dataset.
- **NASA SMAP:** Surface soil moisture and soil temperature for six growing seasons, with complete daily records.
- **NASA HLS:** NDVI/EVI2 observations for six growing seasons; substantial missingness is expected on a daily calendar.
- **ESA Sentinel-2:** Aligned NDVI/EVI2 observations for 2024–2025 only; other growing seasons are not yet covered.
- **NASA SRTM:** Static elevation, slope and aspect for the provisional study footprint.
- **FAO GAEZ v4:** Historical rainfed, low-input suitability indices for wheat, barley, maize, chickpea and dry pea.
- **NASA ECOSTRESS:** A small initial ET sample has been downloaded, but its units/quality treatment and multisource integration need further validation.
- **ERA5-Land:** Not required for the first decision-engine prototype; its download was blocked by CDS licence-acceptance access.

### Important data constraints

1. **Provisional geography:** `evia_pilot` uses an unverified approximately **90 × 90 m** satellite sampling footprint, not a confirmed agricultural parcel.
2. **Resolution mismatch:** POWER, IMERG, SMAP and GAEZ represent regional or coarse-grid context, not direct measurements of that parcel.
3. **Sparse vegetation:** Satellite NDVI/EVI2 should remain irregular observations. Do **not** impute zeros on missing acquisition dates.
4. **Sensor discrepancy:** HLS and Sentinel-2 showed a same-day NDVI offset in six comparisons. Preserve sensor-specific features and evaluate harmonization before combined change-point analysis.
5. **No field-level ground truth:** Satellite green-up events are retrospective spectral signals, **not verified crop-emergence labels**.
6. **Temporal integrity:** Historical rolling predictors must use only data that would have been available before the assessed decision date; do not treat retrospective observations as forecast information.

## 3. Missing feature engineering

| Category | Already available | Still needed |
|---|---|---|
| **Vegetation** | NDVI, EVI2, HLS/S2 clear fractions | NDVI rate of change, growth-stage indicators, NDWI, vegetation anomalies |
| **Water & Soil** | SMAP moisture and soil temperature, recent moisture means | Soil-moisture anomalies, water-balance features, reference ET₀ |
| **Weather** | Temperature, humidity, precipitation, GDD, prior-rainfall sums | Dry-spell duration, extreme-heat indicators, seasonal anomalies |
| **Terrain** | Elevation, slope, aspect | Optional topographic wetness index (TWI) |
| **Agronomic** | Five crop-specific GAEZ suitability scores | Crop history, rotation rules, sowing requirements, verified crop labels |

**Main gap:** The dataset records environmental measurements, but it does not yet turn those measurements into a crop-dependent assessment such as *too dry*, *too wet*, or *favorable for sowing wheat*.

## 4. Decision Engine work packages

### A. Vegetation time-series analysis — partially implemented

- Retain the existing retrospective HLS PELT analysis and its recorded outputs.
- Implement and evaluate **Sentinel-2-only** PELT on aligned, high-quality NDVI/EVI2 observations.
- Test sensitivity to smoothing windows, observation quality thresholds, and missing-date intervals.
- Compare sensor-specific and harmonized multisensor analyses **without assuming identical NDVI response**.
- Report candidate green-up *intervals*, uncertainty, and possible late-season decline—not exact sowing or emergence dates.
- Seek independent field observations before treating these detections as agricultural labels.

### B. Sowing Window Model — not implemented

**Goal:** Assess candidate sowing dates from soil temperature, soil moisture, rainfall history and crop-specific requirements.

**Recommended v1:** A transparent rule-based eligibility and scoring system with explicit threshold sources and missing-data flags.

**Possible future ML:** XGBoost/LightGBM only once real sowing dates, outcomes and multiple independently sampled fields become available. Retrospective scores must not be presented as forecast probabilities.

### C. Crop Rotation Model — not implemented

**Available input:** GAEZ indices for five crops.

**Still required:**

- Previous crop and crop-family history.
- Rotation constraints and disease/pest considerations.
- Water requirements and seasonality.
- Soil health and nitrogen considerations.
- Multi-criteria ranking with transparent weights and explanations.

**Critical caution:** Ranking solely by GAEZ index is a crop-suitability comparison, **not** a valid crop-rotation recommendation.

### D. Environmental Risk Assessment — not implemented

Build interpretable indicators for:

- Moisture deficit and drought exposure.
- Extreme heat and temperature stress.
- Heavy precipitation/excess-water conditions.
- Combined water-stress context from POWER, IMERG and SMAP.

Begin with historically calibrated, transparent **heuristic risk indicators**. Do not claim probabilistic risk estimates before appropriate labeled outcomes and calibration exist.

### E. Decision Fusion & Recommendation — not implemented

Combine:

1. Sowing-condition scores.
2. Crop suitability context.
3. Rotation constraints.
4. Environmental risk indicators.
5. Data quality, provenance and uncertainty.

Each recommendation should include an explanation and clear disclosure of missing or coarse-resolution inputs.

## 5. Application & Outputs — remaining integration

The existing application scaffold should connect to real pipeline outputs and provide:

- Interactive study-area map with an explicit **unverified/provisional geometry** flag.
- Time-series visualizations for weather, soil moisture and sensor-specific vegetation indices.
- Candidate sowing windows with evidence and uncertainty.
- Ranked crop options, with rotation constraints distinguished from GAEZ scores.
- Drought, heat and moisture-related warnings.
- Historical comparison, feature coverage and downloadable reports.

Avoid suggesting a field-specific recommendation if the only available context is coarse regional data and no verified field history.

## 6. Example future assessment

This is a **mock interface example**; only the GAEZ value is taken from the reported dataset.

| Element | Example result |
|---|---|
| Crop | Wheat |
| Historical GAEZ suitability index | **8,070 / 10,000** |
| Soil-moisture assessment | Pending crop-specific rules |
| Sowing window | To be calculated |
| Water-stress risk | To be calculated |
| Suggested next crop | Requires previous-crop/rotation history |
| Confidence | Requires empirical validation |

The GAEZ score is a modeled regional index, **not** yield, a probability of crop success or a validated farm-level recommendation.

## 7. Recommended implementation roadmap

### Phase 1 — Environmental feature engineering

- Add soil-moisture anomalies, rainfall deficit, dry-spell duration, GDD/heat indicators and ET₀ where derivation is supported.
- Validate physical units, historical reference periods, numerical ranges, and time boundaries.
- Check rolling statistics use only past observations and do not silently fill missing source data with zeros.

**Deliverable:** Versioned, documented risk-feature table with unit tests.

### Phase 2 — Environmental Risk Engine v1

- Create transparent drought, heat, and excess-water risk rules.
- Separate observed variables from inferred risk levels.
- Report missing-input and coarse-resolution flags.
- Backtest against historical observations where possible, without claiming accuracy on absent ground truth.

**Deliverable:** Daily risk indicators and human-readable explanations.

### Phase 3 — Sowing Window Engine

- Define crop-specific agronomic requirements from appropriate references.
- Score historical candidate dates using information available by each decision date.
- Compare environmental trade-offs and record limitations.

**Deliverable:** Candidate sowing-window assessments, not uncalibrated success probabilities.

### Phase 4 — Crop Rotation Recommendation Engine

- Integrate five-crop GAEZ results with family/history constraints, seasonal requirements and resource considerations.
- Implement transparent multi-criteria scoring.
- Explain why options are included, penalized or excluded.

**Deliverable:** Explainable provisional crop-option ranking, conditional on known field history.

### Phase 5 — Decision Fusion & Streamlit application

- Connect the engines to a common decision interface.
- Add map, historical charts, source coverage, scenario comparison and downloadable results.
- Display confidence/quality signals based on observed completeness, not fabricated probabilities.

**Deliverable:** End-to-end usable prototype.

### Phase 6 — Machine-learning training and evaluation

- Obtain verified parcel boundaries, actual crop histories, sowing dates and outcomes for multiple independent locations.
- Define targets that correspond to real agricultural decisions.
- Train baseline models before XGBoost/LightGBM and use appropriate temporal/spatial validation.
- Evaluate calibration, generalization and possible data leakage.

**Deliverable:** Defensible supervised models, only when labeled data supports them.

## 8. Key limitation and immediate recommendation

The project currently has one **provisional study location** and six seasons of environmental context, rather than thousands of independent, labeled agricultural observations. This is adequate for engineering and testing environmental risk indicators; it is **not** sufficient to establish a reliable supervised predictor of sowing success or crop rotation.

**Recommended next implementation:** **Environmental Risk Engine v1**, starting from `environment_multisource_daily.parquet`, with transparent rules for soil moisture, rainfall and temperature. Add sowing-window and crop-rotation logic only after these inputs and their limitations are clearly documented.

---

*Prepared from the AgriSim AI implementation status and results reported in the conversation on 14 November 2026.*
