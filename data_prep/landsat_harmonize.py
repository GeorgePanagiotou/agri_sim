"""Cross-sensor NDVI harmonization from our own data: near-same-day scene pairs over the study area
(Landsat 5 vs 7 in 1999-2011, Landsat 7 vs 8 in 2013-2017 before Landsat 7's orbit drift, Landsat 9 vs 8 in
2021-2025). For pixels clear in both scenes, a reduced-major-axis fit gives  ndvi_ref = a + b * ndvi_sensor.
Landsat 8 (OLI) is the reference; Landsat 5 is chained through Landsat 7. Landsat 4 uses the Landsat 5 fit (same TM).

Output: data/processed/landsat_ndvi_harmonization.json (fit per sensor, pairs used)

    ..\\.venv\\Scripts\\python.exe data_prep\\landsat_harmonize.py
"""
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from config import PROC
from landsat_common import catalog, clear_mask, reflectance

MAX_DAYS, MIN_VALID, PAIRS_PER_GROUP = 8, 0.5, 12
GROUPS = {  # sensor -> reference, years
    "landsat-7": ("landsat-8", 2013, 2017),
    "landsat-5": ("landsat-7", 1999, 2011),
    "landsat-9": ("landsat-8", 2021, 2025),
}
scenes = pd.read_csv(PROC / "landsat_scenes.csv", parse_dates=["date"])
scenes = scenes[scenes.valid_share >= MIN_VALID]
cat = catalog()


def ndvi(item_id):
    it = next(cat.search(collections=["landsat-c2-l2"], ids=[item_id]).items())
    ok = clear_mask(it)
    red, nir = reflectance(it, "red"), reflectance(it, "nir08")
    with np.errstate(all="ignore"):
        return np.where(ok & (red > 0) & (nir > 0), (nir - red) / (nir + red), np.nan)


def rma(x, y):
    b = np.sign(np.corrcoef(x, y)[0, 1]) * np.std(y) / np.std(x)
    return float(np.mean(y) - b * np.mean(x)), float(b)


fits, rng = {}, np.random.default_rng(0)
for sensor, (ref, y0, y1) in GROUPS.items():
    a = scenes[(scenes.platform == sensor) & scenes.date.dt.year.between(y0, y1)]
    b = scenes[(scenes.platform == ref) & scenes.date.dt.year.between(y0, y1)]
    pairs = []
    for _, r in a.iterrows():
        d = (b.date - r.date).dt.days.abs()
        if len(d) and d.min() <= MAX_DAYS:
            pairs.append((r.id, b.loc[d.idxmin(), "id"], int(d.min())))
    # spread over the seasons/years: take every k-th pair
    pairs = pairs[:: max(1, len(pairs) // PAIRS_PER_GROUP)][:PAIRS_PER_GROUP]
    xs, ys = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda p: (ndvi(p[0]), ndvi(p[1])), pairs))
    for xa, ya in results:
        m = np.isfinite(xa) & np.isfinite(ya) & (xa > -0.1) & (ya > -0.1)
        if m.sum() < 1000:
            continue
        idx = rng.choice(np.flatnonzero(m), size=min(20000, int(m.sum())), replace=False)
        xs.append(xa.ravel()[idx]); ys.append(ya.ravel()[idx])
    x, y = np.concatenate(xs), np.concatenate(ys)
    a0, b0 = rma(x, y)
    fits[sensor] = {"reference": ref, "a": round(a0, 4), "b": round(b0, 4), "pixels": int(x.size),
                    "pairs": [{"sensor": p[0], "reference": p[1], "days_apart": p[2]} for p in pairs],
                    "median_diff_ref_minus_sensor": round(float(np.median(y - x)), 4),
                    "r": round(float(np.corrcoef(x, y)[0, 1]), 3)}
    print(sensor, "->", ref, {k: v for k, v in fits[sensor].items() if k != "pairs"}, "pairs", len(pairs))

# Used: OFFSETS (median difference), chained L5 -> L7 -> L8. The RMA slopes are kept for the record only: pixel noise
# from real change within 8 days and residual clouds (even L9 vs L8, near-identical sensors, give r ~0.79) bends
# them; the median differences agree with published comparisons (TM/ETM+ NDVI a few hundredths below OLI).
d7 = fits["landsat-7"]["median_diff_ref_minus_sensor"]
d5 = fits["landsat-5"]["median_diff_ref_minus_sensor"]
offset = {"landsat-8": 0.0, "landsat-7": round(d7, 4), "landsat-9": fits["landsat-9"]["median_diff_ref_minus_sensor"],
          "landsat-5": round(d5 + d7, 4)}
offset["landsat-4"] = offset["landsat-5"]
json.dump({"offset_to_landsat8": offset, "fits": fits,
           "method": f"median NDVI difference on clear pixels of near-same-day pairs (<= {MAX_DAYS} days), study "
                     "area; ndvi_l8 = ndvi_sensor + offset. RMA fits recorded but not used."},
          open(PROC / "landsat_ndvi_harmonization.json", "w"), indent=1)
print("offset to Landsat 8:", offset)
