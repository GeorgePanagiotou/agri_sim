"""GPM IMERG daily (0.1 deg): Final Run where it exists, then the Late Run scaled to the Final level.

Served from the area's local files (written by the data pipeline, data_prep/):
- imerg_daily_2001_2025.parquet   IMERG Final (GPM_3IMERGDF v07), gauge-adjusted, ends ~3.5 months back
- imerg_late_daily.parquet        IMERG Late (GPM_3IMERGDL v07), up to yesterday, raw values
- imerg_late_to_final.csv         monthly Late -> Final factors (data_prep/imerg_late_calibration.py)

Late is not gauge-adjusted: over Evia it ran 20-50 % wetter than Final in 2023-2025, so Late days are multiplied by
the factor of their month. Final always wins on days both have. Why local and not live: IMERG needs an Earthdata
login, and the files carry only the cells around each prepared area.

Area -> value: plain mean over the 0.1 deg cells that overlap the area (the rule of data_prep/download_imerg_daily.py,
imerg_daily_area_mean.parquet).
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

from ..areas import Area
from ..config import Settings
from ..variables import SourceVar
from .base import Fetched, NoData, ProviderError

HALF = 0.05   # half a cell
EPS = 1e-6
FINAL = "imerg_daily_2001_2025.parquet"
LATE = "imerg_late_daily.parquet"
FACTORS = "imerg_late_to_final.csv"


@lru_cache(maxsize=8)
def _read(path: str, mtime_ns: int) -> pd.DataFrame:  # mtime in the key = reload when the file changes
    df = pd.read_parquet(path, columns=["date", "lat", "lon", "precip_mm"])
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df


def _load(path: Path) -> pd.DataFrame | None:
    try:
        return _read(str(path), path.stat().st_mtime_ns)
    except FileNotFoundError:
        return None


def _factors(path: Path) -> pd.Series | None:
    if not path.exists():
        return None
    f = pd.read_csv(path).set_index("month")["factor"]
    if sorted(f.index) != list(range(1, 13)) or not f.between(0.2, 5).all():
        raise ProviderError(f"{path.name}: expected 12 monthly factors between 0.2 and 5")
    return f


def _cells(df: pd.DataFrame, area: Area) -> pd.DataFrame:
    cells = df.drop_duplicates(["lat", "lon"])
    return cells[cells.lat.between(area.south - HALF - EPS, area.north + HALF + EPS)
                 & cells.lon.between(area.west - HALF - EPS, area.east + HALF + EPS)]


def _area_mean(df: pd.DataFrame, sel: pd.DataFrame, start: date, end: date, col: str) -> pd.Series:
    keys = pd.MultiIndex.from_frame(sel[["lat", "lon"]])
    sub = df[pd.MultiIndex.from_frame(df[["lat", "lon"]]).isin(keys)]
    sub = sub[(sub.date >= pd.Timestamp(start)) & (sub.date <= pd.Timestamp(end))]
    series = sub.groupby("date")[col].mean()
    series.index = pd.DatetimeIndex(series.index)
    return series


class ImergProvider:
    name = "imerg"
    title = "GPM IMERG daily: Final Run (GPM_3IMERGDF v07), then Late Run (GPM_3IMERGDL v07) scaled to Final"
    native_resolution = "0.1° x 0.1° (~10 km)"
    reference = "Huffman et al., NASA GES DISC, https://gpm.nasa.gov/data/imerg"

    def __init__(self, settings: Settings):
        self.s = settings

    def fetch(self, var: SourceVar, area: Area, start: date, end: date) -> Fetched:
        if area.data_dir is None:
            raise NoData("no prepared area contains this location; IMERG is served only for prepared areas "
                         "(python -m agrisim.pipelines.prepare_area --name <name> --bbox ...)")
        final = _load(area.data_dir / FINAL)
        if final is None:
            raise ProviderError(f"{FINAL} not found for area {area.home!r} ({area.data_dir})")
        sel = _cells(final, area)
        if sel.empty:
            raise NoData(f"no IMERG cells cached for this area; cached extent lon {final.lon.min() - HALF:.2f}.."
                         f"{final.lon.max() + HALF:.2f}, lat {final.lat.min() - HALF:.2f}..{final.lat.max() + HALF:.2f}")
        series = _area_mean(final, sel, start, end, var.native) * var.factor
        final_end = final.date.max()
        notes, extra = [], {"cells": [[round(float(r.lon), 2), round(float(r.lat), 2)] for r in sel.itertuples()],
                            "final_until": str(final_end.date())}
        late = _load(area.data_dir / LATE)
        if late is not None and pd.Timestamp(end) > final_end:
            late = late[late.date > final_end]            # Final wins wherever it exists
            factors = _factors(area.data_dir / FACTORS)
            if factors is not None:
                late = late.assign(**{var.native: late[var.native] * late.date.dt.month.map(factors).to_numpy()})
            ls = _area_mean(late, _cells(late, area), start, end, var.native) * var.factor
            if len(ls):
                series = pd.concat([series, ls]).sort_index()
                if factors is not None:
                    span = sorted(set(factors.round(3)))
                    notes.append(f"from {(final_end + pd.Timedelta(days=1)).date()}: IMERG Late Run (provisional, "
                                 f"not gauge-adjusted) scaled to the Final level, factor {', '.join(map(str, span))}")
                else:
                    notes.append(f"from {(final_end + pd.Timedelta(days=1)).date()}: IMERG Late Run, UNCORRECTED "
                                 f"({FACTORS} missing; Late reads wetter than Final)")
                extra["late_days"] = int(ls.notna().sum())
        if series.empty:
            raise NoData(f"IMERG covers {final.date.min().date()}..{(late.date.max() if late is not None and len(late) else final_end).date()}, "
                         "nothing in the requested period")
        return Fetched(series=series, origin="local", n_cells=len(sel),
                       method="mean of the 0.1° cells overlapping the area", notes=notes, extra=extra)
