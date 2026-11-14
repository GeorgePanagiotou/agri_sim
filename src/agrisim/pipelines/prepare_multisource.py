"""Rebuild AgriSim's local environmental features from already-downloaded data.

Uses the six-season HLS batch, per-date Sentinel-2 L2A clips, SRTM HGT ZIP,
regional POWER/IMERG/SMAP caches, FAO GAEZ crops, and optional ECOSTRESS ET.
NEVER performs downloads or modifies raw NASA/ESA/FAO inputs.

    uv run python -m agrisim.pipelines.prepare_multisource --plan
    uv run python -m agrisim.pipelines.prepare_multisource

Outputs are stored under data/processed/features. Existing processed outputs
are regenerated; the original raw files are untouched.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from agrisim.config import REPO
from agrisim.features.build_multisource_environment import main as build_environment
from agrisim.features.ecostress import extract as extract_ecostress
from agrisim.preprocessing.sentinel2_aligned import (
    extract_all as extract_sentinel2,
    latest_hls_batch,
)
from agrisim.preprocessing.srtm_terrain import extract_hgt, extract_terrain
from agrisim.timeseries.greenup import run as run_greenup
from agrisim.timeseries.vegetation_indices import build as build_hls_vegetation


def paths(repo: Path = REPO) -> dict[str, Path]:
    base = repo / "data"
    features = base / "processed/features"
    return {
        "hls_batches": base / "processed/evia_sowing/hls_batches",
        "sentinel": base / "raw/sentinel2",
        "srtm_zip": base / "raw/srtm/N38E023.SRTMGL1.hgt.zip",
        "srtm_extract": base / "interim/srtm",
        "appeears": base / "raw/appeears",
        "features": features,
        "hls_observations": features / "vegetation_observations.csv",
        "greenup": features / "greenup_events.csv",
        "s2_observations": features / "sentinel2_aligned_evia_pilot.csv",
        "ecostress_overpasses": features / "ecostress_overpasses.csv",
        "dataset": features / "environment_multisource_daily.parquet",
        "coverage": features / "environment_multisource_coverage.csv",
        "gaez": base / "raw/fao_gaez",
        "smap": base / "processed/evia_sowing/smap",
        "imerg": base / "raw/imerg_daily",
    }


def discover(p: dict[str, Path], field_id: str = "evia_pilot") -> tuple[Path, list[Path], list[Path]]:
    batch = latest_hls_batch(p["hls_batches"], field_id)
    sentinel = sorted(p["sentinel"].glob("s2_l2a_*.tif"))
    ecostress = sorted(p["appeears"].glob("**/ECO_L3T_JET.*_ETdaily_*.tif"))
    if not p["srtm_zip"].exists():
        raise FileNotFoundError(f"SRTM tile not found: {p['srtm_zip']}")
    if not p["gaez"].exists():
        raise FileNotFoundError(f"GAEZ crop raster folder not found: {p['gaez']}")
    if not list(p["smap"].glob("smap_daily*.csv")):
        raise FileNotFoundError("No SMAP daily CSVs found; finish SMAP preprocessing first")
    if not list(p["imerg"].glob("*.parquet")):
        raise FileNotFoundError("No IMERG Final cache found")
    return batch, sentinel, ecostress


def run(*, plan: bool = False, min_clear: float = 0.8,
        first_year: int = 2020, last_year: int = 2025,
        repo: Path = REPO, field_id: str = "evia_pilot") -> dict[str, object]:
    if field_id != "evia_pilot":
        raise ValueError("Current static GAEZ/SRTM pipeline is restricted to evia_pilot")
    if not 0 <= min_clear <= 1:
        raise ValueError("min_clear must be between 0 and 1")
    p = paths(repo)
    batch, sentinel_files, ecostress_files = discover(p, field_id)
    summary = {
        "hls_batch": str(batch),
        "s2_tifs": len(sentinel_files),
        "ecostress_tifs": len(ecostress_files),
        "srtm_zip": str(p["srtm_zip"]),
        "min_clear": min_clear,
    }
    print("AGRISIM: LOCAL PREPROCESSING PLAN" if plan else "AGRISIM: LOCAL PREPROCESSING")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    if plan:
        print("No raw files will be modified; no downloads or API calls are made.")
        return summary
    p["features"].mkdir(parents=True, exist_ok=True)

    # HLS is always processed alone; Sentinel-2 uses its own aligned index table.
    # This prevents the old 990m-window / 90m-candidate mixing issue.
    hls = build_hls_vegetation(hls_batch=batch, out=p["hls_observations"])
    if hls.empty:
        raise ValueError("HLS preprocessing returned no observations")
    run_greenup(observations=p["hls_observations"], out=p["greenup"], method="pelt")
    if sentinel_files:
        s2 = extract_sentinel2(p["sentinel"], batch, field_id)
        s2.to_csv(p["s2_observations"], index=False)
        print(f"Sentinel-2: {len(s2)} aligned dates -> {p['s2_observations']}")
    else:
        # Avoid consuming a stale aligned CSV from a previous run.
        if p["s2_observations"].exists():
            raise RuntimeError("No Sentinel-2 TIFFs exist, but aligned CSV does. "
                               "Remove or archive the stale CSV before rebuilding.")
        print("No Sentinel-2 TIFFs found; environmental build retains S2 as missing")

    hgt = extract_hgt(p["srtm_zip"], p["srtm_extract"])
    terrain = extract_terrain(hgt, batch, p["features"], field_id)
    print("SRTM:", terrain[["elevation_m_median", "slope_deg_median"]].to_dict("records"))
    if ecostress_files:
        et = extract_ecostress(p["appeears"], batch, field_id)
        et.to_csv(p["ecostress_overpasses"], index=False)
        print(f"ECOSTRESS: {len(et)} raw overpasses, {et.et_raw_median.notna().sum()} valid")
        print("Raw ET units and QA limitations retained, NOT converted to mm/day")
    elif p["ecostress_overpasses"].exists():
        raise RuntimeError("ECOSTRESS extracted CSV exists, but no raw ET TIFFs were found. "
                           "Archive stale CSV before rebuilding.")
    else:
        print("ECOSTRESS optional; no ET TIFFs were found")

    # build_environment is an existing CLI-style function, called locally.
    # It samples all 5 GAEZ crop rasters and joins POWER, IMERG, SMAP,
    # independent HLS + Sentinel-2 NDVI, static SRTM, optional raw ECOSTRESS.
    build_environment([
        "--first-year", str(first_year), "--last-year", str(last_year),
        "--min-clear", str(min_clear), "--out-dir", str(p["features"]),
    ])
    frame = pd.read_parquet(p["dataset"])
    if frame.duplicated(["field_id", "date"]).any():
        raise AssertionError("The combined dataset contains duplicate site/date pairs")
    expected = sum((pd.Timestamp(f"{y+1}-06-30") - pd.Timestamp(f"{y}-09-01")).days + 1
                   for y in range(first_year, last_year + 1))
    if len(frame) != expected:
        raise AssertionError(f"Expected {expected} daily rows, got {len(frame)}")
    print(f"INTEGRATION VERIFIED: {len(frame)} daily rows, {len(frame.columns)} columns")
    print("Saved:", p["dataset"])
    summary.update(daily_rows=len(frame), columns=len(frame.columns))
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true", help="Inspect local inputs without modifying files")
    ap.add_argument("--min-clear", type=float, default=0.8)
    ap.add_argument("--first-year", type=int, default=2020)
    ap.add_argument("--last-year", type=int, default=2025)
    args = ap.parse_args(argv)
    run(plan=args.plan, min_clear=args.min_clear,
        first_year=args.first_year, last_year=args.last_year)


if __name__ == "__main__":
    main()
