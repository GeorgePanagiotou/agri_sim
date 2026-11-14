"""Past-only daily climate indicators and calendar-day percentile baselines (ETCCDI style).

Every "prior" indicator for date d uses completed days d-N .. d-1 only, i.e. what was known at the start of day d.
Missing input days make a strict window NaN; nothing is filled with zeros.

Calendar baselines compare a value with the same calendar dates (+/- a half window, circular over the year) in a
fixed reference period, so "dry" or "hot" always means "unusual for this time of year in this place".
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def calendar_day(dates) -> np.ndarray:
    """Day of year 1..365 with 29 February mapped onto 28 February (day 59)."""
    d = pd.DatetimeIndex(dates)
    doy = d.dayofyear.to_numpy()
    return np.where(d.is_leap_year & (doy > 59), doy - 1, doy)


def _check_daily(series: pd.Series) -> None:
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("Series needs a DatetimeIndex")
    if len(series) > 1 and not (series.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all():
        raise ValueError("Series must be on an uninterrupted daily calendar (reindex first; gaps stay NaN)")


def prior_sum(series: pd.Series, days: int) -> pd.Series:
    """Sum of the previous `days` completed days; NaN if any of them is missing."""
    _check_daily(series)
    return series.rolling(days, min_periods=days).sum().shift(1)


def prior_mean(series: pd.Series, days: int, min_valid: int | None = None) -> pd.Series:
    _check_daily(series)
    return series.rolling(days, min_periods=min_valid or days).mean().shift(1)


def prior_max(series: pd.Series, days: int) -> pd.Series:
    _check_daily(series)
    return series.rolling(days, min_periods=days).max().shift(1)


def prior_count(condition: pd.Series, days: int) -> pd.Series:
    """Days with condition True among the previous `days`; NaN if any day is unknown (NaN/NA)."""
    _check_daily(condition)
    numeric = condition.astype("float64")
    return numeric.rolling(days, min_periods=days).sum().shift(1)


def prior_run(condition: pd.Series) -> pd.Series:
    """Length of the run of consecutive True days ending on day d-1.

    An unknown day makes the run unknown (NaN) until the next known False day restarts the count.
    """
    _check_daily(condition)
    values = condition.astype("float64").to_numpy()
    run = np.full(len(values), np.nan)
    current = 0.0
    for i, v in enumerate(values):
        if np.isnan(v):
            current = np.nan
        elif v:
            current = current + 1 if np.isfinite(current) else np.nan
        else:
            current = 0.0
        run[i] = current
    return pd.Series(run, index=condition.index).shift(1)


def _reference(series: pd.Series, years: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    ref = series[(series.index.year >= years[0]) & (series.index.year <= years[1])].dropna()
    return calendar_day(ref.index), ref.to_numpy(dtype=float)


def _window_mask(ref_doy: np.ndarray, day: int, half_window: int) -> np.ndarray:
    dist = np.abs(ref_doy - day)
    return np.minimum(dist, 365 - dist) <= half_window


def calendar_percentile(series: pd.Series, years: tuple[int, int], half_window: int,
                        *, min_baseline: int = 30) -> pd.Series:
    """Mid-rank percentile (0-100) of each value among same-calendar-window reference values.

    Ties count half, so a 0 mm rain sum in a month that is usually dry sits near the middle, not at 0.
    NaN when the value is missing or the baseline has fewer than `min_baseline` values.
    """
    ref_doy, ref_val = _reference(series, years)
    days = calendar_day(series.index)
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for day in np.unique(days):
        base = np.sort(ref_val[_window_mask(ref_doy, day, half_window)])
        if len(base) < min_baseline:
            continue
        idx = np.flatnonzero((days == day) & np.isfinite(values))
        lo = np.searchsorted(base, values[idx], side="left")
        hi = np.searchsorted(base, values[idx], side="right")
        out[idx] = 100.0 * (lo + 0.5 * (hi - lo)) / len(base)
    return pd.Series(out, index=series.index)


def calendar_quantile(series: pd.Series, years: tuple[int, int], half_window: int, q: float,
                      *, min_baseline: int = 30) -> pd.Series:
    """Per-date threshold: the q-quantile of the same-calendar-window reference values (e.g. TX90p)."""
    ref_doy, ref_val = _reference(series, years)
    days = calendar_day(series.index)
    by_day = {}
    for day in np.unique(days):
        base = ref_val[_window_mask(ref_doy, day, half_window)]
        by_day[day] = float(np.quantile(base, q)) if len(base) >= min_baseline else np.nan
    return pd.Series([by_day[d] for d in days], index=series.index)


def wet_day_quantile(rain: pd.Series, years: tuple[int, int], q: float, wet_day_min_mm: float = 1.0) -> float:
    """q-quantile of daily rain on wet days (>= wet_day_min_mm) in the reference period (ETCCDI R95p/R99p)."""
    _, values = _reference(rain, years)
    wet = values[values >= wet_day_min_mm]
    if len(wet) < 100:
        raise ValueError("Too few wet days in the reference period for a stable percentile")
    return float(np.quantile(wet, q))
