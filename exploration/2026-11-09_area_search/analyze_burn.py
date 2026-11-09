"""Scratch: dNBR from the pre/post Sentinel-2 composites + WorldCover 2020 -> burned land by class, and the
best windows that hold burned fields, burned grazing land (grass/shrub) and forest (bees) together.

    python analyze_burn.py <data_dir> [window_km]
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject, transform_bounds
from scipy.ndimage import uniform_filter

D = Path(sys.argv[1])
WIN_KM = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]


def load(period):
    f = sorted((D / period).glob("*.tif"))[0]
    with rasterio.open(f) as src:
        a = src.read().astype("float32")
        names = list(src.descriptions)
        prof = src.profile
    if all(names) and set(BANDS) <= set(names):
        a = a[[names.index(b) for b in BANDS]]
    return {b: a[i] for i, b in enumerate(BANDS)}, prof


pre, prof = load("pre_2021-07")
post, _ = load("post_2021-09")


def nbr(x):
    with np.errstate(invalid="ignore", divide="ignore"):
        return (x["B08"] - x["B12"]) / (x["B08"] + x["B12"])


dnbr = nbr(pre) - nbr(post)
H, W = dnbr.shape
px_ha = abs(prof["transform"].a * prof["transform"].e) / 1e4

lc = np.zeros((H, W), dtype="uint8")
with rasterio.open(D / "worldcover_2020_evia.tif") as src:
    reproject(rasterio.band(src, 1), lc, dst_transform=prof["transform"], dst_crs=prof["crs"],
              resampling=Resampling.mode)

# USGS-style dNBR classes: <0.10 unburned, 0.10-0.27 low, 0.27-0.44 moderate-low, 0.44-0.66 mod-high, >0.66 high
burn = dnbr > 0.27
valid = np.isfinite(dnbr) & (lc != 80) & (lc != 0)
NAMES = {10: "tree", 20: "shrub", 30: "grass", 40: "cropland", 50: "built", 60: "bare", 90: "wetland"}
stats = {}
for k, n in NAMES.items():
    m = valid & (lc == k)
    stats[n] = {"total_ha": round(float(m.sum() * px_ha)), "burned_ha": round(float((m & burn).sum() * px_ha))}
stats["all_land"] = {"total_ha": round(float(valid.sum() * px_ha)), "burned_ha": round(float((valid & burn).sum() * px_ha))}
print(json.dumps(stats, indent=1))

# Window search: area (ha) of burned cropland, burned grazing land (grass+shrub), forest (burned + unburned edge)
win = int(round(WIN_KM * 1000 / prof["transform"].a))
def wsum(mask):
    return uniform_filter(mask.astype("float32"), size=win, mode="constant") * win * win * px_ha
crop_b = wsum(valid & burn & (lc == 40))
graz_b = wsum(valid & burn & np.isin(lc, (20, 30)))
tree_b = wsum(valid & burn & (lc == 10))
tree_u = wsum(valid & ~burn & (lc == 10))
crop_all = wsum(valid & (lc == 40))
# balanced score: all of burned crop, burned grazing, burned forest, and some forest still standing (bee forage)
score = np.cbrt(crop_b * graz_b * tree_b) * np.sqrt(np.minimum(tree_u, 500) / 500)
score[:win // 2] = score[-win // 2:] = 0
score[:, :win // 2] = score[:, -win // 2:] = 0

picks = []
s = score.copy()
for _ in range(6):
    r, c = np.unravel_index(np.nanargmax(s), s.shape)
    if s[r, c] <= 0:
        break
    x, y = rasterio.transform.xy(prof["transform"], r, c)
    lon, lat = transform_bounds(prof["crs"], "EPSG:4326", x, y, x, y)[:2]
    half = win // 2
    r0, r1, c0, c1 = r - half, r + half, c - half, c + half
    bx0, by1 = rasterio.transform.xy(prof["transform"], r0, c0)
    bx1, by0 = rasterio.transform.xy(prof["transform"], r1, c1)
    bbox = transform_bounds(prof["crs"], "EPSG:4326", bx0, by0, bx1, by1)
    picks.append({"center_lonlat": [round(lon, 4), round(lat, 4)], "bbox_wsen": [round(v, 4) for v in bbox],
                  "burned_cropland_ha": round(float(crop_b[r, c])), "cropland_ha": round(float(crop_all[r, c])),
                  "burned_grass_shrub_ha": round(float(graz_b[r, c])), "burned_forest_ha": round(float(tree_b[r, c])),
                  "unburned_forest_ha": round(float(tree_u[r, c])), "score": round(float(s[r, c]), 1)})
    s[max(0, r - win):r + win, max(0, c - win):c + win] = 0  # no overlapping picks
print(json.dumps(picks, indent=1))
json.dump({"stats": stats, "window_km": WIN_KM, "picks": picks}, open(D / f"picks_{int(WIN_KM)}km.json", "w"), indent=1)

with rasterio.open(D / "dnbr.tif", "w", **(prof | {"count": 1, "dtype": "float32", "compress": "deflate"})) as dst:
    dst.write(dnbr.astype("float32"), 1)
with rasterio.open(D / "worldcover_on_s2grid.tif", "w", **(prof | {"count": 1, "dtype": "uint8", "nodata": 0,
                                                                   "compress": "deflate"})) as dst:
    dst.write(lc, 1)
