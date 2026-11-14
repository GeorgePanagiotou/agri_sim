"""Join regional NASA POWER, Final/Late IMERG, SMAP, SRTM and observed NDVI.

No interpolation, no silent rainfall zeros, no homogenization of satellite NDVI.
Prior-day rolling features exclude the candidate date to avoid information leakage.

uv run python -m agrisim.features.build_environment_multisource \
    --power data/processed/power_daily_19910101_20251231.parquet
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from agrisim.config import REPO, STUDY_AREA


def _normalize_dates(value):
    # Remove timezone safely before matching NASA data on UTC calendar days.
    return pd.to_datetime(value, errors="raise", utc=True).dt.tz_localize(None).dt.normalize()


def load_power(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_parquet(path).reset_index()
    if "date" not in df:
        df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = _normalize_dates(df["date"])
    if df.date.duplicated().any():
        raise ValueError("POWER has duplicate dates")
    rename = {
        "T2M": "power_temp_c",
        "T2M_MAX": "power_temp_max_c",
        "T2M_MIN": "power_temp_min_c",
        "PRECTOTCORR": "power_rain_mm",
        "GWETTOP": "power_surface_wetness",
        "GWETROOT": "power_root_wetness",
        "RH2M": "power_relative_humidity_pct",
        "WS2M": "power_wind_ms",
    }
    return df.rename(columns=rename).sort_values("date")


def _regional_area_mean(frame: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Match the existing IMERG downloader's geographic area-mean convention."""
    required = {"date", "lat", "lon", "precip_mm"}
    if not required.issubset(frame):
        raise ValueError(f"{source_name} missing {sorted(required - set(frame))}")
    data = frame.copy()
    data["date"] = _normalize_dates(data["date"])
    west, east, south, north = STUDY_AREA
    data = data[
        data.lat.between(south - 0.05, north + 0.05)
        & data.lon.between(west - 0.05, east + 0.05)
    ]
    if data.empty:
        raise ValueError(f"{source_name}: no cells inside study area")
    if data.duplicated(["date", "lat", "lon"]).any():
        raise ValueError(f"{source_name}: duplicate grid-cell dates")
    out = data.groupby("date", as_index=False).agg(
        gpm_rain_mm=("precip_mm", "mean"),
        gpm_valid_cells=("precip_mm", "count"),
    )
    out["gpm_product"] = source_name
    return out


def imerg_daily(raw_root: Path) -> pd.DataFrame:
    """Final first; Late only on dates without Final, with explicit provenance."""
    final_files = sorted((raw_root / "imerg_daily").glob("[12][0-9][0-9][0-9].parquet"))
    items = []
    final_cells = None
    for file in final_files:
        raw = pd.read_parquet(file)
        if raw.empty:
            continue
        items.append(_regional_area_mean(raw, "IMERG_Final_V07"))
        # Every cached Final year should use one fixed regional grid.
        points = set(map(tuple, raw[["lat", "lon"]].drop_duplicates().to_numpy()))
        if final_cells is None:
            final_cells = points
        elif points != final_cells:
            raise ValueError(f"IMERG Final grid differs in {file.name}")
    late_path = raw_root / "imerg_late" / "2025_Q4.parquet"
    if late_path.exists():
        raw = pd.read_parquet(late_path)
        if not raw.empty:
            points = set(map(tuple, raw[["lat", "lon"]].drop_duplicates().to_numpy()))
            if final_cells is not None and points != final_cells:
                raise ValueError("IMERG Late grid does not match Final regional cells")
            items.append(_regional_area_mean(raw, "IMERG_Late_V07"))
    if not items:
        return pd.DataFrame(columns=["date", "gpm_rain_mm", "gpm_valid_cells", "gpm_product"])
    union = pd.concat(items, ignore_index=True)
    if union.duplicated(["date", "gpm_product"]).any():
        # Final data may overlap between the yearly caches only if corrupted.
        raise ValueError("Duplicate date/product in IMERG caches")
    if union.date.duplicated().any():
        overlaps = union.loc[union.date.duplicated(keep=False), ["date", "gpm_product"]]
        raise ValueError(f"IMERG Final/Late overlap; resolve explicitly:\n{overlaps.head(10)}")
    return union.sort_values("date")


