"""Scratch: ESA WorldCover 2020 (10 m, pre-fire) for the North Evia AOI, read by window from the public S3 COGs."""
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge

AOI = (22.80, 38.60, 23.70, 39.05)  # W S E N
URL = "/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2020/map/ESA_WorldCover_10m_2020_v100_{}_Map.tif"
out = Path(sys.argv[1]) / "worldcover_2020_evia.tif"
srcs = [rasterio.open(URL.format(t)) for t in ("N36E021", "N39E021")]
mosaic, transform = merge(srcs, bounds=AOI)
meta = srcs[0].meta | {"height": mosaic.shape[1], "width": mosaic.shape[2], "transform": transform,
                       "compress": "deflate", "driver": "GTiff"}
with rasterio.open(out, "w", **meta) as dst:
    dst.write(mosaic)
vals, counts = np.unique(mosaic, return_counts=True)
print(out, mosaic.shape, {int(v): round(c / mosaic.size * 100, 1) for v, c in zip(vals, counts)})
