# Landsat-only field map and crop/fallow history: checks (2026-11-09)

Decision: the product uses Landsat (NASA/USGS), not Sentinel-2/WorldCover/EFFIS.

## Pipeline (all in `agrisim/data_prep/`, outputs in `agrisim/data/processed/`)

1. `landsat_harmonize.py`: near-same-day scene pairs (≤ 8 days) over the study area, 12 pairs per sensor pair.
   RMA slopes unusable (even L9 vs L8 r ≈ 0.79: real change within 8 days and residual clouds), so **offsets** (median
   difference) are used: **L5/L4 +0.052, L7 +0.030, L9 −0.003** to Landsat 8. Direction agrees with published
   comparisons (TM/ETM+ NDVI below OLI).
2. `landsat_ndvi_history.py` (rebuilt with offsets): 958 scenes 1984–2025, monthly median NDVI, 30 m, 131 MB local.
3. `landsat_burn_2021.py`: dNBR from L8/9, pre 9 + 25 Jul 2021, post 26 Aug, 11 + 27 Sep 2021.
4. `landsat_field_map.py`: land use per period from yearly phenology; per-pixel crop/fallow threshold (2-means on
   its own spring peaks); water from Landsat QA bit 7 (8 clearest L8 scenes 2016–2020).

## Bugs found and fixed while checking

- Irrigated fields counted as woody (green all summer) → woody now also needs green early spring. Irrigated 10 → 491 ha.
- Sea/beach pixels classed as fields/grazing (NDVI water test broke with the offsets) → Landsat QA water mask.
  Seen in `example_field_curves.png` (flat NDVI ~0.05 for 30 years).

## Results (study area, 30 m)

| | ha |
|---|---|
| Fields 2013–2020 (rainfed 442 + irrigated 491) | 933 |
| Fields 1985–1995 | 1,882 |
| Fields then, not now (candidate abandonment → shrub/woody) | 1,237 |
| Fields (incl. former) burned 2021, dNBR ≥ 0.10 | 576 (field map) |
| Herbaceous/shrub = grazing land (burned) | 1,242 (457) |
| Woody (burned) | 26,606 (19,462) |

Crop/fallow (field pixels incl. former fields; per agricultural year):
- Fallow ≈ 17–18 % of field-years both before (2016–21) and after (2022–25) the fire, burned or not.
- **Summer (irrigated) crops roughly halved after 2021**: burned fields 21 % → 11 %, unburned 30 % → 16 %.
  Candidate reasons: dry years (IMERG Oct 2023 = 6 mm, Oct 2024 = 8 mm, driest in the record), irrigation damage
  after the fire/floods, land-use change. Needs local confirmation.
- Rotation pattern: observed crop↔fallow switch rate 0.35 vs 0.42 if random → **fallow comes in multi-year spells,
  not strict biennial cereal–fallow alternation** (or classification noise). 91 % of rainfed pixels have separable
  good/poor years.

## Caveats

- 30 m pixels mix small fields with hedges/trees; field edges are uncertain.
- "Fallow/low" = poor spring growth: fallow, grazed stubble, failed crop or weeds; cannot separate with NDVI alone.
- Abandonment (1,237 ha) needs checking by eye in old Landsat RGB and with local knowledge.
- Thresholds (0.25 amplitude, 0.30/0.35/0.45/0.50) are hand-set; calibrate with a few known fields.

## Rain: IMERG vs POWER (`agrisim/data/processed/imerg_vs_power_october.csv`)

October 2021: IMERG 147 mm (2nd of 2000–2024, median 50) vs POWER 327 mm (1st). POWER is below IMERG in most years
(corr 0.79) but doubles it in 2021 → **use IMERG**; POWER's "record" is an outlier. Storm days 7–12 Oct: IMERG mean
≈ 70 mm (wettest cell ≈ 120 mm) vs POWER 247 mm. No station totals for North Evia found yet (meteo.gr/NOA archive).

Figures: `landuse_then_now_burn.png`, `crop_fallow_2019_2023.png`, `field_year_shares.png`, `example_field_curves.png`.
