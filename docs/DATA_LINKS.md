# Data links for the submission (NASA data · partner and other data)

For the Space Apps project page fields **"NASA Data"** and **"Space Agency Partner & Other Data"**. Every dataset
the product uses, with where it is used. Details and file formats: [DATA.md](DATA.md). Checked against the
challenge's Resources tab (pulled 2026-11-15) at the end.

## NASA data (used in the product)

| Dataset | Product / version | Link | Used for |
|---|---|---|---|
| Landsat 4/5/7/8/9 (NASA/USGS) | Collection 2 Level-2 surface reflectance, 1984–2026 | https://www.usgs.gov/landsat-missions/landsat-collection-2-level-2-science-products · access: https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2 | 40-year field history (crop / fallow per season), field map, 2021 burn severity (dNBR), ML targets and winter-NDVI features |
| HLS (Harmonized Landsat Sentinel-2) | HLSL30 / HLSS30 v2.0 | https://lpdaac.usgs.gov/products/hlsl30v002/ · https://lpdaac.usgs.gov/products/hlss30v002/ | Dense NDVI time series, green-up evidence for the pilot fields |
| GPM IMERG Final | GPM_3IMERGDF v07, daily 0.1° | https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGDF_07/summary · https://gpm.nasa.gov/data/imerg | Rain 2001–Sep 2025: risk engine, sowing windows, ML features |
| GPM IMERG Late | GPM_3IMERGDL v07, daily 0.1° | https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGDL_07/summary | Rain from Oct 2025 to yesterday, scaled to the Final level per area |
| SMAP | SPL4SMGP (L4 surface/root-zone soil moisture, soil temperature) · SPL3SMP_E | https://nsidc.org/data/spl4smgp · https://nsidc.org/data/spl3smp_e · https://www.earthdata.nasa.gov/data/platforms/space-based-platforms/smap | Sowing check (seedbed moisture, soil temperature) |
| NASA POWER | Daily agro-climatology (community AG) + monthly climatology API | https://power.larc.nasa.gov/ · https://power.larc.nasa.gov/docs/services/api/ | Temperature, heat / frost, reference periods 1991–2020, climate API, Köppen class for any area |
| NASADEM | NASADEM_HGT v001 (30 m) | https://lpdaac.usgs.gov/products/nasadem_hgtv001/ · https://www.earthdata.nasa.gov/data/instruments/srtm | Elevation, slope, flow accumulation, RUSLE LS (erosion) |
| MODIS Vegetation Indices | MOD13Q1 v061 (250 m, 16-day) | https://lpdaac.usgs.gov/products/mod13q1v061/ | Long NDVI record 2000–2025 (context, checks) |
| MODIS ET | MOD16A2GF v061 (500 m, 8-day) | https://lpdaac.usgs.gov/products/mod16a2gfv061/ | Evapotranspiration features (tested; no ML skill) |
| MODIS LST | MOD11A2 v061 (1 km, 8-day) | https://lpdaac.usgs.gov/products/mod11a2v061/ | Land surface temperature features (tested; no ML skill) |
| MODIS Burned Area | MCD64A1 v061 | https://lpdaac.usgs.gov/products/mcd64a1v061/ | 2021 fire date, cross-check of the Landsat burn map |
| ECOSTRESS | ECO_L3T_JET v002 (70 m daily ET) | https://lpdaac.usgs.gov/products/eco_l3t_jetv002/ · https://ecostress.jpl.nasa.gov/data | Field-scale dry-season water use 2022–2025 |
| GRACE / GRACE-FO | JPL mascon RL06.3 v04 · GRACE-DA drought (GRACEDADM_CLSM025GL_7D v3.0) | https://podaac.jpl.nasa.gov/dataset/TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4 · https://disc.gsfc.nasa.gov/datasets/GRACEDADM_CLSM025GL_7D_3.0/summary | Regional water storage and drought context |

**NASA access services used:**
- NASA Earthdata / CMR search: https://www.earthdata.nasa.gov/ · https://search.earthdata.nasa.gov/
- Earthdata Login: https://urs.earthdata.nasa.gov/
- Earthdata cloud OPeNDAP: https://opendap.earthdata.nasa.gov/
- GES DISC: https://disc.gsfc.nasa.gov/
- AppEEARS: https://appeears.earthdatacloud.nasa.gov/
- NSIDC DAAC: https://nsidc.org/
- LP DAAC: https://lpdaac.usgs.gov/products/
- earthaccess Python library: https://github.com/nsidc/earthaccess

