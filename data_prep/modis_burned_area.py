"""NASA MODIS MCD64A1 v061 burned area (500 m, monthly, burn day of year) for Aug 2021 on the study-area grid, and its
agreement with the Landsat dNBR burn map. Window reads from Microsoft Planetary Computer COGs (nothing downloaded whole).

Output: data/processed/modis_mcd64a1_2021_burndate.tif (uint16 day of year 2021, 0 = not burned in Aug-Sep 2021)

    ..\\.venv\\Scripts\\python.exe data_prep\\modis_burned_area.py
"""
import numpy as np
import rasterio
from rasterio.warp import Resampling

from config import PROC
from landsat_common import BBOX, catalog, profile, read

items = list(catalog().search(collections=["modis-64A1-061"], bbox=BBOX, datetime="2021-08-01/2021-09-30").items())
print("MCD64A1 items:", [i.id for i in items])
doy = np.zeros(read(items[0].assets["Burn_Date"].href, Resampling.nearest).shape, "uint16")
for it in items:
    d = read(it.assets["Burn_Date"].href, Resampling.nearest)
    new = (d > 0) & (doy == 0)
    doy[new] = d[new]
with rasterio.open(PROC / "modis_mcd64a1_2021_burndate.tif", "w", **profile("uint16", nodata=None)) as dst:
    dst.write(doy, 1)

with rasterio.open(PROC / "landsat_field_map_30m.tif") as s:
    land = s.read(1) > 0
with rasterio.open(PROC / "landsat_dnbr_2021_30m.tif") as s:
    ls = (np.nan_to_num(s.read(1), nan=0) >= 0.10) & land
mo = (doy > 0) & land
ha = 0.09
both = (ls & mo).sum()
print({"modis_burned_ha": round(float(mo.sum() * ha)), "landsat_burned_ha": round(float(ls.sum() * ha)),
       "agree_ha": round(float(both * ha)), "landsat_inside_modis_share": round(float(both / ls.sum()), 2),
       "modis_inside_landsat_share": round(float(both / mo.sum()), 2),
       "burn_dates": {f"day {d} ({np.datetime64('2021-01-01') + int(d) - 1})": round(float((doy[land] == d).sum() * ha))
                      for d in np.unique(doy[mo])[:20]}})
