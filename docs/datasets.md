# Approved datasets and native resolution

| Source | Intended use | Native caution |
|---|---|---|
| NASA HLS / Landsat | reflectance, greenness, historical change | 30 m fields have mixed pixels |
| ESA Sentinel-2 | multispectral detail | 10–20 m, compare acquisition times and SCL masks |
| NASA SMAP | regional surface soil moisture | ~9 km, not a parcel sensor |
| NASA IMERG | rainfall history | ~0.1° grid, regional |
| NASA POWER | weather and environmental history | coarse regional grid |
| NASA MODIS/VIIRS | regional phenology, ET, LST | 250–1000 m, cannot directly label 30 m crops |
| NASA ECOSTRESS | ET and surface thermal context | intermittent overpasses |
| NASA SRTM | elevation and derived terrain risk | elevation is not drainage ground truth |
| ESA/ECMWF ERA5-Land | weather/soil gap context | hourly gridded reanalysis |
| FAO GAEZ | regional crop suitability | scenario-specific layer codes need documentation |

Only these and other categories explicitly named in the user-supplied challenge Resources tab are eligible. The repository does not ingest ISRIC SoilGrids or GRACE even if present in older research notes. Source code provenance does not independently verify farm outcomes.
