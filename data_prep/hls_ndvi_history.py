"""HLS v2 (Harmonized Landsat Sentinel-2, NASA LP DAAC) NDVI history of the study area on the 30 m grid.

L30 (Landsat 8/9) and S30 (Sentinel-2) are already harmonized by NASA (same 30 m tiling, BRDF and bandpass
adjusted), so together they give an observation every ~2-3 days instead of ~8 with Landsat alone; this matters in
cloudy winters. Only the study-area window of red, NIR and Fmask is read from the COGs on Microsoft Planetary
Computer (mirror of the NASA product), warped to the area grid of landsat_common.py.

NDVI = (NIR - red) / (NIR + red) with L30 B05 / S30 B8A as NIR (narrow NIR, as in the HLS harmonization).
Clear = Fmask bits 1-5 zero (cloud, adjacent cloud, shadow, snow/ice, water) and aerosol not high (bits 6-7 != 3).
Several tiles on the same UTC day are merged (mean of valid values).

Outputs
- data/raw/hls_ndvi/<year>.npz         per-day NDVI stack (uint8, ndvi = (v - 1) / 200 - 0.25; 0 = no data), dates,
                                       sensors (resume: years already done are skipped)
- data/raw/hls_ndvi/<year>_items.csv   every item used: id, date, sensor, tile, cloud cover, clear share
- data/processed/hls_ndvi_monthly_30m.nc  ndvi_max, ndvi_median, nobs (time = month, y, x), same encoding

    ..\\.venv\\Scripts\\python.exe data_prep\\hls_ndvi_history.py [first_year] [last_year] [months, e.g. 9-12,1-5]
Default: 2016 .. this year, all months.
"""
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".TIF,.tif")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

import numpy as np
import pandas as pd
import xarray as xr
from rasterio.warp import Resampling

from config import CRS, PROC, RAW
from landsat_common import BBOX, HEIGHT, RES, WIDTH, X, Y, catalog, read

FIRST = int(sys.argv[1]) if len(sys.argv) > 1 else 2016
LAST = int(sys.argv[2]) if len(sys.argv) > 2 else date.today().year
MONTHS = set(range(1, 13))
if len(sys.argv) > 3:
    MONTHS = set()
    for part in sys.argv[3].split(","):
        a, _, b = part.partition("-")
        MONTHS |= set(range(int(a), int(b or a) + 1))
MAX_CLOUD = 80
NIR = {"hls2-l30": "B05", "hls2-s30": "B8A"}
OUT_YEARS = RAW / "hls_ndvi"
OUT_YEARS.mkdir(parents=True, exist_ok=True)


def encode(ndvi):
    v = np.clip(np.round((ndvi + 0.25) * 200) + 1, 1, 255)
    return np.where(np.isfinite(ndvi), v, 0).astype("uint8")


def item_ndvi(item):
    col = item.collection_id
    try:
        qa = read(item.assets["Fmask"].href, Resampling.nearest)
        red = read(item.assets["B04"].href, Resampling.bilinear).astype("float32")
        nir = read(item.assets[NIR[col]].href, Resampling.bilinear).astype("float32")
    except Exception as exc:  # a broken asset must not stop the run
        return item, None, f"{type(exc).__name__}: {str(exc)[:100]}"
    # WarpedVRT fills outside the tile with 0; HLS fill is -9999 and Fmask 255
    ok = (qa != 255) & ((qa & 62) == 0) & ((qa >> 6) != 3) & (red > 0) & (nir > 0) & (red != -9999) & (nir != -9999)
    red, nir = red * 1e-4, nir * 1e-4
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = np.where(ok, (nir - red) / (nir + red), np.nan).astype("float32")
    return item, ndvi, None


cat = catalog()
for year in range(FIRST, LAST + 1):
    target = OUT_YEARS / f"{year}.npz"
    if target.exists() and year < date.today().year:
        print(year, "exists, skipping")
        continue
    items = []
    for col in NIR:
        items += [it for it in cat.search(collections=[col], bbox=BBOX, datetime=f"{year}-01-01/{year}-12-31",
                                          query={"eo:cloud_cover": {"lt": MAX_CLOUD}}).items()
                  if int(it.properties["datetime"][5:7]) in MONTHS]
    by_day, rows = {}, []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for item, ndvi, err in pool.map(item_ndvi, items):
            p = item.properties
            day = p["datetime"][:10]
            clear = 0.0 if ndvi is None else float(np.isfinite(ndvi).mean())
            rows.append({"id": item.id, "date": day, "sensor": "S30" if item.collection_id.endswith("s30") else "L30",
                         "tile": item.id.split(".")[2], "cloud_cover": p.get("eo:cloud_cover"),
                         "clear_share": round(clear, 3), "error": err or ""})
            if ndvi is not None and clear > 0.01:
                by_day.setdefault(day, []).append(ndvi)
    days = sorted(by_day)
    stack = np.zeros((len(days), HEIGHT, WIDTH), "uint8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i, day in enumerate(days):
            stack[i] = encode(np.nanmean(np.stack(by_day[day]), axis=0))
    sensors = np.array(["+".join(sorted({r["sensor"] for r in rows if r["date"] == d})) for d in days])
    np.savez_compressed(target, ndvi=stack, dates=np.array(days), sensors=sensors)
    pd.DataFrame(rows).sort_values("date").to_csv(OUT_YEARS / f"{year}_items.csv", index=False)
    print(f"{year}: {len(items)} items, {len(days)} days with clear pixels", flush=True)

# Monthly cube from every year on disk
months, mx, md, nobs = [], [], [], []
for f in sorted(OUT_YEARS.glob("[12][0-9][0-9][0-9].npz")):
    z = np.load(f)
    dates = pd.to_datetime(z["dates"])
    v = z["ndvi"]
    for m in range(1, 13):
        sel = dates.month == m
        if not sel.any():
            continue
        arr = np.where(v[sel] == 0, np.nan, (v[sel].astype("float32") - 1) / 200 - 0.25)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mx.append(encode(np.nanmax(arr, axis=0)))
            md.append(encode(np.nanmedian(arr, axis=0)))
        nobs.append(np.isfinite(arr).sum(axis=0).clip(0, 255).astype("uint8"))
        months.append(pd.Timestamp(f"{dates[0].year}-{m:02d}-15"))
ds = xr.Dataset({"ndvi_max": (("time", "y", "x"), np.stack(mx)), "ndvi_median": (("time", "y", "x"), np.stack(md)),
                 "nobs": (("time", "y", "x"), np.stack(nobs))}, coords={"time": months, "y": Y, "x": X})
for v in ("ndvi_max", "ndvi_median"):
    ds[v].attrs = {"encoding": "ndvi = (v - 1) / 200 - 0.25; 0 = no data", "long_name": f"monthly {v[5:]} HLS NDVI"}
ds["nobs"].attrs = {"long_name": "clear HLS observation days in the month"}
ds.attrs = {"crs": CRS, "resolution_m": RES, "source": "NASA HLS v2.0 L30 + S30 via Microsoft Planetary Computer",
            "nir_band": "L30 B05, S30 B8A"}
out = PROC / "hls_ndvi_monthly_30m.nc"
ds.to_netcdf(out, encoding={v: {"zlib": True, "complevel": 5} for v in ds.data_vars})
print(out, f"{out.stat().st_size / 1e6:.1f} MB", dict(ds.sizes))
