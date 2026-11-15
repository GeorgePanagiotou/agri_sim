"""GPM IMERG Final daily (0.1 deg), served from data/processed/imerg_daily_2001_2025.parquet.

Why local: IMERG needs an Earthdata login, and GES DISC is retiring the OPeNDAP the download script uses
(docs/DATA.md, "Access risk"). The parquet has the cells around the study area; extend it with
data_prep/download_imerg_daily.py, the service picks the new file up without a restart.

Area -> value: plain mean over the 0.1 deg cells that overlap the area. This is the same rule as
data_prep/download_imerg_daily.py (imerg_daily_area_mean.parquet), so the numbers match the repo.
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
FILE = "imerg_daily_2001_2025.parquet"


@lru_cache(maxsize=2)
def _read(path: str, mtime_ns: int) -> pd.DataFrame:  # mtime in the key = reload when the file changes
    return pd.read_parquet(path, columns=["date", "lat", "lon", "precip_mm"])


def _load(path: Path) -> pd.DataFrame:
    try:
        return _read(str(path), path.stat().st_mtime_ns)
    except FileNotFoundError:
        raise ProviderError(f"{path.name} not found in DATA_DIR ({path.parent})") from None


class ImergProvider:
    name = "imerg"
    title = "GPM IMERG Final Run, daily (GPM_3IMERGDF v07)"
    native_resolution = "0.1° x 0.1° (~10 km)"
    reference = "Huffman et al., NASA GES DISC, https://gpm.nasa.gov/data/imerg"

    def __init__(self, settings: Settings):
        self.path = settings.data_dir / FILE

    def fetch(self, var: SourceVar, area: Area, start: date, end: date) -> Fetched:
        df = _load(self.path)
        cells = df.drop_duplicates(["lat", "lon"])
        sel = cells[cells.lat.between(area.south - HALF - EPS, area.north + HALF + EPS)
                    & cells.lon.between(area.west - HALF - EPS, area.east + HALF + EPS)]
        if sel.empty:
            raise NoData(f"no IMERG cells cached for this area; cached extent lon {cells.lon.min() - HALF:.2f}.."
                         f"{cells.lon.max() + HALF:.2f}, lat {cells.lat.min() - HALF:.2f}..{cells.lat.max() + HALF:.2f}")
        keys = pd.MultiIndex.from_frame(sel[["lat", "lon"]])
        sub = df[pd.MultiIndex.from_frame(df[["lat", "lon"]]).isin(keys)]
        sub = sub[(sub.date >= pd.Timestamp(start)) & (sub.date <= pd.Timestamp(end))]
        if sub.empty:
            raise NoData(f"IMERG cache covers {df.date.min().date()}..{df.date.max().date()}, nothing in the requested period")
        series = sub.groupby("date")[var.native].mean() * var.factor
        series.index = pd.DatetimeIndex(series.index)
        return Fetched(series=series, origin="local", n_cells=len(sel),
                       method="mean of the 0.1° cells overlapping the area",
                       extra={"cells": [[round(float(r.lon), 2), round(float(r.lat), 2)] for r in sel.itertuples()]})
