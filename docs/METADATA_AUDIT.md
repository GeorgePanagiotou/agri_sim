# Uploaded metadata audit (November 15, 2026)

The JSON companions below were read directly. Counts are *metadata assertions*, **not independently validated Parquet contents**, because this runtime lacked a Parquet reader.

| Dataset | As of | Rows in JSON | Total manifest features | Selected model features | Latest NDVI |
|---|---|---:|---:|---:|---|
| `training_table_1114` | `11-14` | 122183 | 56 | 29 | ndvi_prior_oct |
| `training_table_v1` | `12-01` | 122183 | 57 | 30 | ndvi_prior_nov |
| `training_table_0201` | `02-01` | 122183 | 59 | 32 | ndvi_prior_jan |
| `training_table_0301` | `03-01` | 122183 | 60 | 33 | ndvi_prior_feb |
| `training_table_0401` | `04-01` | 122183 | 61 | 34 | ndvi_prior_mar |
| `predict_2027_1114` | `11-14` | 4911 | 56 | 29 | ndvi_prior_oct |

Training and 2027 prediction metadata for November 14 have identical ordered feature lists and match `EPSG:32634`.

**Note:** `target_crop` is the satellite-proxy class-1 binary label. Summer crop (class 3) is also encoded as `target_crop=0`.

Important time-leakage flags discovered in the table builder / methodology:
- `burn_class_2021`, `burn_dnbr_2021`, and `terrain_upslope_burned_share` are 2021 event observations. Mask them for pre-2022 decisions.
- The threshold used to create past `target_class` labels was recomputed with later years. `hist_class_*` based on those labels can contain hindsight. This warrants source-level, season-causal relabeling before high-stakes claims.
- Soil static layers are later-era products and cannot be assumed to represent their exact 2002 values.
- March/April models are **in-season monitors**, not pre-season sowing forecasts.

The regression and classification baseline metrics reported in `ml_training_data.md` have **not been re-measured** for this delivery.
