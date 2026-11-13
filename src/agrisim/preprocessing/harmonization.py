"""Explicit spatial co-registration; resampling never increases source detail."""
import numpy as np

def resample_geotiff(src_path, output_path, *, dst_crs, dst_transform, width, height,
                     categorical=False, dst_nodata=np.nan):
    import rasterio
    from rasterio.warp import reproject, Resampling
    from pathlib import Path
    out = Path(output_path); out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src_path) as src:
        alg = Resampling.nearest if categorical else Resampling.bilinear
        data = np.full((src.count, height, width), dst_nodata, dtype='float32')
        for idx in range(src.count):
            reproject(source=rasterio.band(src, idx + 1), destination=data[idx],
                      src_transform=src.transform, src_crs=src.crs,
                      src_nodata=src.nodata, dst_transform=dst_transform, dst_crs=dst_crs,
                      dst_nodata=dst_nodata, resampling=alg)
        with rasterio.open(out, 'w', driver='GTiff', height=height, width=width,
                           count=src.count, crs=dst_crs, transform=dst_transform,
                           dtype='float32', nodata=dst_nodata, compress='deflate') as dst:
            dst.write(data)
    return out
