# Tasks

## Now

- [ ] Everyone: create an Earthdata Login account
- [ ] Put the Space Apps rules, judging criteria, deadline and the Resources tab in `../admin/`
- [ ] Set up `..\.venv` (Python 3.11) and install `requirements.txt`
- [ ] First look at the data: NASA POWER for 2–3 points; HLS NDVI before/after the fire; GPM monthly rain
- [ ] Check the key insight (STORY.md): bare months vs. erosive autumn rain
- [ ] Pick 2–3 demo spots: burned fields, pastures, apiary areas
- [ ] Rebuild the current rotation of each spot from older Landsat images; confirm with a local contact if possible
- [ ] Search for more detailed / local datasets (list in DATA.md)

## Roles (proposal)

| Person | Part |
|---|---|
| 1 | Data: downloads, harmonized grid, data checks |
| 2 | Engine: indicators, water balance, erosion, crop table, scoring |
| 3 | App + story: Streamlit, visuals, video / pitch |

## Requests

- **App ← data (2026-11-14):** `app/demo_data.py` makes synthetic daily series. The real series for the pilot
  point (Demo site A, Sep–Jun 2020-21 … 2025-26) are already in
  `data/processed/features/environment_multisource_daily.parquet` (`python -m agrisim.pipelines.prepare_multisource`).
  Rain is now complete for 2025-26: IMERG Late fills Jan–Jun 2026, see `gpm_product`.

  | Synthetic column | Real column |
  |---|---|
  | `air_temp_c` | `power_temp_c` |
  | `soil_temp_c` | `smap_soil_temp_c` |
  | `rain_mm` | `gpm_rain_mm` |
  | `soil_moisture_m3m3` | `smap_surface_m3m3` |
  | `ndvi`, `clear_fraction` | `s2_ndvi` / `hls_ndvi`, `s2_clear_fraction` / `hls_clear_fraction` |
  | `rain_prior_7d_mm`, `rain_prior_14d_mm` | `imerg_rain_prior_7d_mm`, `imerg_rain_prior_14d_mm` |
  | `temp_prior_7d_c` | `power_temp_prior_7d_c` |
  | `soil_moisture_prior_7d` | `smap_surface_prior_7d_m3m3` |

  The real risk levels and sowing verdicts are in `outputs/risk_daily.csv` and `outputs/sowing_weeks.csv`.
  ML tables for the engine are in `data/processed/ml/` ([ml_training_data.md](ml_training_data.md)).
