"""Download one explicitly selected FAO GAEZ v4 suitability GeoTIFF.

The crop, water regime, management, climate period and particular raster must
be selected from the OFFICIAL FAO GAEZ v4 portal/repository. This script does
not guess a raster path, infer a crop suitability score, or scrape the portal.

Accepted origins: FAO's GAEZ v4 repository, and its documented S3 bucket:
    https://gaez-v4-data.fao.org/data/...
    https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/res05/...

Example after copying the actual suitability-index .tif URL from FAO:
    uv run python -m agrisim.data_sources.download_gaez_official \
      --url "https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/res05/.../su..._whe.tif" \
      --crop wheat --scenario rainfed_low_input_historical --kind suitability-index
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests
import rasterio

from agrisim.config import RAW, SOWING_LAT, SOWING_LON
from rasterio.warp import transform


ALLOWED_DOMAINS = {"gaez-v4-data.fao.org", "s3.eu-west-1.amazonaws.com"}
OFFICIAL_S3_PREFIX = "/data.gaezdev.aws.fao.org/res05/"


def validate_url(url: str, kind: str) -> str:
    p = urlparse(url)
    if p.scheme != "https" or p.hostname not in ALLOWED_DOMAINS:
        raise ValueError("Only FAO GAEZ v4 repository links and FAO's documented S3 bucket are allowed")
    if p.username or p.password or p.query or p.fragment or p.port:
        raise ValueError("FAO direct raster URLs must not have credentials, query parameters or ports")
    if p.hostname == "s3.eu-west-1.amazonaws.com":
        if not p.path.startswith(OFFICIAL_S3_PREFIX):
            raise ValueError("Unexpected S3 bucket/prefix: not FAO GAEZ v4 res05")
    elif not p.path.startswith("/data/res05/"):
        raise ValueError("Expected an official FAO GAEZ v4 suitability/attainable-yield raster (res05)")
    filename = Path(unquote(p.path)).name
    if not filename.lower().endswith((".tif", ".tiff")):
        raise ValueError("Select the direct .tif URL (not a portal page or an archive)")
    # Official FAO GAEZ v4 res05 codebook:
    #   su = continuous suitability index (0–10000), current cropland
    #   sx = continuous suitability index (0–10000), all land
    #   sc = suitability class, current cropland
    #   si = suitability class, all land
    #   sx1/sx2/sx3 represent shares of suitable land, NOT index rasters.
    code = filename[:2].lower()
    if kind == "suitability-index":
        if code not in {"su", "sx"} or filename[:3].lower() in {"sx1", "sx2", "sx3"}:
            raise ValueError("Expected a FAO GAEZ v4 suitability-index raster (su...tif or sx...tif)")
    elif kind == "suitability-class" and code not in {"sc", "si"}:
        raise ValueError("Expected a FAO GAEZ v4 suitability-class raster (sc...tif or si...tif)")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", filename):
        raise ValueError("Unexpected GeoTIFF filename")
    return filename


def point_sample(path: Path, lat: float, lon: float):
    with rasterio.open(path) as src:
        if src.count < 1 or src.crs is None:
            raise ValueError("Downloaded GAEZ raster has no bands or CRS")
        x, y = transform("EPSG:4326", src.crs, [lon], [lat])
        if not (src.bounds.left <= x[0] <= src.bounds.right
                and src.bounds.bottom <= y[0] <= src.bounds.top):
            raise ValueError("Downloaded GAEZ raster does not cover North Evia")
        values = next(src.sample([(x[0], y[0])], masked=True))
        return {
            "crs": str(src.crs),
            "resolution": list(src.res),
            "bands": src.count,
            "pilot_value_raw": None if values.mask.any() else [float(v) for v in values],
            "nodata": src.nodata,
        }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True, help="Real direct .tif URL copied from FAO GAEZ v4")
    p.add_argument("--crop", required=True, help="FAO crop for the chosen raster")
    p.add_argument("--scenario", required=True, help="Exact FAO water/input/climate scenario")
    p.add_argument("--kind", choices=["suitability-index", "suitability-class"],
                   default="suitability-index")
    p.add_argument("--plan", action="store_true", help="Validate URL; do not download")
    args = p.parse_args(argv)
    filename = validate_url(args.url, args.kind)
    slug = lambda value: re.sub(r"[^a-z0-9_-]+", "_", value.lower())[:80]
    out = RAW / "fao_gaez" / f"{slug(args.crop)}_{slug(args.scenario)}_{filename}"
    print(f"GAEZ v4 {args.kind}: {filename}")
    print(f"Destination: {out}")
    if args.plan:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        tmp = out.with_name(out.name + ".partial")
        try:
            with requests.get(args.url, stream=True, allow_redirects=False,
                              timeout=(20, 180)) as response:
                response.raise_for_status()
                if 300 <= response.status_code < 400:
                    raise ValueError("Unexpected redirect; use the FAO direct raster URL")
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            if tmp.stat().st_size < 128:
                raise ValueError("Downloaded object is unexpectedly small")
            details = point_sample(tmp, SOWING_LAT, SOWING_LON)
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        details = point_sample(out, SOWING_LAT, SOWING_LON)

    manifest = {
        "source": "FAO GAEZ v4", "url": args.url, "crop": args.crop,
        "scenario": args.scenario, "kind": args.kind,
        "download_utc": datetime.now(timezone.utc).isoformat(),
        "site": {"id": "evia_pilot", "lat": SOWING_LAT, "lon": SOWING_LON},
        **details,
        "warning": "Raw raster value is not an interpreted suitability score: consult the exact FAO codebook.",
    }
    out.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("FAO GAEZ raster verified:", out)
    print("Raw pilot pixel:", details["pilot_value_raw"])
    print("Do not infer agronomic suitability without the correct layer legend.")


if __name__ == "__main__":
    main()
