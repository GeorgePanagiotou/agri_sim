"""Download a small ESA Copernicus Sentinel-2 L2A reflectance window at 10 m.

Uses ONLY ESA Copernicus Data Space Sentinel Hub Process API (official ESA
partner resource). Requires a personal CDSE account + OAuth client credentials:
    CDSE_CLIENT_ID, CDSE_CLIENT_SECRET (environment variables, never committed).

One output TIFF contains five float32 bands: B03 green, B04 red, B08 NIR,
SCL scene classification and dataMask. NDVI/EVI2 can be calculated locally.

Examples:
    python data_prep/download_sentinel2.py --date 2024-12-08
    python data_prep/download_sentinel2.py --start 2024-11-01 --end 2024-11-05 --size-m 1200

A multi-day window is an ESA least-cloudy MOSAIC; it is not a single dated
observation. Use --date for per-day time series. SCL is NOT a crop label.
"""
import argparse
import json
import os
from datetime import date
from pathlib import Path

import requests
from pyproj import Transformer

try:
    from .config import RAW, SOWING_LAT, SOWING_LON
except ImportError:
    from .config import RAW, SOWING_LAT, SOWING_LON

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
BAND_ORDER = ["B03_green", "B04_red", "B08_nir", "SCL", "dataMask"]
EVALSCRIPT = r"""//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B03", "B04", "B08", "SCL", "dataMask"],
              units: ["REFLECTANCE", "REFLECTANCE", "REFLECTANCE", "DN", "DN"] }],
    output: { id: "default", bands: 5, sampleType: "FLOAT32" }
  };
}
function evaluatePixel(s) { return [s.B03, s.B04, s.B08, s.SCL, s.dataMask]; }
"""


def bounds_utm(lon, lat, width_m):
    """Create metric bounding square in the native UTM CRS of Northern Evia."""
    crs = "EPSG:32634"
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    half = width_m / 2
    return [x - half, y - half, x + half, y + half], crs


def payload(lon, lat, start, end, size_m, resolution, max_cloud):
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("start date must be <= end date")
    if size_m <= 0 or resolution != 10 or size_m % resolution:
        raise ValueError("size-m must be a positive multiple of 10 m")
    size_px = int(size_m // resolution)
    if size_px > 2500:
        raise ValueError("A single ESA request cannot exceed 2500 x 2500 pixels")
    bbox, crs = bounds_utm(lon, lat, size_m)
    code = crs.split(":")[-1]
    return {
        "input": {"bounds": {"bbox": bbox, "properties": {"crs": f"http://www.opengis.net/def/crs/EPSG/0/{code}"}},
                  "data": [{"type": "sentinel-2-l2a", "dataFilter": {
                      "timeRange": {"from": start + "T00:00:00Z", "to": end + "T23:59:59Z"},
                      "maxCloudCoverage": max_cloud, "mosaickingOrder": "leastCC",
                  }}]},
        "output": {"width": size_px, "height": size_px,
                   "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": EVALSCRIPT,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    date_group = ap.add_mutually_exclusive_group()
    date_group.add_argument("--date", help="A single UTC acquisition day (YYYY-MM-DD)")
    date_group.add_argument("--start", default="2024-12-08", help="UTC start day")
    ap.add_argument("--end", help="UTC end day; defaults to --start")
    ap.add_argument("--site", default="evia_pilot", help="Field/site ID matching the HLS field_id")
    ap.add_argument("--lon", type=float, default=SOWING_LON)
    ap.add_argument("--lat", type=float, default=SOWING_LAT)
    ap.add_argument("--size-m", type=int, default=990, help="Square size at 10 m (default 990)")
    ap.add_argument("--max-cloud", type=int, default=30)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)
    if not 0 <= args.max_cloud <= 100:
        ap.error("--max-cloud must be 0..100")
    start = args.date or args.start
    end = args.date or args.end or start
    request_json = payload(args.lon, args.lat, start, end, args.size_m, 10, args.max_cloud)
    stem = f"s2_l2a_{args.lon:.5f}_{args.lat:.5f}_{start}_{end}_{args.size_m}m".replace("-", "_")
    folder = RAW / "sentinel2"
    folder.mkdir(parents=True, exist_ok=True)
    tif = folder / f"{stem}.tif"
    manifest = folder / f"{stem}.json"
    if tif.exists() and not args.overwrite:
        print(f"Cached ESA image: {tif}")
        return
    client = os.getenv("CDSE_CLIENT_ID")
    secret = os.getenv("CDSE_CLIENT_SECRET")
    if not client or not secret:
        raise SystemExit("CDSE_CLIENT_ID and CDSE_CLIENT_SECRET environment variables are required")
    with requests.Session() as s:
        auth = s.post(TOKEN_URL, data={"grant_type": "client_credentials", "client_id": client,
                                            "client_secret": secret}, timeout=(20, 90))
        auth.raise_for_status()
        token = auth.json()["access_token"]
        r = s.post(PROCESS_URL, json=request_json, headers={"Authorization": f"Bearer {token}",
                        "Accept": "image/tiff"}, timeout=(30, 240), stream=True)
        r.raise_for_status()
        tmp = tif.with_suffix(".tif.part")
        with tmp.open("wb") as out:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    out.write(chunk)
        # Confirm actual image data, rather than accidentally keeping an error HTML page.
        import rasterio
        with rasterio.open(tmp) as src:
            if src.count != len(BAND_ORDER) or src.width != args.size_m // 10 or src.height != args.size_m // 10:
                raise RuntimeError("ESA Sentinel-2 response has unexpected band count or dimensions")
        tmp.replace(tif)
    # Never write the OAuth bearer token or the client secret to disk.
    manifest.write_text(json.dumps({
        "source": "ESA Copernicus Sentinel-2 L2A via Copernicus Data Space Sentinel Hub Process API",
        "dataset": "sentinel-2-l2a", "field_id": args.site, "access_endpoint": PROCESS_URL,
        "start_utc": start, "end_utc": end,
        "is_temporal_mosaic": start != end,
        "band_order": BAND_ORDER,
        "reflectance_units": "unitless surface reflectance, bands 1–3",
        "quality_bands": {"SCL": 4, "dataMask": 5},
        "bbox_utm": request_json["input"]["bounds"]["bbox"],
        "crs": request_json["input"]["bounds"]["properties"]["crs"],
        "size_m": args.size_m, "resolution_m": 10,
        "max_scene_cloud_percent": args.max_cloud,
    }, indent=2), encoding="utf-8")
    print(f"ESA Sentinel-2 L2A: {tif}\nMetadata: {manifest}")


if __name__ == "__main__":
    main()
