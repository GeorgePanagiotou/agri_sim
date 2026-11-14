"""Re-extract Sentinel-2 vegetation indices over the SAME provisional HLS mask.

This replaces the earlier one-off PowerShell/Python notebook code. It never
changes downloaded Copernicus GeoTIFFs. ESA scene cloud percentage is NOT a
substitute for per-pixel SCL masking.

    uv run python -m agrisim.preprocessing.sentinel2_aligned
    uv run python -m agrisim.preprocessing.sentinel2_aligned --start 2024-09-01 --end 2025-06-30
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject

from agrisim.config import REPO
from agrisim.timeseries.vegetation_indices import vegetation_indices

EXPECTED_BANDS = ["B03_green", "B04_red", "B08_nir", "SCL", "dataMask"]
DEFAULT_HLS_ROOT = REPO / "data/processed/evia_sowing/hls_batches"
DEFAULT_S2_DIR = REPO / "data/raw/sentinel2"
DEFAULT_OUTPUT = REPO / "data/processed/features/sentinel2_aligned_evia_pilot.csv"


def latest_hls_batch(root: Path = DEFAULT_HLS_ROOT, field_id: str = "evia_pilot") -> Path:
    """Find the latest *complete* saved HLS batch, not a half-written directory."""
    candidates = [
        p for p in root.iterdir()
        if p.is_dir() and (p / field_id / "hls" / "field_context.npz").exists()
    ] if root.exists() else []
    if not candidates:
        raise FileNotFoundError(f"No HLS field_context.npz under {root}; preprocess HLS first")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def reference_mask(batch: Path, field_id: str = "evia_pilot") -> tuple[np.ndarray, Affine, CRS]:
    archive = batch / field_id / "hls" / "field_context.npz"
    with np.load(archive, allow_pickle=False) as z:
        mask = z["candidate_mask"].astype("uint8")
        transform = Affine(*z["transform"].tolist())
        crs = CRS.from_wkt(z["crs"].item())
    if int(mask.sum()) != 9 or not mask.shape == (33, 33):
        raise ValueError(f"Expected the provisional 3x3 candidate in 33x33 HLS context: {archive}")
    return mask, transform, crs


def extract_one(tif: Path, mask: np.ndarray, src_transform: Affine, src_crs: CRS,
                field_id: str = "evia_pilot") -> dict:
    metadata = tif.with_suffix(".json")
    if not metadata.exists():
        raise FileNotFoundError(f"Sentinel-2 acquisition metadata missing: {metadata}")
    info = json.loads(metadata.read_text(encoding="utf-8"))
    if info.get("dataset") != "sentinel-2-l2a" or info.get("band_order") != EXPECTED_BANDS:
        raise ValueError(f"Unexpected Sentinel-2 source/band ordering: {metadata}")
    if info.get("field_id") != field_id:
        raise ValueError(f"Sentinel-2 site does not match HLS mask: {metadata}")
    if info.get("is_temporal_mosaic") or info.get("start_utc") != info.get("end_utc"):
        raise ValueError(f"Multi-day mosaics are not individual acquisition dates: {metadata}")
    date_utc = pd.Timestamp(info["start_utc"]).date().isoformat()
    with rasterio.open(tif) as ds:
        if ds.count != 5 or ds.crs is None:
            raise ValueError(f"Expected five georeferenced Sentinel-2 bands: {tif}")
        local = np.zeros((ds.height, ds.width), dtype="uint8")
        reproject(
            source=mask, destination=local,
            src_transform=src_transform, src_crs=src_crs,
            dst_transform=ds.transform, dst_crs=ds.crs,
            src_nodata=0, dst_nodata=0, resampling=Resampling.nearest,
        )
        green, red, nir, scl, datamask = ds.read()
    footprint = local == 1
    total = int(footprint.sum())
    if not total:
        raise ValueError(f"HLS candidate does not intersect Sentinel-2 image: {tif}")
    clear = (datamask > 0) & np.isin(scl, [4, 5])
    ndvi, evi2, savi = vegetation_indices(green, red, nir, footprint & clear)
    good = np.isfinite(ndvi) & np.isfinite(evi2)
    n = int(good.sum())
    return {
        "field_id": field_id,
        "date_utc": date_utc,
        "source": "ESA_Sentinel2_L2A",
        "source_file": tif.name,
        "spatial_support": "provisional_hls_candidate_mask",
        "resolution_m": 10,
        "footprint_pixels": total,
        "valid_pixels": n,
        "clear_fraction": n / total,
        "ndvi_median": float(np.median(ndvi[good])) if n else np.nan,
        "evi2_median": float(np.median(evi2[good])) if n else np.nan,
        "savi_median": float(np.median(savi[good])) if n else np.nan,
    }


def extract_all(sentinel_dir: Path = DEFAULT_S2_DIR, hls_batch: Path | None = None,
                field_id: str = "evia_pilot", start: str | None = None,
                end: str | None = None) -> pd.DataFrame:
    hls_batch = hls_batch or latest_hls_batch(field_id=field_id)
    mask, ref_transform, ref_crs = reference_mask(hls_batch, field_id)
    rows = []
    for tif in sorted(Path(sentinel_dir).glob("s2_l2a_*.tif")):
        meta = tif.with_suffix(".json")
        if not meta.exists():
            raise FileNotFoundError(f"Missing Sentinel-2 metadata: {meta}")
        info = json.loads(meta.read_text(encoding="utf-8"))
        if info.get("is_temporal_mosaic"):
            continue  # Do not claim a mosaic is a single-day observation.
        if info.get("field_id") != field_id:
            continue
        acquired = info.get("start_utc", "")
        if (start and acquired < start) or (end and acquired[:10] > end):
            continue
        rows.append(extract_one(tif, mask, ref_transform, ref_crs, field_id))
    if not rows:
        raise FileNotFoundError(f"No single-date Sentinel-2 GeoTIFFs under {sentinel_dir}")
    out = pd.DataFrame(rows).sort_values(["date_utc", "source_file"])
    if out.date_utc.duplicated().any():
        raise ValueError("Multiple Sentinel-2 TIFFs per date; resolve acquisitions explicitly")
    return out.reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sentinel-dir", type=Path, default=DEFAULT_S2_DIR)
    p.add_argument("--hls-batch", type=Path, default=None)
    p.add_argument("--field-id", default="evia_pilot")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args(argv)
    if args.start and args.end and args.start > args.end:
        p.error("--start must precede --end")
    result = extract_all(args.sentinel_dir, args.hls_batch, args.field_id, args.start, args.end)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.out, index=False)
    print("Aligned Sentinel-2:", len(result), "observations;",
          int(result.ndvi_median.notna().sum()), "with valid NDVI;",
          int((result.clear_fraction >= 0.8).sum()), "at >=80% clear")
    print("Saved:", args.out)
    print("Footprint is a provisional 3x3 HLS candidate, NOT a surveyed field")


if __name__ == "__main__":
    main()
