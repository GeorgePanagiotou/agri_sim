"""Download single-date ESA Sentinel-2 L2A windows for the Evia pilot from the Microsoft Planetary Computer mirror.

Same product (ESA Copernicus Sentinel-2 Level-2A) and the SAME output format as download_sentinel2.py (CDSE Process
API), so preprocessing/sentinel2_aligned.py reads both: a 990 m square at 10 m in the area's UTM grid centred on the pilot,
five float32 bands B03_green, B04_red, B08_nir (surface reflectance, unitless), SCL, dataMask, plus a JSON manifest.
No account is needed (Planetary Computer issues short-lived read tokens).

Reflectance harmonization: from processing baseline 04.00 (25 Jan 2022) ESA adds BOA_ADD_OFFSET = -1000 to the
digital numbers. Reflectance = (DN - 1000) / 10000 for baseline >= 04.00, DN / 10000 before; negative values clipped
to 0 and DN = 0 treated as no data, as the Sentinel Hub "harmonizeValues" default does. SCL (20 m) is resampled to
10 m by nearest neighbour.

    python -m agrisim.data_sources.download_sentinel2_pc --plan
    python -m agrisim.data_sources.download_sentinel2_pc --max-cloud 40 --workers 4
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import certifi
import numpy as np
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from pyproj import Transformer
from shapely.geometry import Polygon, shape

from .config import RAW, SOWING_LAT, SOWING_LON, SOWING_SEASONS
from .download_sentinel2 import BAND_ORDER, bounds_utm

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
ASSETS = ("B03", "B04", "B08", "SCL")
OUT = RAW / "sentinel2"
RES = 10


def harmonize(dn: np.ndarray, baseline: float) -> np.ndarray:
    """Digital numbers -> unitless surface reflectance (Sentinel Hub harmonized convention)."""
    offset = -1000.0 if baseline >= 4.0 else 0.0
    refl = (dn.astype("float32") + offset) / 10000.0
    refl = np.clip(refl, 0, None)
    refl[dn == 0] = 0.0
    return refl


def window_geometry(lon: float, lat: float, size_m: int):
    bbox, crs = bounds_utm(lon, lat, size_m)
    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    xs, ys = to_wgs([bbox[0], bbox[2], bbox[2], bbox[0]], [bbox[1], bbox[1], bbox[3], bbox[3]])
    return bbox, crs, Polygon(zip(xs, ys))


def select_items(items, window_wgs84) -> list:
    """One item per UTC date: footprint must contain the whole window; then lowest scene cloud, then ID."""
    by_date = {}
    for item in items:
        if not shape(item.geometry).contains(window_wgs84):
            continue
        day = item.properties["datetime"][:10]
        key = (item.properties.get("eo:cloud_cover", 101), item.id)
        if day not in by_date or key < by_date[day][0]:
            by_date[day] = (key, item)
    return [by_date[d][1] for d in sorted(by_date)]


def catalogue(lon, lat, size_m, seasons, max_cloud):
    _, _, window = window_geometry(lon, lat, size_m)
    client = pystac_client.Client.open(STAC)
    items = []
    for start, end in seasons:
        search = client.search(collections=[COLLECTION], intersects=window.__geo_interface__,
                               datetime=f"{start}T00:00:00Z/{end}T23:59:59Z",
                               query={"eo:cloud_cover": {"lte": max_cloud}})
        items.extend(search.items())
    return select_items(items, window)


def stem(lon, lat, day, size_m):
    return f"s2_l2a_{lon:.5f}_{lat:.5f}_{day}_{day}_{size_m}m".replace("-", "_")


def download(item, lon, lat, size_m, site):
    day = item.properties["datetime"][:10]
    tif = OUT / f"{stem(lon, lat, day, size_m)}.tif"
    if tif.exists() and tif.with_suffix(".json").exists():
        return tif, "cached"
    bbox, crs = bounds_utm(lon, lat, size_m)
    n = size_m // RES
    transform = from_origin(bbox[0], bbox[3], RES, RES)
    baseline = float(item.properties.get("s2:processing_baseline", "0"))
    for attempt in range(4):
        try:
            signed = planetary_computer.sign(item)
            raw = {}
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CURL_CA_BUNDLE=certifi.where(),
                              GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2", CPL_LOG="NUL"):
                for name in ASSETS:
                    with rasterio.open(signed.assets[name].href) as src, WarpedVRT(
                            src, crs=crs, transform=transform, width=n, height=n,
                            resampling=Resampling.nearest, src_nodata=0, nodata=0) as vrt:
                        raw[name] = vrt.read(1)
            break
        except rasterio.errors.RasterioIOError as err:
            if attempt == 3:
                raise RuntimeError(f"{item.id}: {type(err).__name__}") from None
            time.sleep(2 ** attempt)
    valid = np.logical_and.reduce([raw[b] > 0 for b in ASSETS])
    bands = [harmonize(raw[b], baseline) for b in ("B03", "B04", "B08")]
    bands += [raw["SCL"].astype("float32"), valid.astype("float32")]
    tmp = tif.with_suffix(".partial.tif")
    with rasterio.open(tmp, "w", driver="GTiff", count=5, dtype="float32", width=n, height=n,
                       crs=crs, transform=transform, compress="deflate") as ds:
        ds.write(np.stack(bands))
        ds.descriptions = tuple(BAND_ORDER)
    tmp.replace(tif)
    tif.with_suffix(".json").write_text(json.dumps({
        "source": "ESA Copernicus Sentinel-2 L2A via Microsoft Planetary Computer (mirror of the ESA product)",
        "dataset": "sentinel-2-l2a", "field_id": site, "access_endpoint": STAC,
        "stac_item": f"{STAC}/collections/{COLLECTION}/items/{item.id}", "scene_id": item.id,
        "start_utc": day, "end_utc": day, "acquired_utc": item.properties["datetime"],
        "is_temporal_mosaic": False, "band_order": BAND_ORDER,
        "reflectance_units": "unitless surface reflectance, bands 1-3",
        "processing_baseline": item.properties.get("s2:processing_baseline"),
        "boa_offset_applied": -1000 if baseline >= 4.0 else 0,
        "quality_bands": {"SCL": 4, "dataMask": 5}, "scl_resampling": "nearest 20 m -> 10 m",
        "bbox_utm": bbox, "crs": f"http://www.opengis.net/def/crs/EPSG/0/{crs.split(':')[-1]}",
        "size_m": size_m, "resolution_m": RES,
        "scene_cloud_percent": item.properties.get("eo:cloud_cover"),
        "mgrs_tile": item.properties.get("s2:mgrs_tile"),
        "valid_fraction": float(valid.mean()),
    }, indent=2), encoding="utf-8")
    return tif, "downloaded"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--site", default="evia_pilot")
    p.add_argument("--lon", type=float, default=SOWING_LON)
    p.add_argument("--lat", type=float, default=SOWING_LAT)
    p.add_argument("--size-m", type=int, default=990)
    p.add_argument("--max-cloud", type=int, default=40, help="Scene cloud cover limit, percent")
    p.add_argument("--start", help="Restrict to one window (default: config SOWING_SEASONS)")
    p.add_argument("--end")
    p.add_argument("--workers", type=int, default=4, choices=range(1, 9))
    p.add_argument("--plan", action="store_true", help="List the selected dates only")
    a = p.parse_args(argv)
    seasons = [(a.start, a.end)] if a.start and a.end else list(SOWING_SEASONS)
    items = catalogue(a.lon, a.lat, a.size_m, seasons, a.max_cloud)
    for start, end in seasons:
        n = sum(start <= i.properties["datetime"][:10] <= end for i in items)
        print(f"{start} .. {end}: {n} dates (scene cloud <= {a.max_cloud} %)", flush=True)
    if a.plan:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    def safe(it):
        try:
            return download(it, a.lon, a.lat, a.size_m, a.site)
        except RuntimeError as err:   # one unreadable scene must not stop the series; re-run to retry
            return None, str(err)

    done, failed = 0, []
    with ThreadPoolExecutor(a.workers) as pool:
        for tif, status in pool.map(safe, items):
            done += 1
            if tif is None:
                failed.append(status)
            if done % 25 == 0 or done == len(items):
                print(f"{done}/{len(items)} dates processed, {len(failed)} failed", flush=True)
    print(f"Sentinel-2 L2A windows in {OUT}")
    if failed:
        print("Failed (re-run to retry):\n  " + "\n  ".join(failed))


if __name__ == "__main__":
    main()
