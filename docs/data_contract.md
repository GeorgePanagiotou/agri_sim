# AgriSim AI — data contract and scientific boundaries

## Approved resources only

The project uses NASA Landsat/HLS, SMAP, GPM IMERG, POWER, MODIS/VIIRS, ECOSTRESS and SRTM; ESA Sentinel-2 and ERA5-Land; and FAO GAEZ, all named in the Space Apps 2026 resources shared by the team. US-only products (NAIP/CDL/SSURGO/PRISM) are listed by the challenge but are not suitable for Evia. The original ISRIC SoilGrids and NASA GRACE files are deliberately excluded because they were **not** in the pasted resource list. Microsoft Planetary Computer is an access mirror for the *underlying approved Landsat/HLS product*, not a new science dataset. See `configs/sources.json`.

## Core tables

| File | Primary key | Meaning and caution |
|---|---|---|
| `data/processed/features/vegetation_observations.csv` | `(field_id,source,date_utc)` | Quality-masked NDVI, EVI2, SAVI and fraction above NDVI 0.3. Provisional centers flagged. |
| `data/processed/features/greenup_events.csv` | `(field_id,season,source)` | Retrospective spectral transition interval between last low and first high clear observation; **not actual planted-crop emergence**. |
| `data/processed/features/environment_daily.parquet` | `date` | NASA regional weather and soil moisture; ESA ERA5-Land optional. No inferred field-level resolution. |
| `data/processed/features/sowing_candidate_features.csv` | `(field_id,candidate_week_start)` | Rolling precipitation, regional wetness and degree-day features computed from strictly **prior completed days**. |
| `data/processed/features/site_characteristics.csv` | `field_id` | Optional NASA SRTM and FAO GAEZ point-sampled rasters, **not parcel averages**. |
| `data/processed/features/ecostress_overpasses.csv` | `(field_id,date_utc,source_file)` | Optional NASA ECOSTRESS ET overpasses; no interpolation across gaps. |
| `outputs/sowing_recommendations.csv` | `(field_id,candidate_week_start)` | Heuristic flags and evidence; NOT probability of sowing success or forecast. |
| `outputs/risk_alerts.csv` | `(field_id,candidate_week_start)` | Rule counts, not calibrated risk probabilities. |
| `outputs/decision_summary.csv` | `(field_id,candidate_week_start,strategy_id)` | Joined sowing/risk/rotation evidence; no invented probabilities or yields. |
| `outputs/rotation_comparisons.csv` | `strategy_id` | Farmer/agronomist-entered relative 0–5 scores and user priorities; missing means **not ranked**. |
| `data/labels/observed_outcomes_template.csv` | `(field_id,candidate_week_start,crop_id)` | Template for independently verified actual sowing success and days to emergence. Leave empty until ground truth exists. |

## Cross-source temporal and spatial rules

1. A 9 km SMAP value describes a regional cell. It must not be labeled as a 10 m Sentinel-2 or 30 m Landsat measurement. NASA POWER and ERA5-Land are regional too.
2. NDVI, EVI2 and SAVI are calculated from *surface reflectance*, **not RGB PNGs or re-scaled uint8 display bands**.
3. Cloud, shadow, fill and water masks are applied before field statistics. For HLS, Fmask is supplied with each granule. For ESA Sentinel-2 L2A, SCL categories 4 and 5 and dataMask are the conservative starting set.
4. Multi-day Sentinel Process API requests generate **mosaics** with ambiguous per-pixel dates and are excluded from dated time-series processing. Request individual acquisition days instead.
5. If actual parcel polygons are absent, input point/windows are provisional. Such observations cannot establish a farmer's crop identity or reliably form independent training examples.
6. Retrospective green-up estimates necessarily use subsequent observation dates. They must **not be joined as known predictors** to earlier candidate-week predictions.
7. Rain/temperature/soil-water rolling features use completed prior days (`rolling(...).shift(1)`), not the candidate week's future observations. The historical replay is not a future weather forecast.
8. ERA5-Land NetCDF parser supports t2m, swvl1 and stl1 with explicit Kelvin-to-Celsius conversion. ERA5 precipitation accumulation conversion requires validating exact CDS time-step conventions and is not used; GPM supplies precipitation.
9. FAO GAEZ raster classifications require product-specific legends, crop, scenario and input regime. The optional sampler reports a **raw** value and does not automatically treat that as a 0–1 suitability probability.
10. If independent farm outcomes are unavailable, XGBoost training refuses to run. Rule-based outputs are labeled as heuristics; no fake supervised metrics are generated.

## Verification needed before any field-level agronomic advice

- Confirm actual farm and parcel boundaries (`fields.geojson`).
- Obtain sowing dates, crop identity, crop-specific viable temperature and soil-moisture windows, and actual emergence observations.
- Validate and calibrate 0–5 rotation tradeoff scores locally (feed, pollinator, soil-cover and market conditions).
- Separate independent farms and later seasons for evaluation. Satellite-derived pseudo labels are **not** a substitute for independent test observations.
- Verify the source products, QA conventions, available years and licenses using the official portals; live download endpoints were not exercised during packaging.
