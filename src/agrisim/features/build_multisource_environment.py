"""Build an auditable, six-season environmental feature table for North Evia.

Input observations: NASA POWER, regional GPM IMERG Final/Late, NASA SMAP L4,
NASA HLS L30, ESA Sentinel-2 L2A, NASA SRTM, and FAO GAEZ v4.

No future-data leakage in prior-day rolling aggregates; no fabricated weather,
missing rainfall zeros, satellite harmonization, or field-level claims.

Run from the AgriSim-AI repository root:
  uv run python -m agrisim.features.build_multisource_environment
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform as warp_transform

from agrisim.config import REPO, SOWING_LAT, SOWING_LON
from agrisim.features.build_environment_multisource import (
    add_vegetation,
    imerg_daily,
    load_power,
    smap_daily,
)

CROPS = {
    "wheat": "whe",
    "barley": "brl",
    "maize": "mze",
    "chickpea": "chk",
    "dry_pea": "pea",
}
EXPECTED_SCENARIO = "rainfed_historical_low_input"


def grow_seasons(first_year: int = 2020, last_year: int = 2025) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    if last_year < first_year:
        raise ValueError("last_year must be at least first_year")
    return [
        (f"{y}-{y+1}", pd.Timestamp(f"{y}-09-01"), pd.Timestamp(f"{y+1}-06-30"))
        for y in range(first_year, last_year + 1)
    ]


def power_input(processed: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.exists():
            raise FileNotFoundError(explicit)
        return explicit
    # Full-span files only, not a short 2023-2025 extract.
    files = list(processed.glob("power_daily_*.parquet"))
    candidates = []
    for file in files:
        match = re.fullmatch(r"power_daily_(\d{8})_(\d{8})\.parquet", file.name)
        if match and match.group(1) <= "20200901":
            candidates.append((match.group(2), file))
    if not candidates:
        raise FileNotFoundError("No full-span POWER parquet found. Pass --power PATH explicitly.")
    return max(candidates, key=lambda x: x[0])[1]


def _read_gaez_crop(path: Path, lon: float, lat: float) -> dict:
    """Sample one official current-cropland suitability-index grid cell."""
    with rasterio.open(path) as ds:
        if ds.crs is None or ds.count != 1:
            raise ValueError(f"GAEZ raster must be a single-band georeferenced raster: {path}")
        xx, yy = warp_transform("EPSG:4326", ds.crs, [lon], [lat])
        x, y = xx[0], yy[0]
        if not (ds.bounds.left <= x < ds.bounds.right and ds.bounds.bottom < y <= ds.bounds.top):
            raise ValueError(f"GAEZ raster does not cover study point: {path}")
        sample = next(ds.sample([(x, y)], masked=True))
        mask = np.ma.getmaskarray(sample)
        value = float(sample[0]) if not bool(mask[0]) else float("nan")
        if ds.nodata is not None and np.isfinite(value) and value == ds.nodata:
            value = float("nan")
        if not np.isfinite(value) or not 0 <= value <= 10000:
            raise ValueError(f"GAEZ point value is invalid or NoData for {path}: {value}")
        return {
            "suitability_index": value,
            "crs": str(ds.crs),
            "resolution_x": float(ds.res[0]),
            "resolution_y": float(ds.res[1]),
            "source_file": str(path),
        }


def gaez_suitability(folder: Path, lon: float = SOWING_LON, lat: float = SOWING_LAT) -> pd.DataFrame:
    """Load five matching suLr GAEZ files; reject missing/incompatible layers."""
    rows = []
    reference_grid = None
    for crop, code in CROPS.items():
        files = sorted(folder.glob(f"{crop}_{EXPECTED_SCENARIO}_suLr_{code}.tif"))
        if len(files) != 1:
            raise FileNotFoundError(
                f"Expected exactly one GAEZ {crop} layer: "
                f"{folder / f'{crop}_{EXPECTED_SCENARIO}_suLr_{code}.tif'}"
            )
        path = files[0]
        with rasterio.open(path) as ds:
            grid = (str(ds.crs), tuple(round(float(x), 10) for x in ds.res))
            if reference_grid is None:
                reference_grid = grid
            elif grid != reference_grid:
                raise ValueError(f"GAEZ CRS/resolution mismatch for {path}")
        item = _read_gaez_crop(path, lon, lat)
        item.update(
            crop=crop, source="FAO_GAEZ_v4_suLr",
            scenario=EXPECTED_SCENARIO,
            baseline="1981-2010",
            spatial_support="regional_5arcmin_grid_current_cropland",
        )
        rows.append(item)
    return pd.DataFrame(rows)


def _verify_dates(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    data = frame.copy()
    if "date" not in data:
        raise ValueError(f"{source} missing date column")
    data["date"] = pd.to_datetime(data["date"], errors="raise", utc=True).dt.tz_localize(None).dt.normalize()
    if data["date"].duplicated().any():
        raise ValueError(f"{source} has duplicate daily dates")
    return data



def load_ecostress(path: Path) -> pd.DataFrame:
    """Optional raw JET ET overpasses, without fictitious daily filling or ET units conversion.

    Multiple genuine overpasses on the same day are summarized to a daily median,
    but only when all units match; original per-overpass rows remain in the CSV.
    """
    cols = ["date", "ecostress_et_raw_median", "ecostress_et_raw_units",
            "ecostress_overpasses", "ecostress_et_valid_fraction"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path)
    required = {"date_utc", "et_raw_median", "reported_units", "valid_fraction"}
    if not required.issubset(df):
        raise ValueError(f"Invalid ECOSTRESS overpasses CSV: {path}")
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["date"] = pd.to_datetime(df["date_utc"], utc=True).dt.tz_localize(None).dt.normalize()
    groups = []
    for day, part in df.groupby("date"):
        units = part["reported_units"].dropna().unique().tolist()
        if len(units) != 1:
            raise ValueError(f"Mixed/unknown ECOSTRESS raw ET units on {day}: {units}")
        usable = part.loc[part["et_raw_median"].notna()]
        groups.append({
            "date": day,
            "ecostress_et_raw_median": (float(usable["et_raw_median"].median())
                                         if not usable.empty else np.nan),
            "ecostress_et_raw_units": units[0],
            "ecostress_overpasses": len(part),
            "ecostress_et_valid_fraction": (float(usable["valid_fraction"].mean())
                                             if not usable.empty else np.nan),
        })
    return pd.DataFrame(groups, columns=cols)

def build_daily(
    power: pd.DataFrame,
    gpm: pd.DataFrame,
    smap: pd.DataFrame,
    terrain: pd.DataFrame,
    gaez: pd.DataFrame,
    *,
    vegetation_dir: Path | None = None,
    ecostress: pd.DataFrame | None = None,
    min_clear: float = 0.8,
    first_year: int = 2020,
    last_year: int = 2025,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (growing-season daily features, per-season QA summary)."""
    if not 0 <= min_clear <= 1:
        raise ValueError("min_clear must be in [0, 1]")
    periods = grow_seasons(first_year, last_year)
    if len(terrain) != 1 or terrain.iloc[0].get("field_id") != "evia_pilot":
        raise ValueError("SRTM terrain CSV must contain exactly one evia_pilot row")
    if set(gaez["crop"]) != set(CROPS) or gaez["crop"].duplicated().any():
        raise ValueError("GAEZ should have exactly the five expected crops")

    # Include a pre-season lookback so the first day can use the prior
    # 7/14 days when the source provides them.
    start = periods[0][1] - pd.Timedelta(days=30)
    end = periods[-1][2]
    # Build an UNINTERRUPTED calendar before rolling features, so a September
    # window never uses values from the previous June as if it were yesterday.
    all_dates = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    data = all_dates
    for source, frame in (("POWER", power), ("IMERG", gpm), ("SMAP", smap)):
        frame = _verify_dates(frame, source)
        data = data.merge(frame, on="date", how="left", validate="one_to_one")

    if vegetation_dir is not None:
        data = add_vegetation(data, vegetation_dir, min_clear)
    if ecostress is not None and not ecostress.empty:
        ecostress = _verify_dates(ecostress, "ECOSTRESS")
        data = data.merge(ecostress, on="date", how="left", validate="one_to_one")
    for col in ("ecostress_et_raw_median", "ecostress_et_raw_units",
                "ecostress_overpasses", "ecostress_et_valid_fraction"):
        if col not in data:
            data[col] = np.nan
    data["ecostress_missing"] = data["ecostress_et_raw_median"].isna()
    data["ecostress_cloud_qa_available"] = False
    for col in ("hls_ndvi", "hls_evi2", "hls_clear_fraction",
                "s2_ndvi", "s2_evi2", "s2_clear_fraction"):
        if col not in data:
            data[col] = np.nan
    for col in ("gpm_rain_mm", "gpm_valid_cells", "gpm_product",
                "smap_surface_m3m3", "smap_soil_temp_c", "smap_complete_day",
                "power_temp_c", "power_rain_mm"):
        if col not in data:
            data[col] = np.nan

    terrain_cols = (
        "elevation_m_median", "slope_deg_median", "aspect_deg_circular_mean"
    )
    for col in terrain_cols:
        if col not in terrain:
            raise ValueError(f"Missing SRTM terrain column {col}")
        value = float(terrain.iloc[0][col])
        if not np.isfinite(value):
            raise ValueError(f"Invalid SRTM {col}")
        data[f"srtm_{col}"] = value
    for row in gaez.itertuples(index=False):
        value = float(row.suitability_index)
        if not np.isfinite(value):
            raise ValueError(f"Missing GAEZ suitability for {row.crop}")
        data[f"gaez_{row.crop}_index"] = value

    data["field_id"] = "evia_pilot"
    data["geometry_status"] = "unverified_provisional_hls_candidate_3x3"
    data["smap_spatial_support"] = "coarse_regional_grid_not_field_level"
    data["imerg_spatial_support"] = "regional_0p1_degree_area_mean"
    data["vegetation_spatial_support"] = "provisional_hls_candidate_mask"
    data["gaez_spatial_support"] = "regional_5arcmin_current_cropland"
    data["gaez_scenario"] = EXPECTED_SCENARIO
    data["srtm_source"] = "NASA_SRTMGL1_v003"

    data["power_missing"] = data["power_temp_c"].isna()
    data["imerg_missing"] = data["gpm_rain_mm"].isna()
    data["smap_missing"] = data["smap_surface_m3m3"].isna()
    data["hls_ndvi_missing"] = data["hls_ndvi"].isna()
    data["s2_ndvi_missing"] = data["s2_ndvi"].isna()
    # Sensor observations are NOT averaged: there is an observed offset.
    data["hls_s2_same_day"] = data["hls_ndvi"].notna() & data["s2_ndvi"].notna()
    data["hls_minus_s2_ndvi"] = data["hls_ndvi"] - data["s2_ndvi"]

    # These aggregates are available as of the START of the candidate date.
    # NaN in the underlying full window remains NaN for strict sums.
    data["imerg_rain_prior_7d_mm"] = data["gpm_rain_mm"].shift(1).rolling(7, min_periods=7).sum()
    data["imerg_rain_prior_14d_mm"] = data["gpm_rain_mm"].shift(1).rolling(14, min_periods=14).sum()
    data["power_temp_prior_7d_c"] = data["power_temp_c"].shift(1).rolling(7, min_periods=7).mean()
    data["power_gdd5_prior_14d"] = (
        (data["power_temp_c"] - 5.0).clip(lower=0).shift(1).rolling(14, min_periods=14).sum()
    )
    data["smap_surface_prior_7d_m3m3"] = (
        data["smap_surface_m3m3"].shift(1).rolling(7, min_periods=3).mean()
    )

    # Filter only after calculating features on the full calendar.
    keep = np.zeros(len(data), dtype=bool)
    data["season"] = None
    data["season_day"] = np.nan
    for name, a, b in periods:
        mask = data["date"].between(a, b)
        keep |= mask.to_numpy()
        data.loc[mask, "season"] = name
        data.loc[mask, "season_day"] = (data.loc[mask, "date"] - a).dt.days
    out = data.loc[keep].reset_index(drop=True)
    out["season_day"] = out["season_day"].astype(int)
    if len(out) != sum((b - a).days + 1 for _, a, b in periods):
        raise AssertionError("Unexpected growing-season daily row count")

    qa = []
    for name, a, b in periods:
        part = out.loc[out["season"] == name]
        qa.append({
            "field_id": "evia_pilot",
            "season": name,
            "first_day": a.date().isoformat(),
            "last_day": b.date().isoformat(),
            "calendar_days": len(part),
            "power_temp_days": int(part["power_temp_c"].notna().sum()),
            "imerg_days": int(part["gpm_rain_mm"].notna().sum()),
            "imerg_final_days": int(part["gpm_product"].eq("IMERG_Final_V07").sum()),
            "imerg_late_days": int(part["gpm_product"].eq("IMERG_Late_V07").sum()),
            "smap_days": int(part["smap_surface_m3m3"].notna().sum()),
            "hls_ndvi_days": int(part["hls_ndvi"].notna().sum()),
            "s2_ndvi_days": int(part["s2_ndvi"].notna().sum()),
            "any_ndvi_days": int((part["hls_ndvi"].notna() | part["s2_ndvi"].notna()).sum()),
            "same_day_sensor_pairs": int(part["hls_s2_same_day"].sum()),
            "ecostress_et_days": int(part["ecostress_et_raw_median"].notna().sum()),
        })
    return out, pd.DataFrame(qa)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--power", type=Path, default=None,
                        help="POWER daily parquet; otherwise auto-select latest full historical file")
    parser.add_argument("--first-year", type=int, default=2020,
                        help="First September growing-season start year")
    parser.add_argument("--last-year", type=int, default=2025,
                        help="Last September growing-season start year")
    parser.add_argument("--min-clear", type=float, default=0.8,
                        help="Minimum clear-pixel fraction for NDVI/EVI2 (0..1)")
    parser.add_argument("--out-dir", type=Path,
                        default=REPO / "data/processed/features")
    args = parser.parse_args(argv)
    if not 0 <= args.min_clear <= 1:
        parser.error("--min-clear must be between 0 and 1")
    data_root = REPO / "data"
    processed = data_root / "processed"
    features = processed / "features"
    power_path = power_input(processed, args.power)
    terrain_path = features / "srtm_terrain_evia_pilot.csv"
    if not terrain_path.exists():
        raise FileNotFoundError(f"Missing SRTM features: {terrain_path}")
    gaez_root = data_root / "raw" / "fao_gaez"
    gaez = gaez_suitability(gaez_root)
    daily, qa = build_daily(
        load_power(power_path),
        imerg_daily(data_root / "raw"),
        smap_daily(processed / "evia_sowing" / "smap"),
        pd.read_csv(terrain_path), gaez,
        vegetation_dir=features,
        ecostress=load_ecostress(features / "ecostress_overpasses.csv"),
        min_clear=args.min_clear,
        first_year=args.first_year, last_year=args.last_year,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    parquet = args.out_dir / "environment_multisource_daily.parquet"
    coverage = args.out_dir / "environment_multisource_coverage.csv"
    crops = args.out_dir / "environment_multisource_gaez_crops.csv"
    manifest_file = args.out_dir / "environment_multisource_manifest.json"
    daily.to_parquet(parquet, index=False)
    qa.to_csv(coverage, index=False)
    gaez.to_csv(crops, index=False)
    manifest = {
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "field_id": "evia_pilot",
        "geometry_status": "unverified_provisional_hls_candidate_3x3",
        "daily_rows": len(daily),
        "min_clear": args.min_clear,
        "seasons": qa["season"].tolist(),
        "sources": {
            "power": str(power_path),
            "imerg_final": str(data_root / "raw/imerg_daily"),
            "imerg_late": str(data_root / "raw/imerg_late/2025_Q4.parquet"),
            "smap": str(processed / "evia_sowing/smap"),
            "hls": str(features / "vegetation_observations.csv"),
            "sentinel2": str((features / "sentinel2_aligned_evia_pilot.csv")
                             if (features / "sentinel2_aligned_evia_pilot.csv").exists()
                             else (features / "sentinel2_aligned_evia_pilot_2024_2025.csv")),
            "ecostress": str(features / "ecostress_overpasses.csv"),
            "srtm": str(terrain_path),
            "gaez": str(gaez_root),
        },
        "caveats": [
            "Regional grid products and a provisional 3x3 HLS sample, not a surveyed parcel.",
            "GAEZ v4 is static historical 1981-2010 current-cropland suitability, not a daily field measurement.",
            "HLS and Sentinel-2 NDVI remain separate; no sensor offset correction.",
            "Observed same-day weather/vegetation are retrospective; only *_prior_* features are past-only.",
            "IMERG Late and Final product identities are retained. Missing dates remain NaN.",
            "ECOSTRESS ETdaily is RAW tagged data (e.g. W/m²); no conversion, cloud QA or daily interpolation.",
            "No verified crop labels, sowing dates or real-time forecasts are included.",
        ],
    }
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("\nAGRISIM MULTISOURCE ENVIRONMENT")
    print("POWER input:", power_path)
    print(qa.to_string(index=False))
    print("\nGAEZ suitability:")
    print(gaez[["crop", "suitability_index"]].to_string(index=False))
    print("\nSaved:")
    for path in (parquet, coverage, crops, manifest_file):
        print(" ", path)
    if daily["gpm_rain_mm"].isna().any():
        print("\nNOTE: Some IMERG dates are missing (likely 2026). No zero filling was applied.")
    if daily["s2_ndvi"].isna().any():
        print("NOTE: Sentinel-2 is only processed for the 2024-2025 season so far.")
    print("NOTE: This is a regional/provisional-site observational dataset, NOT field-level ground truth.")


if __name__ == "__main__":
    main()