## Space agency partner and other data

| Dataset | Licence | Link | Used for |
|---|---|---|---|
| FAO GAEZ v4 crop suitability (rainfed, low input, 1981–2010) | CC BY 4.0 (FAO & IIASA) | https://gaez.fao.org | Crop suitability of wheat, barley, maize, chickpea, dry pea for any area; global rasters in `data/reference/gaez/` |
| SoilGrids 2.0 (ISRIC) | CC BY 4.0 | https://www.isric.org/explore/soilgrids · https://files.isric.org/soilgrids/latest/data/ | Soil texture, organic carbon, pH, nitrogen, water holding capacity, RUSLE K |
| Sentinel-2 L2A (ESA Copernicus) | Copernicus open licence | https://dataspace.copernicus.eu · https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a | Exploration only: area search and an S2-vs-HLS NDVI check; not in the product |
| ESA WorldCover, EFFIS (Copernicus) | CC BY 4.0 / Copernicus | https://esa-worldcover.org · https://forest-fire.emergency.copernicus.eu | Exploration only (area search, fire context) |
| Microsoft Planetary Computer | Data under each source's licence | https://planetarycomputer.microsoft.com/ | Access to Landsat C2 L2, HLS and Sentinel-2 cloud-optimised files (window reads) |
| OpenStreetMap / CARTO basemap | ODbL / CARTO attribution | https://www.openstreetmap.org/copyright · https://carto.com/attributions | Map backgrounds in the app |

**Methods cited:**
- Köppen–Geiger rules: Beck et al. 2018, *Scientific Data* 5:180214, https://doi.org/10.1038/sdata.2018.214
- FAO-56 reference evapotranspiration: https://www.fao.org/4/x0490e/x0490e00.htm
- USDM-style percentile drought classes and ETCCDI climate indices: https://www.drought.gov/data-maps-tools/us-drought-monitor · https://etccdi.pacificclimate.org/list_27_indices.shtml

## Challenge Resources tab (Field Shift), checked 2026-11-15

| Resource | Used? |
|---|---|
| https://power.larc.nasa.gov/ | **yes**: NASA POWER daily + climatology |
| https://gpm.nasa.gov/data | **yes**: IMERG Final + Late |
| https://www.earthdata.nasa.gov/ | **yes**: search and login for all Earthdata products |
| https://lpdaac.usgs.gov/products/ | **yes**: HLS, NASADEM, MODIS, ECOSTRESS |
| https://www.earthdata.nasa.gov/data/platforms/space-based-platforms/smap | **yes**: SMAP L4 + L3 |
| https://www.earthdata.nasa.gov/data/instruments/srtm | **yes**: NASADEM (the reprocessed SRTM) |
| https://ecostress.jpl.nasa.gov/data | **yes**: ECOSTRESS JET ET |
| https://gaez.fao.org | **yes**: GAEZ v4 crop suitability |
| https://earthexplorer.usgs.gov/ | **yes, same data**: Landsat C2 L2 read from the Planetary Computer mirror |
| https://dataspace.copernicus.eu | exploration only (Sentinel-2) |
| https://search.earthdata.nasa.gov/search?q=VIIRS | no: Landsat/HLS at 30 m fit field scale better |
| https://gedi.umd.edu/data | no: canopy structure, not needed for annual crops |
| https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels | no: POWER + IMERG cover climate (an ERA5-Land loader exists but is not used) |
| https://openetdata.org | no: western US only |
| https://quickstats.nass.usda.gov, https://nassgeodata.gmu.edu/CropScape/, https://naip-usdaonline.hub.arcgis.com/, https://websoilsurvey.nrcs.usda.gov/app/, https://www.nrcs.usda.gov/resources/data-and-reports/soils, https://waterdata.usgs.gov/nwis, https://prism.oregonstate.edu, https://www.cocorahs.org/Maps, https://www.landfire.gov, https://www.usgs.gov/centers/eros/science/national-land-cover-database, https://www.ams.usda.gov/market-news, https://www.nal.usda.gov/services/agdatacommons | no: United States only; our demo areas are in Greece (SoilGrids and GAEZ replace the US soil and crop layers) |
