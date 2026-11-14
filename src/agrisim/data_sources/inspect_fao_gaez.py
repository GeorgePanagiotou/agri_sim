"""Inspect downloaded official FAO GAEZ rasters; do not invent suitability scores.

Prerequisite: select a crop/regime/layer and use existing download_fao_gaez
with a real direct FAO-hosted GeoTIFF URL obtained from the official portal.

uv run python -m agrisim.data_sources.inspect_fao_gaez \
  --raster data/raw/fao_gaez/your_actual_layer.tif
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform

from agrisim.config import SOWING_LAT, SOWING_LON


def inspect(path: Path, latitude: float, longitude: float):
    with rasterio.open(path) as raster:
        if raster.crs is None:
            raise ValueError("FAO raster lacks a CRS; cannot locate Evia")
        xx, yy = transform("EPSG:4326", raster.crs, [longitude], [latitude])
        x, y = xx[0], yy[0]
        inside = (raster.bounds.left <= x <= raster.bounds.right and
                  raster.bounds.bottom <= y <= raster.bounds.top)
        if not inside:
            raise ValueError("Selected FAO raster does not cover Evia")
        pixel = next(raster.sample([(x, y)], masked=True))
        if np.any(np.ma.getmaskarray(pixel)):
            raise ValueError("FAO raster has no valid value at pilot centre")
        pixel = np.asarray(pixel)
        if (raster.nodata is not None and np.any(pixel == raster.nodata)) or not np.isfinite(pixel).all():
            raise ValueError("FAO raster contains nodata/invalid values at pilot centre")
        print("Source:", path)
        print("CRS:", raster.crs)
        print("Resolution:", raster.res)
        print("Bands:", raster.count)
        print("Point raw value(s):", pixel.tolist())
        print("Interpretation NOT applied. Consult the FAO layer legend/codebook,")
        print("crop, water regime, input regime and climate scenario before scoring.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raster", type=Path, required=True)
    p.add_argument("--lat", type=float, default=SOWING_LAT)
    p.add_argument("--lon", type=float, default=SOWING_LON)
    args = p.parse_args(argv)
    inspect(args.raster, args.lat, args.lon)


if __name__ == "__main__":
    main()
