# Environmental Risk Engine v1 (2026-11-14)

Phase 2 of the [gap report](../AgriSim_AI_Implementation_Gap_Report.md): transparent daily risk levels for the Evia
pilot from regional NASA data. **Heuristic, uncalibrated, regional. Not probabilities, not forecasts, not field
measurements.**

```powershell
python -m agrisim.decision_engine.environmental_risk            # 2020-09-01 .. last day with data
python -m agrisim.decision_engine.environmental_risk --start 2024-09-01 --end 2025-06-30
pytest -q tests/test_environmental_risk.py
```

Code: `features/climate_indices.py` (past-only indicators, calendar percentiles) and
`decision_engine/environmental_risk.py` (levels, explanations, CLI). Thresholds and sources:
[`configs/risk_rules.yaml`](../configs/risk_rules.yaml). Inputs are read with the existing loaders of
`features/build_environment_multisource.py`; no GAEZ, Sentinel-2 or HLS needed.

## Rules

Each date is assessed **as of the start of that day**: only completed earlier days are used. "Unusual" always means
compared with the same calendar dates (± a window) in a fixed reference period that ends before the assessed seasons:
POWER 1991–2020 (WMO normal), IMERG 2001–2020.

| Hazard | Indicator | watch / warning / severe | Basis |
|---|---|---|---|
| Drought | rain of the last 90 days, percentile | ≤ 30 / ≤ 20 / ≤ 10 | US Drought Monitor D0 / D1 / D2 |
| Dry spell | consecutive days < 1 mm (≥ 7 days to count), percentile for the date | ≥ 70 / ≥ 80 / ≥ 90 | ETCCDI CDD day definition; bands project choice |
| Heat | days in the last 7 with Tmax > calendar 90th percentile **and** ≥ 30 °C | ≥ 2 / ≥ 4 / ≥ 6 days | ETCCDI TX90p, WSDI 6-day spell; 30 °C floor project choice |
| Frost | days in the last 7 with Tmin < 0 °C | ≥ 1 / ≥ 3 / – | ETCCDI FD |
| Heavy rain | wettest day of the last 3 vs wet-day percentiles | ≥ p95 / ≥ p99, +1 level if the 14 days before were ≥ p90 wet | ETCCDI R95p / R99p; wet-ground step project choice |

- **Rain source:** IMERG Final (+ Late Run Oct–Dec 2025, flagged) first. Where the IMERG window is incomplete (2026
  so far), NASA POWER rain is used against its own 1991–2020 baseline, with `confidence_note` = lower.
- **Missing input → `unknown`**, never `none`; the hazards concerned are listed in `hazards_unknown`.
- **Not used for levels:** POWER soil wetness (see check 2) and SMAP (only six seasons, no baseline). Both are in the
  table as context (`root_wetness_pct`, `smap_surface_prior_7d_m3m3`, `smap_soil_temp_prior_7d_c`).

## Output: `outputs/risk_daily.csv` (+ `.json` manifest)

One row per day (`field_id`, `date`). Per hazard: `<hazard>_level` (0–3, empty = unknown), `<hazard>_label`,
`explain_<hazard>` (one sentence with the numbers and sources). Plus `overall_level` / `overall_label` (worst known
hazard), `hazards_flagged`, `hazards_unknown`, every indicator value and percentile, `rain_source`, `rain_support`,
`confidence_note`, `risk_method`.

## Checks on the real data (2020-09-01 .. 2026-10-31, 2,252 days)

1. **Known events are caught:**
   - **Heatwave Jul–Aug 2021:** watch from 31 Jul, severe 4–8 Aug (Tmax 40.8 °C).
   - **Storm Daniel, Sep 2023:** heavy rain warning on 6–7 Sep (82 mm in a day), severe on 8 Sep.
   - **Storm, Dec 2025:** 83 mm in a day, severe.
   - **Storm Elpis, Jan 2022:** frost watch (POWER Tmin −0.4 °C).
   - **2024–25 drought:** warning in Nov 2024, severe in Apr–May 2025 (90-day rain at the 4th percentile).
2. **POWER soil wetness is not usable for drought here.**
   - POWER rain disagrees with IMERG: about 1,000 mm in 2020 and 2021, against 520–640 mm.
   - GWETROOT has a model floor of about 0.53, so values pile up at the bottom.
   - Root-zone wetness read the 92nd–94th percentile in Jan–Mar 2025, the driest season on record.
   - Dropped from the levels.
3. **The first version flagged "heat" on 47 % of January days.** That was unusual mildness, not heat stress. The 30 °C
   floor fixed it: heat now appears only in May–October.
4. **The levels are frequent because the recent years really are dry.** Drought warning or severe on 31–64 % of days
   in the agricultural years 2020–2024 (IMERG yearly rain 480–640 mm against a 2001–2020 mean of about 670 mm). The
   bands are fixed against the reference period, not re-tuned to give fewer alerts.

## Limitations and next steps

- Regional cells (IMERG ~10 km, POWER ~50 km): the level describes the area, not the pilot field.
- Thresholds marked *project choice* need review by a local agronomist; crop-specific heat, frost and moisture
  thresholds belong in the sowing-window engine (crop table).
- No validation against farm outcomes (none available). The checks above are plausibility checks against known
  events only.
- Next: weekly summary for candidate sowing weeks; feed `drought` / `heavy_rain` into the sowing-window verdicts and
  the rotation comparison (bare soil × heavy rain = erosion risk).
