"""Download NASA GPM IMERG Final v07 daily rain for the North Evia study area.

Uses the Earthdata token from the repository-root .env, official CMR granule
links, and earthaccess.download. The retired on-premises GES DISC OPeNDAP URL
is NOT used. Each global NetCDF granule is downloaded to a temporary folder,
subset locally to nearby 0.1-degree cells, then deleted. The small Parquet
outputs remain compatible with the rest of AgriSim AI.

First test only ONE day (does not publish datasets)::

    uv run python -m agrisim.data_sources.download_imerg_daily --smoke-test

Then download a year::

    uv run python -m agrisim.data_sources.download_imerg_daily \
        --first-year 2023 --last-year 2023 --workers 2

Requires a *new*, unshared Earthdata token in the local .env file::

    EARTHDATA_TOKEN=<your replacement token>

A token does not grant approval of any outstanding GES DISC access agreement.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import earthaccess
import numpy as np
import pandas as pd
import xarray as xr
from dotenv import load_dotenv

from .config import PROC, RAW, REPO, STUDY_AREA

PRODUCT = "GPM_3IMERGDF"
VERSION = "07"


def authenticate() -> None:
    """Load only the local .env and use Earthdata's token login strategy."""
    env_file = Path(REPO) / ".env"
    # Already-supplied process variables take precedence over .env.
    load_dotenv(dotenv_path=env_file, override=False)
    if not os.getenv("EARTHDATA_TOKEN", "").strip():
        raise SystemExit(
            f"Missing EARTHDATA_TOKEN. Add it to {env_file} (not .env.example). "
            "Do not commit .env or share your token."
        )
    try:
        auth = earthaccess.login(strategy="environment")
    except Exception as exc:
        # Avoid leaking a token through an exception message.
        raise SystemExit(
            f"Earthdata token authentication failed ({type(exc).__name__}). "
            "Check that your token is current, then retry."
        ) from None
    if not auth or not auth.authenticated:
        raise SystemExit("Earthdata token authentication did not succeed")
    print("Earthdata environment-token authentication initialized")


def _date_of(granule) -> str:
    return granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10]


def _require_precip_units(units: str | None) -> None:
    if units and units.lower().replace(" ", "") not in {"mm/day", "mmday-1", "mmd-1", "mm/d"}:
        raise ValueError(f"Unexpected IMERG precipitation units: {units!r} (expected mm/day)")


def extract_regional_precip(path: Path, day: str, area=STUDY_AREA, pad=0.1) -> pd.DataFrame:
    """Load only the regional cells from a daily IMERG v07 NetCDF granule.

    Product documentation defines 'precipitation' in mm/day. Longitude in the
    output is normalized to [-180, 180]. Neither the regional cells nor their
    mean constitute field-scale rainfall measurements.
    """
    west, east, south, north = area
    with xr.open_dataset(path, engine="h5netcdf", mask_and_scale=True) as ds:
        if "precipitation" not in ds:
            raise ValueError("IMERG NetCDF has no 'precipitation' variable")
        if "lat" not in ds or "lon" not in ds:
            raise ValueError("IMERG NetCDF is missing lat/lon coordinates")

        _require_precip_units(ds["precipitation"].attrs.get("units"))
        lats = np.asarray(ds["lat"].values)
        lons = np.asarray(ds["lon"].values)
        canonical_lons = (lons + 180) % 360 - 180
        latitude_indices = np.flatnonzero((lats >= south - pad) & (lats <= north + pad))
        longitude_indices = np.flatnonzero(
            (canonical_lons >= west - pad) & (canonical_lons <= east + pad)
        )
        if not len(latitude_indices) or not len(longitude_indices):
            raise ValueError("No native IMERG cells intersect the study-area window")

        subset = ds["precipitation"].isel(
            lat=latitude_indices, lon=longitude_indices
        ).squeeze(drop=True)
        if set(subset.dims) != {"lat", "lon"}:
            raise ValueError(f"Unexpected IMERG precipitation dimensions: {subset.dims}")
        subset = subset.transpose("lat", "lon")
        frame = subset.to_dataframe(name="precip_mm").reset_index()

    frame["lon"] = (frame["lon"] + 180) % 360 - 180
    frame["precip_mm"] = pd.to_numeric(frame["precip_mm"], errors="coerce")
    frame.loc[frame.precip_mm < 0, "precip_mm"] = float("nan")
    frame.insert(0, "date", pd.Timestamp(day))
    return frame[["date", "lat", "lon", "precip_mm"]]


def read(granule, tmp_parent: Path) -> pd.DataFrame:
    """Download one authentic CMR granule, extract regional values, delete it."""
    day = _date_of(granule)
    with tempfile.TemporaryDirectory(prefix="imerg_", dir=str(tmp_parent)) as directory:
        # CMR's current direct-data URL is passed through unchanged.
        # earthaccess handles Earthdata authorization and redirects.
        files = earthaccess.download([granule], local_path=directory, threads=1)
        paths = [Path(p) for p in files]
        if not paths or not paths[0].is_file():
            raise RuntimeError(f"IMERG {day}: no downloaded NetCDF file")
        return extract_regional_precip(paths[0], day)


