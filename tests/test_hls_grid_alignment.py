"""Offline regression tests for HLS source-tile grid alignment."""

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from agrisim.data_sources import download_evia_hls as hls
from agrisim.data_sources.hls_fields import Site


def _synthetic_clip(path: Path, site: Site, crs: str, horizontal_shift_m: float,
                    cloud_at_centre: bool = False):
    x, y = transform("EPSG:4326", crs, [site.lon], [site.lat])
    raster_transform = from_origin(
        x[0] - 16.5 * 30 + horizontal_shift_m, y[0] + 16.5 * 30, 30, 30,
    )
    pixels = np.zeros((4, 33, 33), dtype="int16")
    pixels[0] = 1000  # green reflectance: 0.1
    pixels[1] = 1000  # red reflectance: 0.1
    pixels[2] = 3000  # NIR reflectance: 0.3
    if cloud_at_centre:
        pixels[3, 16, 16] = 2  # cloud flag; must stay exact
    with rasterio.open(
        path, "w", driver="GTiff", width=33, height=33, count=4,
        dtype="int16", crs=crs, transform=raster_transform,
    ) as dst:
        dst.write(pixels)
        dst.descriptions = hls.BANDS


def test_prepare_reprojects_different_native_tile_grids(tmp_path, monkeypatch):
    site = Site("evia_pilot", 23.43232, 38.75920, 33)
    monkeypatch.setattr(hls, "RAW", tmp_path / "raw")
    monkeypatch.setattr(hls, "PROC", tmp_path / "processed")
    monkeypatch.setattr(hls, "REPO", tmp_path)
    clip_dir = site.directory(hls.RAW)
    clip_dir.mkdir(parents=True)
    ids = [
        "HLS.L30.T34SGH.2023260T090400.v2.0",
        "HLS.L30.T34SGJ.2023261T090400.v2.0",
        "HLS.L30.T34SGH.2023262T090400.v2.0",
    ]
    _synthetic_clip(clip_dir / f"{ids[0]}.tif", site, "EPSG:32634", 0)
    _synthetic_clip(clip_dir / f"{ids[1]}.tif", site, "EPSG:32634", 15, True)
    _synthetic_clip(clip_dir / f"{ids[2]}.tif", site, "EPSG:32635", 0)
    features = [
        {"id": identifier, "properties": {"datetime": f"2023-09-{17+i}T09:04:00Z", "platform": "landsat-9"}}
        for i, identifier in enumerate(ids)
    ]
    output = site.directory(hls.PROC)
    output.mkdir(parents=True)
    hls.prepare(features, site, out=output)
    manifest = pd.read_csv(output / "acquisitions.csv")
    assert manifest["native_grid_aligned"].tolist() == [False, True, True]
    with np.load(output / "field_context.npz") as archive:
        assert archive["reflectance"].shape == (3, 3, 33, 33)
        assert archive["clear"].shape == (3, 33, 33)
        assert np.isnan(archive["reflectance"][1, :, 16, 16]).all()
        assert not archive["clear"][1, 16, 16]
        assert archive["clear"][0, 16, 16]
        assert np.isclose(archive["reflectance"][0, 2, 16, 16], np.float32(0.3), atol=1e-6)
    # Source cached GeoTIFFs were never modified.
    with rasterio.open(clip_dir / f"{ids[1]}.tif") as ds:
        assert ds.read(4)[16, 16] == 2
