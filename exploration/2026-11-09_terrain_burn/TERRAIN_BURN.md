# Terrain and burn: NASADEM + MODIS (2026-11-09)

**NASADEM** (`data_prep/terrain_nasadem.py`, one 9 MB tile, 13 s) on the 30 m Landsat grid →
`data/processed/terrain_30m.tif`: elevation, slope, D8 upslope area (priority-flood filled), RUSLE LS (Moore & Burch,
slope length capped 300 m), share of upslope area burned (dNBR ≥ 0.27).

Study area: 29,034 ha land, median elevation 175 m, **median slope 11°, 32 % steeper than 15°**.

| Land use (Landsat 2013–2020) | ha | Slope median | > 15° | LS median | Upslope > 50 % burned | Burned itself (dNBR ≥ 0.10) |
|---|---|---|---|---|---|---|
| Rainfed field | 441 | 3.8° | 1 % | 1.2 | 27 % | 72 % |
| Irrigated field | 491 | 1.5° | 0 % | 0.4 | 27 % | 53 % |
| Woody | 26,605 | 11.8° | 34 % | 5.2 | 64 % | 73 % |
| Grazing (herb/shrub) | 1,242 | 5.1° | 14 % | 1.7 | 15 % | 37 % |

Reading: fields lie on flat valley floors below steep burned slopes. **69 ha of fields collect runoff from large
(≥ 1.8 ha), mostly burned catchments**: the receiving end of storm-Athena-type floods (run-on and sediment).

**MODIS MCD64A1** (`data_prep/modis_burned_area.py`, Planetary Computer COGs) → `modis_mcd64a1_2021_burndate.tif`.
MODIS 22,007 ha vs Landsat 20,513 ha burned (land only); **94 % of the Landsat burn is inside MODIS, 88 % the other
way**. Burn dates: 4 Aug 994 ha, 5 Aug 3,367, **6 Aug 11,456**, 7 Aug 4,654, 8 Aug 391, 9 Aug 1,003 ha.
Spread: south-west first (2–4 Aug), then north and east (5–7 Aug), then south (8–9 Aug).

Figure: `terrain_burn_overview.png` (`overview.py`).

Caveats: D8 on 30 m DEM, edges of the study area cut catchments that start outside it; LS cap is a convention.
