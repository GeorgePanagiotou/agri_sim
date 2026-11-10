"""Download native HLSL30 v2 windows for the Evia sowing pilot from the NASA data mirror.

The raw cache contains only cropped windows. Outputs contain one observation per
UTC day, the unmodified quality byte, and scaled B03/B04/B05 reflectance.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from urllib.parse import urlsplit

import certifi
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.warp import transform
from rasterio.windows import Window

from config import PROC, RAW, SOWING_LAT, SOWING_LON, SOWING_SEASONS

API = "https://planetarycomputer.microsoft.com/api"
BANDS = ("B03", "B04", "B05", "Fmask")
SIZE = 33
RAW_CLIPS = RAW / "evia_sowing" / "hls"
OUT = PROC / "evia_sowing" / "hls"


def catalog():
    by_id = {}
    for start, end in SOWING_SEASONS:
        params = {"collections": "hls2-l30", "limit": 250,
                  "bbox": f"{SOWING_LON-.00001},{SOWING_LAT-.00001},{SOWING_LON+.00001},{SOWING_LAT+.00001}",
                  "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z"}
        url = f"{API}/stac/v1/search"
        while url:
            response = requests.get(url, params=params, timeout=45)
            response.raise_for_status()
            page = response.json()
            for feature in page["features"]:
                by_id[feature["id"]] = feature
            url = next((link["href"] for link in page["links"] if link["rel"] == "next"), None)
            params = None
    if not by_id:
        raise RuntimeError("No HLSL30 granules found.")
    return sorted(by_id.values(), key=lambda f: f["id"])


def storage(href):
    url = urlsplit(href)
    return url.hostname.split(".")[0], url.path.split("/")[1]


def download_clip(feature, tokens):
    scene = feature["id"]
    target = RAW_CLIPS / f"{scene}.tif"
    if target.exists():
        return target
    for attempt in range(3):
        try:
            arrays = []
            grid = None
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CURL_CA_BUNDLE=certifi.where(),
                              GDAL_HTTP_CONNECTTIMEOUT="15", GDAL_HTTP_TIMEOUT="45",
                              GDAL_HTTP_MAX_RETRY="2", GDAL_HTTP_RETRY_DELAY="1", CPL_LOG="NUL"):
                for name in BANDS:
                    href = feature["assets"][name]["href"].split("?")[0]
                    with rasterio.open(href + "?" + tokens[storage(href)]) as src:
                        x, y = transform("EPSG:4326", src.crs, [SOWING_LON], [SOWING_LAT])
                        row, col = src.index(x[0], y[0])
                        win = Window(col-SIZE//2, row-SIZE//2, SIZE, SIZE)
                        transform_out = src.window_transform(win)
                        if not np.allclose(src.res, (30, 30)):
                            raise ValueError("Expected a native 30 m raster")
                        current = (src.crs, transform_out)
                        if grid is not None and current != grid:
                            raise ValueError("HLS band grids differ")
                        grid = current
                        fill = 255 if name == "Fmask" else -9999
                        arrays.append(src.read(1, window=win, boundless=True, fill_value=fill).astype("int16"))
            tmp = target.with_suffix(".partial.tif")
            with rasterio.open(tmp, "w", driver="GTiff", count=4, dtype="int16", width=SIZE, height=SIZE,
                               crs=grid[0], transform=grid[1], compress="deflate") as ds:
                ds.write(np.stack(arrays))
                ds.descriptions = BANDS
                ds.update_tags(granule=scene, scale_B03_B04_B05="0.0001", fill_reflectance="-9999", fill_Fmask="255")
            tmp.replace(target)
            return target
        except (rasterio.errors.RasterioIOError, requests.RequestException) as err:
            if attempt == 2:
                # Signed storage query strings must never be written to logs.
                raise RuntimeError(f"Failed to read the window for {scene} ({type(err).__name__})") from None
            time.sleep(2 ** attempt)


def prepare(features):
    roi = np.zeros((SIZE, SIZE), dtype=bool)
    centre = SIZE // 2
    roi[centre-1:centre+2, centre-1:centre+2] = True
    rows, scenes = [], {}
    grid = None
    for f in features:
        scene = f["id"]
        with rasterio.open(RAW_CLIPS / f"{scene}.tif") as ds:
            if ds.descriptions != BANDS or ds.shape != (SIZE, SIZE):
                raise ValueError(f"Unexpected clip layout: {scene}")
            current = (ds.crs.to_string(), tuple(ds.transform)[:6])
            if grid is not None and current != grid:
                raise ValueError(f"Different grids at the pilot point: {scene}")
            grid = current
            raw = ds.read()
        qa = raw[3].astype("uint8")
        # Fmask bits 1–5 = cloud, adjacent cloud, shadow, snow/ice, water.
        # A conservative extra filter excludes high aerosol (bits 6–7 both set).
        clear = (qa != 255) & ((qa & 62) == 0) & ((qa >> 6) != 3) & (raw[:3] != -9999).all(axis=0)
        reflectance = raw[:3].astype("float32") * np.float32(0.0001)
        reflectance[:, ~clear] = np.nan
        scenes[scene] = (reflectance, qa, clear)
        properties = f["properties"]
        date = properties["datetime"][:10]
        year = int(date[:4]) if int(date[5:7]) >= 9 else int(date[:4])-1
        red, nir = reflectance[1], reflectance[2]
        valid_ndvi = roi & clear & ((nir + red) > 0)
        ndvi = ((nir[valid_ndvi] - red[valid_ndvi]) / (nir[valid_ndvi] + red[valid_ndvi]))
        row = {"date_utc": date, "acquired_utc": properties["datetime"], "season": f"{year}-{year+1}",
               "granule": scene, "tile": scene.split(".")[2], "platform": properties.get("platform"),
               "candidate_clear_pixels": int((roi & clear).sum()), "candidate_pixels": int(roi.sum()),
               "context_clear_pixels": int(clear.sum()), "candidate_median_ndvi": float(np.median(ndvi)) if ndvi.size else np.nan,
               "source_stac": f"{API}/stac/v1/collections/hls2-l30/items/{scene}"}
        rows.append(row)
    manifest = pd.DataFrame(rows).sort_values(["date_utc", "candidate_clear_pixels", "context_clear_pixels", "granule"],
                                               ascending=[True, False, False, True]).reset_index(drop=True)
    manifest["selected"] = ~manifest.date_utc.duplicated()
    manifest["array_index"] = pd.Series(pd.NA, index=manifest.index, dtype="Int64")
    manifest.loc[manifest.selected, "array_index"] = np.arange(int(manifest.selected.sum()))
    chosen = manifest[manifest.selected]
    ids = chosen.granule.tolist()
    temp = OUT / "field_context.partial.npz"
    np.savez_compressed(temp, reflectance=np.stack([scenes[k][0] for k in ids]),
                        fmask=np.stack([scenes[k][1] for k in ids]), clear=np.stack([scenes[k][2] for k in ids]),
                        candidate_mask=roi, dates=chosen.date_utc.to_numpy(dtype="U10"), granules=np.array(ids),
                        bands=np.array(BANDS[:3]), crs=grid[0], transform=grid[1],
                        longitude=SOWING_LON, latitude=SOWING_LAT)
    temp.replace(OUT / "field_context.npz")
    manifest.to_csv(OUT / "acquisitions.csv", index=False, float_format="%.6f")
    labels = chosen[["array_index", "date_utc", "season", "granule", "candidate_clear_pixels", "candidate_pixels"]].copy()
    labels.insert(1, "field_id", "evia_pilot")
    for col in ("farm_id", "crop_id", "sown_on", "label", "evidence", "split"):
        labels[col] = ""
    labels.to_csv(OUT / "labels_template.csv", index=False)
    print(chosen.groupby("season").agg(dates=("granule","size"), full_clear=("candidate_clear_pixels",lambda x:(x==9).sum()),
                                       some_clear=("candidate_clear_pixels",lambda x:(x>0).sum())).to_string(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=5, choices=range(1, 9))
    args = parser.parse_args()
    RAW_CLIPS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    features = catalog()
    print(f"Found {len(features)} native tile records for both seasons.", flush=True)
    tokens = {}
    for account, container in {storage(f["assets"]["B03"]["href"]) for f in features}:
        resp = requests.get(f"{API}/sas/v1/token/{account}/{container}", timeout=35)
        resp.raise_for_status()
        tokens[account, container] = resp.json()["token"].lstrip("?")
    with ThreadPoolExecutor(args.workers) as pool:
        for i, _ in enumerate(pool.map(lambda f: download_clip(f, tokens), features), 1):
            if i % 10 == 0 or i == len(features):
                print(f"Cached {i}/{len(features)} windows", flush=True)
    prepare(features)


if __name__ == "__main__":
    main()
