"""Landsat 4/5/7/8/9 Collection 2 Level-2 NDVI history of the study area, 1984 onwards -> monthly median NDVI cube.

No full scenes are downloaded: for each scene only the study-area window of red, NIR and QA_PIXEL is read from the
Cloud-Optimized GeoTIFFs on Microsoft Planetary Computer (public, anonymous SAS token), warped to one fixed 30 m UTM 34N
grid. Clouds, shadows, snow and fill (incl. Landsat 7 SLC-off gaps) are masked with QA_PIXEL.

Outputs
- data/raw/landsat_ndvi/<year>.npz   per-year monthly medians (resume: years already done are skipped)
- data/processed/landsat_scenes.csv  every scene used: id, date, platform, cloud cover, valid share in the area
- data/processed/landsat_ndvi_monthly_30m.nc  NDVI(time, y, x) as uint8 (0 = no data; ndvi = (v - 1) / 200 - 0.25)

    python data_prep/landsat_ndvi_history.py --first-year 2023 --last-year 2024
"""
import json
import os
import argparse
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".TIF,.tif")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")

import numpy as np
import pandas as pd
import planetary_computer as pc
import pystac_client
import rasterio
import xarray as xr
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, transform_bounds

try:
    from .config import CRS, PROC, RAW, STUDY_AREA
except ImportError:
    from .config import CRS, PROC, RAW, STUDY_AREA

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--first-year", type=int, default=2023)
p.add_argument("--last-year", type=int, default=2024)
p.add_argument("--max-cloud", type=int, default=70)
args = p.parse_args()
if args.last_year < args.first_year:
    p.error("last-year must not be earlier than first-year")
FIRST, LAST = args.first_year, args.last_year
MAX_CLOUD = args.max_cloud  # scene-level; the per-pixel QA mask does the real work
RES = 30.0
w, s, e, n = transform_bounds("EPSG:4326", CRS, STUDY_AREA[0], STUDY_AREA[2], STUDY_AREA[1], STUDY_AREA[3])
X0, Y1 = np.floor(w / RES) * RES, np.ceil(n / RES) * RES
WIDTH, HEIGHT = int(np.ceil((e - X0) / RES)), int(np.ceil((Y1 - s) / RES))
TRANSFORM = from_origin(X0, Y1, RES, RES)
OUT_YEARS = RAW / "landsat_ndvi"
OUT_YEARS.mkdir(parents=True, exist_ok=True)
SCENES_CSV = PROC / "landsat_scenes.csv"

# QA_PIXEL bits: 0 fill, 1 dilated cloud, 2 cirrus (L8/9), 3 cloud, 4 cloud shadow, 5 snow
BAD = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5)


def read(href, resampling):
    with rasterio.open(pc.sign(href)) as src, WarpedVRT(src, crs=CRS, transform=TRANSFORM, width=WIDTH,
                                                        height=HEIGHT, resampling=resampling) as vrt:
        return vrt.read(1)


