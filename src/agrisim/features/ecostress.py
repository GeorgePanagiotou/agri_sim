"""Extract raw ECOSTRESS JET ETdaily overpasses for the provisional HLS sample.

NASA AppEEARS ETdaily Collection 2 GeoTIFFs downloaded for the pilot currently
advertise `W/m²` in their metadata. Preserve that value, explicitly unconverted:
NASA documentation uses inconsistent descriptions for ETdaily and the request
contains no separate cloud QA layer. Do NOT call these values mm/day or use
as a validated crop ET time series.

    uv run python -m agrisim.features.ecostress
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask, shapes
from rasterio.warp import transform_geom

from agrisim.config import REPO
from agrisim.preprocessing.sentinel2_aligned import latest_hls_batch, reference_mask

DEFAULT_TASKS = REPO / "data/raw/appeears"
DEFAULT_OUTPUT = REPO / "data/processed/features/ecostress_overpasses.csv"
COLUMNS = [
    "field_id", "date_utc", "acquired_utc", "source", "source_file",
    "footprint_pixels", "valid_pixels", "valid_fraction", "et_raw_median",
    "reported_units", "cloud_qa_available", "spatial_support",
]


def timestamp_from_name(filename: str) -> datetime:
    """Parse real ECO_L3T_JET files, e.g. doy2024278090958; don't guess dates."""
    match = re.search(r"doy(20\d{2})(\d{3})(\d{6})(?!\d)", filename)
    if not match:
        raise ValueError(f"Unrecognized ECOSTRESS overpass timestamp: {filename}")
    return datetime.strptime("".join(match.groups()), "%Y%j%H%M%S").replace(tzinfo=timezone.utc)


def extract(task_root: Path = DEFAULT_TASKS, hls_batch: Path | None = None,
            field_id: str = "evia_pilot") -> pd.DataFrame:
    hls_batch = hls_batch or latest_hls_batch(field_id=field_id)
    candidate, hls_transform, hls_crs = reference_mask(hls_batch, field_id)
    hls_polygons = [geometry for geometry, value in
                    shapes(candidate, mask=candidate.astype(bool), transform=hls_transform)
                    if value == 1]
    rows = []
    # Task download includes one nasa_request.json, so only read verified task dirs.
    for tif in sorted(Path(task_root).glob("**/ECO_L3T_JET.*_ETdaily_*.tif")):
        task = tif.parent / "nasa_request.json"
        if not task.exists() or '"ecostress_et"' not in task.read_text(encoding="utf-8"):
            continue
        acquired = timestamp_from_name(tif.name)
        with rasterio.open(tif) as ds:
            if ds.count != 1 or ds.crs is None:
                raise ValueError(f"Invalid ECOSTRESS GeoTIFF structure: {tif}")
            polygons = [transform_geom(hls_crs, ds.crs, polygon) for polygon in hls_polygons]
            footprint = geometry_mask(polygons, out_shape=(ds.height, ds.width),
                                      transform=ds.transform, invert=True, all_touched=True)
            raw = ds.read(1, masked=True).filled(np.nan).astype("float64")
            valid = footprint & np.isfinite(raw)
            n = int(valid.sum())
            total = int(footprint.sum())
            if not total:
                raise ValueError(f"ECOSTRESS raster does not intersect HLS sample: {tif}")
            units = ds.tags().get("units", "unknown")
        rows.append({
            "field_id": field_id,
            "date_utc": acquired.date().isoformat(),
            "acquired_utc": acquired.isoformat(),
            "source": "NASA_ECO_L3T_JET_002",
            "source_file": tif.name,
            "footprint_pixels": total,
            "valid_pixels": n,
            "valid_fraction": n / total,
            "et_raw_median": float(np.median(raw[valid])) if n else np.nan,
            "reported_units": units,
            "cloud_qa_available": False,
            "spatial_support": "provisional_hls_candidate_all_touched",
        })
    return pd.DataFrame(rows, columns=COLUMNS).sort_values("acquired_utc")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-dir", type=Path, default=DEFAULT_TASKS)
    ap.add_argument("--hls-batch", type=Path)
    ap.add_argument("--field-id", default="evia_pilot")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    a = ap.parse_args(argv)
    observations = extract(a.input_dir, a.hls_batch, a.field_id)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    observations.to_csv(a.out, index=False)
    print("ECOSTRESS overpasses:", len(observations),
          "; non-missing pilot estimates:", observations.et_raw_median.notna().sum())
    print("Raw metadata units only; NO mm/day conversion and NO cloud QA claims")
    print("Saved:", a.out)


if __name__ == "__main__":
    main()
