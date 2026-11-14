"""Resume IMERG Late V07 daily rain for 2025 Q4 without touching Final V07.

Preflight: --plan. One-real-granule test: --smoke-test. Full: --workers 2.
The pre-existing `download_imerg_daily` module provides verified auth and
NetCDF regional extraction. Requires its updated Earthdata-token version.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import earthaccess
import pandas as pd

from . import download_imerg_daily as final

PRODUCT = "GPM_3IMERGDL"
VERSION = "07"
START = "2025-10-01"
END = "2025-12-31"


def canonical_dates(granules):
    """Deduplicate CMR records by date, retaining a stable per-day choice."""
    chosen = {}
    for granule in granules:
        date = final._date_of(granule)
        if START <= date <= END:
            chosen[date] = granule
    return dict(sorted(chosen.items()))


def consolidate(rows: list[pd.DataFrame]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "lat", "lon", "precip_mm", "source"])
    frame = pd.concat(rows, ignore_index=True)
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.drop_duplicates(["date", "lat", "lon"], keep="last")
    frame["source"] = "IMERG_Late_V07"
    return frame.sort_values(["date", "lat", "lon"]).reset_index(drop=True)


def area_mean(frame: pd.DataFrame) -> pd.DataFrame:
    west, east, south, north = final.STUDY_AREA
    inside = frame[
        frame.lat.between(south - 0.05, north + 0.05)
        & frame.lon.between(west - 0.05, east + 0.05)
    ]
    if inside.empty:
        raise ValueError("No Late Run cells inside the project area")
    out = inside.groupby("date", as_index=False).agg(
        precip_mm=("precip_mm", "mean"),
        valid_cells=("precip_mm", "count"),
    )
    out["source"] = "IMERG_Late_V07"
    return out


def save(frame: pd.DataFrame, output: Path, summary: Path) -> None:
    if frame.empty:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".partial.parquet")
    frame.to_parquet(temporary, index=False)
    temporary.replace(output)
    mean = area_mean(frame)
    temporary_summary = summary.with_name(summary.stem + ".partial.parquet")
    mean.to_parquet(temporary_summary, index=False)
    temporary_summary.replace(summary)
    print(f"IMERG Late: {frame.date.nunique()} unique Q4 dates cached", flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    p.add_argument("--plan", action="store_true")
    p.add_argument("--smoke-test", action="store_true")
    args = p.parse_args(argv)
    output = final.RAW / "imerg_late" / "2025_Q4.parquet"
    summary = final.PROC / "imerg_late_area_mean_2025Q4.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)

    if not args.plan:
        final.authenticate()
    granules = earthaccess.search_data(
        short_name=PRODUCT,
        version=VERSION,
        temporal=(START, END),
        bounding_box=(
            final.STUDY_AREA[0], final.STUDY_AREA[2],
            final.STUDY_AREA[1], final.STUDY_AREA[3],
        ),
    )
    by_day = canonical_dates(granules)
    expected = set(pd.date_range(START, END).strftime("%Y-%m-%d"))
    missing_catalog = sorted(expected - by_day.keys())
    previous = pd.read_parquet(output) if output.exists() else consolidate([])
    done = set(pd.to_datetime(previous.date).dt.strftime("%Y-%m-%d"))
    missing = [(day, g) for day, g in by_day.items() if day not in done]
    print(
        f"IMERG Late V07 Q4: {len(by_day)}/92 catalog days, "
        f"{len(done)} cached, {len(missing)} to download", flush=True
    )
    if missing_catalog:
        print("WARNING: Missing catalog dates:", missing_catalog[:15])
    if args.plan:
        return
    if not by_day:
        raise SystemExit("No NASA CMR Late Run granules found")
    if args.smoke_test:
        granule = (missing[0][1] if missing else next(iter(by_day.values())))
        sample = final.read(granule, output.parent)
        print("Smoke test:", final._date_of(granule), len(sample), "regional cells")
        print(sample.head().to_string(index=False))
        return

    rows = [previous] if len(previous) else []
    consecutive_failures = 0
    for offset in range(0, len(missing), args.workers * 2):
        batch = missing[offset: offset + args.workers * 2]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            tasks = [(day, pool.submit(final.read, granule, output.parent))
                     for day, granule in batch]
            for day, task in tasks:
                try:
                    result = task.result()
                    rows.append(result)
                    consecutive_failures = 0
                except Exception as exc:
                    print(f"WARNING: IMERG Late {day}: {type(exc).__name__}", flush=True)
                    consecutive_failures += 1
                    if type(exc).__name__ == "EulaNotAccepted" or consecutive_failures >= 5:
                        save(consolidate(rows), output, summary)
                        raise SystemExit("NASA access/download issue. Rerun to resume.") from None
        save(consolidate(rows), output, summary)

    all_data = consolidate(rows)
    save(all_data, output, summary)
    present = set(all_data.date.dt.strftime("%Y-%m-%d"))
    remaining = sorted(expected - present)
    manifest = {
        "product": PRODUCT,
        "version": VERSION,
        "run": "Late",
        "period": [START, END],
        "catalog_days": len(by_day),
        "downloaded_days": len(present),
        "missing_days": remaining,
        "units": "mm/day",
        "note": "Late Run V07; do not label these observations as Final Run",
    }
    (output.parent / "2025_Q4_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"IMERG Late Q4: {len(present)}/92 days; {len(remaining)} missing")


if __name__ == "__main__":
    main()
