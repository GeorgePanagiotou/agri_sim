"""Landsat-only burn map of the August 2021 fire: dNBR from the clearest Landsat 8/9 scenes before (July 2021) and
after (late Aug - early Oct 2021, before regrowth), on the study-area 30 m grid.

Output: data/processed/landsat_dnbr_2021_30m.tif (float32) + the scenes used in data/processed/landsat_burn_scenes.csv
Burn classes (USGS): < 0.10 unburned, 0.10-0.27 low, 0.27-0.44 moderate-low, 0.44-0.66 moderate-high, > 0.66 high.

    ..\\.venv\\Scripts\\python.exe data_prep\\landsat_burn_2021.py
"""
import numpy as np
import pandas as pd
import rasterio

from config import PROC
from landsat_common import BBOX, catalog, clear_mask, profile, reflectance

WINDOWS = {"pre": "2021-07-01/2021-08-02", "post": "2021-08-16/2021-10-07"}  # storm Athena from 8 Oct
cat = catalog()
nbr, used = {}, []
for name, dt in WINDOWS.items():
    items = [i for i in cat.search(collections=["landsat-c2-l2"], bbox=BBOX, datetime=dt,
                                   query={"eo:cloud_cover": {"lt": 30},
                                          "platform": {"in": ["landsat-8", "landsat-9"]}}).items()]
    stack = []
    for it in sorted(items, key=lambda i: i.properties["eo:cloud_cover"]):
        ok = clear_mask(it)
        if ok.mean() < 0.6:
            continue
        nir, sw2 = reflectance(it, "nir08"), reflectance(it, "swir22")
        with np.errstate(all="ignore"):
            stack.append(np.where(ok & (nir + sw2 > 0), (nir - sw2) / (nir + sw2), np.nan))
        used.append({"period": name, "id": it.id, "date": it.properties["datetime"][:10],
                     "platform": it.properties["platform"], "clear_share": round(float(ok.mean()), 3)})
        if len(stack) == 3:
            break
    nbr[name] = np.nanmedian(np.stack(stack), axis=0)
    print(name, "scenes:", [u["date"] for u in used if u["period"] == name])

dnbr = (nbr["pre"] - nbr["post"]).astype("float32")
with rasterio.open(PROC / "landsat_dnbr_2021_30m.tif", "w", **profile("float32", nodata=np.nan)) as dst:
    dst.write(dnbr, 1)
pd.DataFrame(used).to_csv(PROC / "landsat_burn_scenes.csv", index=False)
ha = 0.09
for lo, hi, lab in [(0.10, 0.27, "low"), (0.27, 0.44, "moderate-low"), (0.44, 0.66, "moderate-high"), (0.66, 9, "high")]:
    print(f"{lab:14s} {int(((dnbr >= lo) & (dnbr < hi)).sum() * ha):6d} ha")
print("burned (dNBR >= 0.10):", int((dnbr >= 0.10).sum() * ha), "ha of", int(np.isfinite(dnbr).sum() * ha), "ha")
