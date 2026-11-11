# Exploration (for the team to look at)

Dated checks and first looks at the data, with their figures, small results and scripts. **Not the product**: some of
it used Sentinel-2, ESA WorldCover and EFFIS, which the product does not use (NASA/USGS only, see
[docs/DATA.md](../docs/DATA.md)). The product's data lives in [data/processed/](../data/processed/).

| Folder | What | Data used |
|---|---|---|
| [2026-11-09_area_search](2026-11-09_area_search/AREA_SEARCH.md) | How the study area "Kireas – Agia Anna" was chosen: burn (dNBR) × land cover window search; fields seen in spring 2021 / 2022; first Landsat history; POWER first look | Sentinel-2 (via STAIR/CDSE), WorldCover, EFFIS, OSM names · **exploration only** |
| [2026-11-09_landsat_fields](2026-11-09_landsat_fields/LANDSAT_FIELDS.md) | Landsat-only field map and crop/fallow history: bugs found, results, caveats; IMERG vs POWER | Landsat, GPM IMERG, POWER |
| [2026-11-09_terrain_burn](2026-11-09_terrain_burn/TERRAIN_BURN.md) | NASADEM terrain, burned runoff onto fields, MODIS burn dates vs Landsat | NASADEM, MODIS MCD64A1, Landsat |
| [2026-11-11_smap_check](2026-11-11_smap_check/SMAP_CHECK.md) | Is the very low 2025 SMAP soil moisture real? Direction yes (2024–25 driest everywhere), size no (SMAP shifted low all 2025) | SMAP L3, POWER, GRACE-DA, IMERG, MODIS |

Quick images: [data/processed/imagery/](../data/processed/imagery/README.md) (Landsat true colour 1987, before/after
the fire, 2022, 2025; open the `.png` or load the `.tif` in QGIS).

Not in git (too big): `data/processed/landsat_ndvi_monthly_30m.nc` (125 MB). Rebuild it with
`..\.venv\Scripts\python.exe data_prep\landsat_harmonize.py` then `data_prep\landsat_ndvi_history.py` (~15 min,
no login needed), or ask for a copy.
