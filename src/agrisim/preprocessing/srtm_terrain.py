"""Process cached official SRTMGL1 .hgt.zip into HLS-aligned terrain features.

No new data are downloaded. Slope is an approximate DEM-derived gradient,
not an on-site survey. Run:
  uv run python -m agrisim.preprocessing.srtm_terrain
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import Resampling, reproject

from agrisim.config import REPO
from agrisim.preprocessing.sentinel2_aligned import latest_hls_batch, reference_mask

DEFAULT_ZIP = REPO / "data/raw/srtm/N38E023.SRTMGL1.hgt.zip"
DEFAULT_OUT = REPO / "data/processed/features"


def extract_hgt(zip_path: Path, output_dir: Path) -> Path:
    """Extract one trusted HGT file, never an arbitrary archive path."""
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path) as archive:
        entries = [entry for entry in archive.infolist()
                   if not entry.is_dir() and entry.filename.lower().endswith(".hgt")]
        if len(entries) != 1:
            raise ValueError(f"Expected exactly one HGT in {zip_path}, found {len(entries)}")
        out = output_dir / Path(entries[0].filename).name
        if not out.exists() or out.stat().st_size != entries[0].file_size:
            tmp = out.with_name(out.name + ".partial")
            with archive.open(entries[0]) as source, tmp.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            tmp.replace(out)
    return out


def terrain_layers(elevation: np.ndarray, cell_x_m: float, cell_y_m: float
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Slope and compass aspect (downslope bearing, north=0, clockwise)."""
    if cell_x_m <= 0 or cell_y_m <= 0:
        raise ValueError("Expected projected grid spacing in positive metres")
    # Grid row increases SOUTHWARD. Mathematical d(elevation)/d(north) = -d/drow.
    dz_drow, dz_deast = np.gradient(elevation.astype("float64"), cell_y_m, cell_x_m)
    slope = np.degrees(np.arctan(np.hypot(dz_deast, dz_drow))).astype("float32")
    # Downslope vector is (-dz/deast, +dz/drow) in (east, north) coordinates.
    aspect = (np.degrees(np.arctan2(-dz_deast, dz_drow)) + 360) % 360
    aspect = aspect.astype("float32")
    aspect[slope < 0.01] = np.nan
    return slope, aspect


def extract_terrain(hgt: Path, hls_batch: Path, out_dir: Path = DEFAULT_OUT,
                    field_id: str = "evia_pilot") -> pd.DataFrame:
    candidate, transform, crs = reference_mask(hls_batch, field_id)
    if not crs.is_projected:
        raise ValueError("HLS reference grid must use a projected metric CRS")
    elevation = np.full(candidate.shape, np.nan, dtype="float32")
    with rasterio.open(hgt) as src:
        reproject(source=rasterio.band(src, 1), destination=elevation,
                  src_transform=src.transform, src_crs=src.crs,
                  dst_transform=transform, dst_crs=crs,
                  src_nodata=src.nodata if src.nodata is not None else -32768,
                  dst_nodata=np.nan, resampling=Resampling.bilinear)
    if not np.isfinite(elevation).all():
        raise ValueError("SRTM HLS context includes invalid/nodata cells; cannot compute gradients")
    slope, aspect = terrain_layers(elevation, abs(transform.a), abs(transform.e))
    selected = candidate.astype(bool)
    angles = np.deg2rad(aspect[selected])
    angles = angles[np.isfinite(angles)]
    mean_aspect = (float((np.degrees(np.arctan2(np.mean(np.sin(angles)),
                                                     np.mean(np.cos(angles)))) + 360) % 360)
                   if angles.size else np.nan)
    out_dir.mkdir(parents=True, exist_ok=True)
    tif = out_dir / f"srtm_terrain_{field_id}.tif"
    csv = out_dir / f"srtm_terrain_{field_id}.csv"
    with rasterio.open(tif, "w", driver="GTiff", height=elevation.shape[0],
                       width=elevation.shape[1], count=3, dtype="float32", crs=crs,
                       transform=transform, nodata=-9999, compress="deflate") as dst:
        for index, (name, layer) in enumerate(
            (("elevation_m", elevation), ("slope_deg", slope), ("aspect_deg", aspect)), 1
        ):
            dst.write(np.where(np.isfinite(layer), layer, -9999).astype("float32"), index)
            dst.set_band_description(index, name)
    summary = pd.DataFrame([{
        "field_id": field_id,
        "source": "NASA_SRTMGL1_v003",
        "spatial_support": "provisional_hls_candidate_3x3",
        "elevation_m_median": float(np.nanmedian(elevation[selected])),
        "slope_deg_median": float(np.nanmedian(slope[selected])),
        "aspect_deg_circular_mean": mean_aspect,
    }])
    summary.to_csv(csv, index=False)
    return summary


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    p.add_argument("--hls-batch", type=Path, default=None)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--field-id", default="evia_pilot")
    a = p.parse_args(argv)
    hgt = extract_hgt(a.zip, REPO / "data/interim/srtm")
    result = extract_terrain(hgt, a.hls_batch or latest_hls_batch(field_id=a.field_id),
                             a.out_dir, a.field_id)
    print("AGRISIM TERRAIN FEATURES\n", result.to_string(index=False))
    print("Saved SRTM GeoTIFF and CSV to", a.out_dir)


if __name__ == "__main__":
    main()
