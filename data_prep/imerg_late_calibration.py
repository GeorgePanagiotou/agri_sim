"""Calibrate GPM IMERG Late Run (GPM_3IMERGDL v07) to IMERG Final for the study area.

IMERG Final is gauge-adjusted and arrives ~3.5 months late; the Late Run fills the gap up to yesterday but is not
gauge-adjusted. Over Evia, Late/Final on the same days was ~1.0 in 2019-2022 but 1.2-1.5 in 2023-2025, so
un-corrected Late days make the live season look wetter than the Final record the engines and the ML table use.

This script downloads Late for days that Final also covers (default 2019-01-01 .. last Final day; same cells,
OPeNDAP, ~600 bytes per day), compares area means, and writes one multiplicative factor per half-year (Oct-Mar,
Apr-Sep; Final total / Late total) from the last 3 complete agricultural years, because the bias drifts. The file
lists it per calendar month, with per-month diagnostics over all years, and prints a per-year drift table.

Outputs
- data/raw/imerg_late_overlap/<YYYY>.parquet   Late on Final days (cache; a complete year is skipped on re-run)
- data/processed/imerg_late_to_final.csv       month, factor, overlap days, Final mm, Late mm, wet-day shares

Readers (agrisim.data_sources.imerg_late_calibration) multiply Late days by the factor of their month. The raw
Late files stay unchanged.

    ..\\.venv\\Scripts\\python.exe data_prep\\imerg_late_calibration.py [start YYYY-MM-DD] [end YYYY-MM-DD]
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import earthaccess

import earthdata  # login: Settings (env) or ~/.netrc
import numpy as np
import pandas as pd

import download_imerg_late as dl
from config import PROC, RAW

CACHE = RAW / "imerg_late_overlap"
OUT = PROC / "imerg_late_to_final.csv"
WET_MM = 1.0
RECENT_YEARS = 3


def final_daily() -> pd.DataFrame:
    files = sorted((RAW / "imerg_daily").glob("[12][0-9][0-9][0-9].parquet"))
    if not files:
        raise SystemExit("No IMERG Final cache; run download_imerg_daily.py first")
    f = pd.concat(pd.read_parquet(p) for p in files)
    f["date"] = pd.to_datetime(f["date"]).dt.normalize()
    return f


def fetch(start: pd.Timestamp, end: pd.Timestamp) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = []
    for year in range(start.year, end.year + 1):
        a, b = max(start, pd.Timestamp(f"{year}-01-01")), min(end, pd.Timestamp(f"{year}-12-31"))
        path = CACHE / f"{year}.parquet"
        if path.exists() and pd.read_parquet(path, columns=["date"]).date.nunique() >= (b - a).days + 1 - 3:
            print(f"  {path.name}: exists, skipping")
            continue
        todo.append((year, a, b))
    if not todo:
        return
    earthdata.login()
    session = earthaccess.get_requests_https_session()
    for year, a, b in todo:
        granules = earthaccess.search_data(short_name="GPM_3IMERGDL", version="07",
                                           temporal=(a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")))
        with ThreadPoolExecutor(6) as pool:
            frames = [f for f in pool.map(lambda g: dl.read(session, g), granules) if f is not None]
        if not frames:
            print(f"  {year}: nothing read")
            continue
        data = pd.concat(frames).drop_duplicates(["date", "lat", "lon"]).sort_values(["date", "lat", "lon"])
        data.loc[data.precip_mm < 0, "precip_mm"] = np.nan
        data.to_parquet(CACHE / f"{year}.parquet", index=False)
        print(f"  {year}.parquet: {data.date.nunique()} days", flush=True)


WET_HALF = (10, 11, 12, 1, 2, 3)


def area_means(late: pd.DataFrame, final: pd.DataFrame) -> pd.DataFrame:
    for d in (late, final):
        d["lat"], d["lon"] = d.lat.round(2), d.lon.round(2)
    m = late.merge(final, on=["date", "lat", "lon"], suffixes=("_late", "_final"))
    area = m.groupby("date")[["precip_mm_late", "precip_mm_final"]].mean().dropna()
    area["agyear"] = area.index.year + (area.index.month >= 10)
    area["half"] = np.where(area.index.month.isin(WET_HALF), "Oct-Mar", "Apr-Sep")
    return area


def fit(area: pd.DataFrame, recent_years: int) -> pd.DataFrame:
    """One factor per half-year (Oct-Mar, Apr-Sep) from the last `recent_years` complete agricultural years.

    The Late/Final ratio drifts: over Evia, winters 2019-2022 were ~1.0, winters 2023-2025 1.2-1.5. The live
    season is closest to the recent years, and 3 years are too few for 12 stable monthly factors."""
    complete = area.groupby("agyear").size()
    years = list(complete[complete >= 360].index)[-recent_years:]
    fitw = area[area.agyear.isin(years)]
    rows = []
    for month in range(1, 13):
        half = "Oct-Mar" if month in WET_HALF else "Apr-Sep"
        part = fitw[fitw.half == half]
        own = area[area.index.month == month]
        rows.append({
            "month": month, "half": half,
            "factor": round(part.precip_mm_final.sum() / part.precip_mm_late.sum(), 3),
            "fit_years": f"{years[0]}-{years[-1]}",
            "overlap_days_own_month_all_years": len(own),
            "final_mm_own_month_all_years": round(own.precip_mm_final.sum(), 1),
            "late_mm_own_month_all_years": round(own.precip_mm_late.sum(), 1),
            "wet_day_share_final": round(float((own.precip_mm_final >= WET_MM).mean()), 3),
            "wet_day_share_late": round(float((own.precip_mm_late >= WET_MM).mean()), 3),
        })
    out = pd.DataFrame(rows)
    by_year = area.groupby(["agyear", "half"])[["precip_mm_late", "precip_mm_final"]].sum()
    by_year = (by_year.precip_mm_late / by_year.precip_mm_final).unstack("half").round(2)
    out.attrs["summary"] = (f"{len(area)} overlap days {area.index.min().date()}..{area.index.max().date()}; "
                            f"Late/Final all years {area.precip_mm_late.sum() / area.precip_mm_final.sum():.2f}; "
                            f"daily r {area[['precip_mm_late', 'precip_mm_final']].corr().iloc[0, 1]:.3f}; "
                            f"factors fitted on agricultural years {years[0]}-{years[-1]}\n"
                            f"Late/Final by agricultural year (drift check):\n{by_year.to_string()}")
    return out


def main():
    final = final_daily()
    start = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else pd.Timestamp("2019-01-01")
    end = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else final.date.max()
    fetch(start, end)
    late = pd.concat(pd.read_parquet(p) for p in sorted(CACHE.glob("[12][0-9][0-9][0-9].parquet")))
    late["date"] = pd.to_datetime(late["date"]).dt.normalize()
    late = late[(late.date >= start) & (late.date <= end)]
    table = fit(area_means(late, final), RECENT_YEARS)
    PROC.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)
    print(table.attrs["summary"])
    print(table.to_string(index=False))
    print("->", OUT)


if __name__ == "__main__":
    main()