def scene_ndvi(item):
    a = item.assets
    try:
        qa = read(a["qa_pixel"].href, Resampling.nearest)
        red = read(a["red"].href, Resampling.bilinear).astype("float32") * 2.75e-5 - 0.2
        nir = read(a["nir08"].href, Resampling.bilinear).astype("float32") * 2.75e-5 - 0.2
    except Exception as exc:  # a broken asset must not stop the run
        return item, None, f"{type(exc).__name__}: {str(exc)[:120]}"
    ok = ((qa & BAD) == 0) & (qa != 0) & (red > 0) & (nir > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = np.where(ok, (nir - red) / (nir + red), np.nan).astype("float32")
    ndvi += OFFSET.get(item.properties.get("platform"), 0.0)  # harmonize to Landsat 8 (landsat_harmonize.py)
    return item, ndvi, None


def encode(ndvi):
    v = np.clip(np.round((ndvi + 0.25) * 200) + 1, 1, 255)
    return np.where(np.isfinite(ndvi), v, 0).astype("uint8")


HARM = PROC / "landsat_ndvi_harmonization.json"
OFFSET = json.load(open(HARM))["offset_to_landsat8"] if HARM.exists() else {}
print("NDVI offsets to Landsat 8:", OFFSET or "none (run landsat_harmonize.py first)")
catalog = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
rows = pd.read_csv(SCENES_CSV).to_dict("records") if SCENES_CSV.exists() else []
rows = [r for r in rows if not (FIRST <= int(str(r["date"])[:4]) <= LAST)]  # redo the years in this run's range
for year in range(FIRST, LAST + 1):
    target = OUT_YEARS / f"{year}.npz"
    if target.exists():
        print(year, "exists, skipping")
        rows += pd.read_csv(OUT_YEARS / f"{year}_scenes.csv").to_dict("records")
        continue
    items = list(catalog.search(collections=["landsat-c2-l2"], bbox=[STUDY_AREA[0], STUDY_AREA[2], STUDY_AREA[1],
                                                                       STUDY_AREA[3]],
                                datetime=f"{year}-01-01/{year}-12-31",
                                query={"eo:cloud_cover": {"lt": MAX_CLOUD}}).items())
    by_month = {m: [] for m in range(1, 13)}
    year_rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for item, ndvi, err in pool.map(scene_ndvi, items):
            p = item.properties
            valid = 0.0 if ndvi is None else float(np.isfinite(ndvi).mean())
            year_rows.append({"id": item.id, "date": p["datetime"][:10], "platform": p.get("platform"),
                              "wrs": f'{p.get("landsat:wrs_path")}/{p.get("landsat:wrs_row")}',
                              "cloud_cover": p.get("eo:cloud_cover"), "valid_share": round(valid, 3),
                              "error": err or ""})
            if ndvi is not None and valid > 0.02:
                by_month[int(p["datetime"][5:7])].append(ndvi)
    cube = np.zeros((12, HEIGHT, WIDTH), dtype="uint8")
    nobs = np.zeros((12, HEIGHT, WIDTH), dtype="uint8")
    for m, stack in by_month.items():
        if stack:
            arr = np.stack(stack)
            with np.errstate(all="ignore"):
                cube[m - 1] = encode(np.nanmedian(arr, axis=0))
            nobs[m - 1] = np.isfinite(arr).sum(axis=0).clip(0, 255)
    np.savez_compressed(target, ndvi=cube, nobs=nobs)
    pd.DataFrame(year_rows).to_csv(OUT_YEARS / f"{year}_scenes.csv", index=False)
    rows += year_rows
    used = sum(1 for r in year_rows if r["valid_share"] > 0.02)
    months = sum(1 for v in by_month.values() if v)
    print(f"{year}: {len(items)} scenes found, {used} used, {months} months with data", flush=True)

pd.DataFrame(rows).sort_values("date").to_csv(SCENES_CSV, index=False)

# assemble everything on disk into one cube
years = sorted(int(p.stem) for p in OUT_YEARS.glob("*.npz"))
ndvi = np.concatenate([np.load(OUT_YEARS / f"{y}.npz")["ndvi"] for y in years])
nobs = np.concatenate([np.load(OUT_YEARS / f"{y}.npz")["nobs"] for y in years])
time = pd.to_datetime([f"{y}-{m:02d}-15" for y in years for m in range(1, 13)])
x = X0 + RES * (np.arange(WIDTH) + 0.5)
y = Y1 - RES * (np.arange(HEIGHT) + 0.5)
ds = xr.Dataset({"ndvi": (("time", "y", "x"), ndvi), "nobs": (("time", "y", "x"), nobs)},
                coords={"time": time, "y": y, "x": x})
ds["ndvi"].attrs = {"long_name": "monthly median Landsat NDVI" + (", harmonized to Landsat 8" if OFFSET else ", no cross-sensor offsets applied"), "encoding": "ndvi = (v - 1) / 200 - 0.25; 0 = no data"}
ds["nobs"].attrs = {"long_name": "clear Landsat observations in the month"}
ds.attrs = {"crs": CRS, "resolution_m": RES, "source": "Landsat Collection 2 Level-2 (USGS/NASA) via Microsoft "
            "Planetary Computer", "area": f"study area {STUDY_AREA}"}
out = PROC / "landsat_ndvi_monthly_30m.nc"
ds.to_netcdf(out, encoding={v: {"zlib": True, "complevel": 5} for v in ("ndvi", "nobs")})
print(out, f"{out.stat().st_size / 1e6:.1f} MB", ds.sizes)
