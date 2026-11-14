"""Additive, resumable acquisition of NASA SPL4SMGP v008 at the Evia pilot.

This module calls the project's existing, validated NASA CMR/OPeNDAP
point reader. It does NOT overwrite the original smap_daily.csv file.

Example:
  uv run --env-file .env python -m agrisim.data_sources.download_evia_smap_range \
      --start 2024-02-01 --end 2024-06-30 --workers 4 --plan
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
import getpass
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import download_evia_smap as base


def expected_slots(start: str, end: str) -> list[str]:
    days = pd.date_range(start, end, freq="D")
    if days.empty:
        raise ValueError("The range must contain at least one day")
    return [
        (day.to_pydatetime() + timedelta(hours=hour, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for day in days
        for hour in range(1, 24, 3)
    ]


def existing_records(manifest: pd.DataFrame) -> dict[str, dict]:
    """Return only checkpoint rows belonging to this catalog/version."""
    active = manifest.set_index("time_utc")["concept_id"].to_dict()
    records = {}
    for file in sorted(base.CACHE.glob("points_*.csv")):
        frame = pd.read_csv(file)
        if "time_utc" not in frame or "concept_id" not in frame:
            continue
        for row in frame.to_dict("records"):
            if active.get(row["time_utc"]) == row["concept_id"]:
                records[row["time_utc"]] = row
    return records


def upsert_months(records: dict[str, dict], dirty_months: set[str]) -> None:
    """Never drop previously downloaded observations from a monthly checkpoint."""
    for month in sorted(dirty_months):
        fresh = pd.DataFrame(
            [value for key, value in records.items() if key.startswith(month)]
        )
        if fresh.empty:
            continue
        target = base.CACHE / f"points_{month}.csv"
        if target.exists():
            previous = pd.read_csv(target)
            fresh = pd.concat([previous, fresh], ignore_index=True)
        fresh = fresh.drop_duplicates("time_utc", keep="last").sort_values("time_utc")
        base.atomic_csv(fresh, target)


def make_daily(manifest: pd.DataFrame, records: dict[str, dict], start: str, end: str):
    """Expose catalog gaps as missing samples, not zeros."""
    timestamps = expected_slots(start, end)
    if manifest.time_utc.duplicated().any():
        raise ValueError("Duplicate SMAP catalog timestamps")
    if not set(manifest.time_utc).issubset(timestamps):
        raise ValueError("SMAP granule outside expected 3-hourly times")
    frame = pd.DataFrame({"time_utc": timestamps})
    matched = [records[key] for key in manifest.time_utc if key in records]
    if matched:
        measured = pd.DataFrame(matched).drop_duplicates("time_utc")
        frame = frame.merge(measured, on="time_utc", how="left", validate="one_to_one")
    else:
        for name in (
            "granule", "concept_id", "sm_surface_m3m3", "soil_temp_layer1_K"
        ):
            frame[name] = np.nan
    frame["soil_temp_layer1_C"] = pd.to_numeric(
        frame["soil_temp_layer1_K"], errors="coerce"
    ) - 273.15
    frame["row"] = base.ROW
    frame["col"] = base.COL
    frame["date_utc"] = frame.time_utc.str[:10]
    daily = frame.groupby("date_utc", as_index=False).agg(
        sm_surface_m3m3=("sm_surface_m3m3", "mean"),
        sm_samples=("sm_surface_m3m3", "count"),
        soil_temp_layer1_C=("soil_temp_layer1_C", "mean"),
        temp_samples=("soil_temp_layer1_C", "count"),
        granules=("granule", "count"),
    )
    daily["complete_day"] = daily.sm_samples.eq(8) & daily.temp_samples.eq(8)
    return frame, daily


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, help="Inclusive UTC date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="Inclusive UTC date YYYY-MM-DD")
    p.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    p.add_argument("--plan", action="store_true", help="Catalog/cache count; no point downloads")
    p.add_argument("--refresh-catalog", action="store_true")
    a = p.parse_args(argv)
    start, end = str(pd.Timestamp(a.start).date()), str(pd.Timestamp(a.end).date())
    if start > end:
        p.error("--start must precede --end")
    if (pd.Timestamp(end) - pd.Timestamp(start)).days > 370:
        p.error("Use ranges <=371 days for manageable, resumable downloads")
    base.CACHE.mkdir(parents=True, exist_ok=True)
    base.OUT.mkdir(parents=True, exist_ok=True)

    manifest = base.catalog(start, end, a.refresh_catalog).sort_values("time_utc")
    records = existing_records(manifest)
    missing = [row for row in manifest.itertuples(index=False) if row.time_utc not in records]
    slots = expected_slots(start, end)
    print(
        f"SMAP {start} to {end}: {len(manifest)}/{len(slots)} granules cataloged, "
        f"{len(records)} cached, {len(missing)} points remaining", flush=True
    )
    if a.plan:
        return

    if missing:
        token = os.getenv("EARTHDATA_TOKEN", "").strip() or getpass.getpass(
            "Earthdata token (hidden): "
        ).strip()
        if not token:
            raise SystemExit("EARTHDATA_TOKEN required for missing SMAP points")
        # Check one point before scheduling concurrent requests.
        initial = base.fetch(missing[0], token)
        records[initial["time_utc"]] = initial
        upsert_months(records, {initial["time_utc"][:7]})
        pending = missing[1:]
        failures = []
        dirty = set()
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            tasks = {pool.submit(base.fetch, item, token): item for item in pending}
            for index, future in enumerate(as_completed(tasks), 1):
                item = tasks[future]
                try:
                    point = future.result()
                    records[point["time_utc"]] = point
                    dirty.add(point["time_utc"][:7])
                except Exception as exc:
                    failures.append((item.time_utc, type(exc).__name__))
                if index % 32 == 0 or index == len(tasks):
                    upsert_months(records, dirty)
                    dirty.clear()
                    print(
                        f"SMAP {len(records)}/{len(manifest)} cached; "
                        f"{len(failures)} failures", flush=True
                    )
        if failures:
            raise SystemExit(
                f"SMAP: {len(failures)} points failed; first {failures[0]}. "
                "Rerun the same command to resume."
            )

    three_hourly, daily = make_daily(manifest, records, start, end)
    suffix = f"{start}_{end}"
    base.atomic_csv(three_hourly, base.OUT / f"smap_3hourly_{suffix}.csv")
    base.atomic_csv(daily, base.OUT / f"smap_daily_{suffix}.csv")
    base.atomic_csv(manifest, base.OUT / f"granules_{suffix}.csv")
    print(
        f"Saved {len(daily)} SMAP daily rows, {int(daily.complete_day.sum())} "
        f"complete; output smap_daily_{suffix}.csv", flush=True
    )


if __name__ == "__main__":
    main()