def _save_year(year: int, rows: list[pd.DataFrame], output: Path) -> pd.DataFrame | None:
    if not rows:
        return None
    frame = pd.concat(rows, ignore_index=True)
    frame = frame.drop_duplicates(["date", "lat", "lon"])
    frame = frame.sort_values(["date", "lat", "lon"])
    frame.to_parquet(output, index=False)
    print(f"{year}: {frame.date.nunique()} days cached", flush=True)
    return frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-year", type=int, default=2023)
    parser.add_argument("--last-year", type=int, default=2024)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=2)
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Download and extract one granule, then exit without publishing Parquet files",
    )
    args = parser.parse_args(argv)
    if args.first_year < 2000 or args.last_year < args.first_year:
        parser.error("Provide an ascending year range starting in 2000 or later")

    cache = RAW / "imerg_daily"
    cache.mkdir(parents=True, exist_ok=True)
    PROC.mkdir(parents=True, exist_ok=True)
    authenticate()

    selected = []
    for year in range(args.first_year, args.last_year + 1):
        output = cache / f"{year}.parquet"
        previous = pd.read_parquet(output) if output.exists() else None
        print(f"Searching NASA CMR for IMERG Final v07 in {year}...", flush=True)
        granules = earthaccess.search_data(
            short_name=PRODUCT,
            version=VERSION,
            temporal=(f"{year}-01-01", f"{year}-12-31"),
            bounding_box=(STUDY_AREA[0], STUDY_AREA[2], STUDY_AREA[1], STUDY_AREA[3]),
        )
        granules = [g for g in granules if _date_of(g).startswith(str(year))]
        granules.sort(key=_date_of)
        if not granules:
            print(f"{year}: no published IMERG Final granules found", flush=True)
            continue

        done = set(previous.date.dt.strftime("%Y-%m-%d")) if previous is not None else set()
        missing = [g for g in granules if _date_of(g) not in done]
        if args.smoke_test:
            target = missing[0] if missing else granules[0]
            print(f"Smoke test: {_date_of(target)}", flush=True)
            try:
                frame = read(target, cache)
            except Exception as exc:
                if type(exc).__name__ == "EulaNotAccepted":
                    raise SystemExit(
                        "NASA denied access to this IMERG file (EulaNotAccepted). "
                        "Accept any outstanding GES DISC EULA and authorize its archive "
                        "in your Earthdata account. A token alone does not grant access."
                    ) from None
                raise
            print(f"Success: {len(frame)} regional cells, units mm/day")
            print(frame.to_string(index=False))
            return

        rows = [previous] if previous is not None else []
        # Bounded batches keep intermediate work resumable without retaining
        # global files, and prevent unbounded concurrent full-globe downloads.
        batch_size = min(8, args.workers * 2)
        consecutive_failures = 0
        for offset in range(0, len(missing), batch_size):
            chunk = missing[offset:offset + batch_size]
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [(g, pool.submit(read, g, cache)) for g in chunk]
                for granule, future in futures:
                    day = _date_of(granule)
                    try:
                        result = future.result()
                    except Exception as exc:
                        if type(exc).__name__ == "EulaNotAccepted":
                            _save_year(year, rows, output)
                            raise SystemExit(
                                "NASA denied IMERG access (EulaNotAccepted). Review GES DISC "
                                "agreements/authorized apps in Earthdata Login; your token "
                                "cannot bypass this restriction."
                            ) from None
                        consecutive_failures += 1
                        print(f"WARNING: IMERG {day}: {type(exc).__name__}", flush=True)
                        if consecutive_failures >= 5:
                            _save_year(year, rows, output)
                            raise SystemExit(
                                "Five consecutive IMERG downloads failed. Stopping rather "
                                "than retrying an entire year. Verify NASA access."
                            ) from None
                        continue
                    consecutive_failures = 0
                    rows.append(result)
            _save_year(year, rows, output)
        if output.exists():
            selected.append(pd.read_parquet(output))
            print(f"{year}: {selected[-1].date.nunique()} daily observations cached "
                  f"({len(granules)} cataloged)", flush=True)

    if not selected:
        raise SystemExit("No NASA IMERG observations downloaded or cached")
    allp = pd.concat(selected, ignore_index=True).sort_values(["date", "lat", "lon"])
    allp.to_parquet(PROC / f"imerg_daily_{args.first_year}_{args.last_year}.parquet", index=False)
    west, east, south, north = STUDY_AREA
    inside = allp[
        allp.lat.between(south - 0.05, north + 0.05)
        & allp.lon.between(west - 0.05, east + 0.05)
    ]
    if inside.empty:
        raise RuntimeError("No IMERG cells overlap the study area")
    inside.groupby("date").precip_mm.mean().to_frame().to_parquet(
        PROC / f"imerg_area_mean_{args.first_year}_{args.last_year}.parquet"
    )
    print(f"Saved {allp.date.nunique()} IMERG daily observations, 0.1-degree regional cells")


if __name__ == "__main__":
    main()