def smap_daily(smap_folder: Path) -> pd.DataFrame:
    files = sorted(smap_folder.glob("smap_daily*.csv"))
    if not files:
        return pd.DataFrame(columns=[
            "date", "smap_surface_m3m3", "smap_soil_temp_c", "smap_samples", "smap_complete_day", "smap_product"
        ])
    data = []
    for file in files:
        df = pd.read_csv(file)
        if not {"date_utc", "sm_surface_m3m3", "soil_temp_layer1_C", "sm_samples"}.issubset(df):
            raise ValueError(f"Invalid SMAP schema in {file}")
        df["date"] = _normalize_dates(df["date_utc"])
        data.append(df)
    union = pd.concat(data, ignore_index=True)
    # Existing validated and new additive ranges may overlap. They must agree.
    for date, group in union.groupby("date"):
        for col in ("sm_surface_m3m3", "soil_temp_layer1_C"):
            values = pd.to_numeric(group[col], errors="coerce").dropna()
            if len(values) > 1 and float(values.max() - values.min()) > 1e-5:
                raise ValueError(f"Conflicting SMAP {col} values for {date.date()}")
    union = union.sort_values(["date", "sm_samples"], ascending=[True, False])
    union = union.drop_duplicates("date", keep="first").copy()
    # An incomplete 3-hourly day is retained in the audit but must not be
    # mistaken for a complete daily mean in the joined feature table.
    if "complete_day" in union:
        complete_flag = union["complete_day"].astype(str).str.strip().str.lower().eq("true")
    else:
        complete_flag = pd.Series(True, index=union.index)
    temp_counts = union["temp_samples"] if "temp_samples" in union else union["sm_samples"]
    union["smap_complete_day"] = (
        complete_flag & union["sm_samples"].eq(8) & temp_counts.eq(8)
    )
    union.loc[~union["smap_complete_day"], ["sm_surface_m3m3", "soil_temp_layer1_C"]] = np.nan
    out = union[["date", "sm_surface_m3m3", "soil_temp_layer1_C", "sm_samples", "smap_complete_day"]].rename(
        columns={
            "sm_surface_m3m3": "smap_surface_m3m3",
            "soil_temp_layer1_C": "smap_soil_temp_c",
            "sm_samples": "smap_samples",
        }
    )
    out["smap_product"] = "NASA_SPL4SMGP_v008"
    return out


def add_vegetation(env: pd.DataFrame, features_dir: Path, min_clear: float) -> pd.DataFrame:
    # The new all-season Sentinel-2 processor writes a stable filename;
    # old 2024-2025 CSVs remain supported for users who already processed them.
    sentinel = features_dir / "sentinel2_aligned_evia_pilot.csv"
    if not sentinel.exists():
        sentinel = features_dir / "sentinel2_aligned_evia_pilot_2024_2025.csv"
    sources = [
        (features_dir / "vegetation_observations.csv", "hls", "NASA_HLSL30_v2"),
        (sentinel, "s2", "ESA_Sentinel2_L2A"),
    ]
    for path, prefix, source in sources:
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        if "source" in frame and not frame["source"].eq(source).all():
            raise ValueError(f"Unexpected vegetation source in {path}; expected {source}")
        frame["date"] = _normalize_dates(frame["date_utc"])
        if frame.date.duplicated().any():
            raise ValueError(f"{source}: multiple observations per day; aggregate explicitly")
        valid = frame.ndvi_median.notna() & frame.clear_fraction.ge(min_clear)
        for col in ("ndvi_median", "evi2_median"):
            frame.loc[~valid, col] = np.nan
        frame = frame[["date", "ndvi_median", "evi2_median", "clear_fraction"]].rename(
            columns={
                "ndvi_median": f"{prefix}_ndvi",
                "evi2_median": f"{prefix}_evi2",
                "clear_fraction": f"{prefix}_clear_fraction",
            }
        )
        env = env.merge(frame, on="date", how="left", validate="one_to_one")
    return env


def build_environment(power: pd.DataFrame, gpm: pd.DataFrame, smap: pd.DataFrame,
                      terrain: pd.DataFrame | None = None,
                      vegetation_dir: Path | None = None, min_clear: float = 0.8):
    env = power.copy()
    env["date"] = _normalize_dates(env["date"])
    env = env.sort_values("date").drop_duplicates("date")
    dates = pd.DataFrame({"date": pd.date_range(env.date.min(), env.date.max())})
    env = dates.merge(env, on="date", how="left", validate="one_to_one")
    env = env.merge(gpm, on="date", how="left", validate="one_to_one")
    env = env.merge(smap, on="date", how="left", validate="one_to_one")
    if terrain is not None:
        if len(terrain) != 1 or terrain.iloc[0].get("field_id") != "evia_pilot":
            raise ValueError("SRTM terrain CSV must contain exactly one evia_pilot row")
        for col in ("elevation_m_median", "slope_deg_median", "aspect_deg_circular_mean"):
            if col in terrain:
                env[col] = terrain.iloc[0][col]
    if vegetation_dir:
        env = add_vegetation(env, vegetation_dir, min_clear)
    env["field_id"] = "evia_pilot"
    env["geometry_status"] = "unverified_provisional_candidate_3x3"
    env["gpm_missing"] = env["gpm_rain_mm"].isna()
    env["smap_missing"] = env["smap_surface_m3m3"].isna()
    env["rain_prior_7d_mm"] = env.gpm_rain_mm.shift(1).rolling(7, min_periods=7).sum()
    env["rain_prior_14d_mm"] = env.gpm_rain_mm.shift(1).rolling(14, min_periods=14).sum()
    if "power_temp_c" in env:
        env["temp_prior_7d_c"] = env.power_temp_c.shift(1).rolling(7, min_periods=7).mean()
    env["smap_moisture_prior_7d"] = env.smap_surface_m3m3.shift(1).rolling(7, min_periods=3).mean()
    return env


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--power", type=Path, required=True, help="POWER daily parquet")
    p.add_argument("--min-clear", type=float, default=0.8)
    p.add_argument("--out", type=Path, default=REPO / "data/processed/features/environment_multisource_daily.parquet")
    args = p.parse_args(argv)
    if not 0 <= args.min_clear <= 1:
        p.error("--min-clear should be between 0 and 1")
    data = REPO / "data"
    features = data / "processed" / "features"
    terrain_path = features / "srtm_terrain_evia_pilot.csv"
    terrain = pd.read_csv(terrain_path) if terrain_path.exists() else None
    out = build_environment(
        power=load_power(args.power),
        gpm=imerg_daily(data / "raw"),
        smap=smap_daily(data / "processed" / "evia_sowing" / "smap"),
        terrain=terrain,
        vegetation_dir=features,
        min_clear=args.min_clear,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f"Environment: {len(out)} days from {out.date.min().date()} to {out.date.max().date()}")
    print("Days with IMERG rain:", out.gpm_rain_mm.notna().sum())
    print("Days with SMAP moisture:", out.smap_surface_m3m3.notna().sum())
    print("IMERG by source:", out.gpm_product.value_counts(dropna=True).to_dict())
    for col in ("hls_ndvi", "s2_ndvi"):
        if col in out:
            print(f"{col} usable days:", out[col].notna().sum())
    print("Saved:", args.out)
    print("NOTE: regional and provisional-site features; NOT validated field/crop labels")


if __name__ == "__main__":
    main()
