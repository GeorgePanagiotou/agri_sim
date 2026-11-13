"""Short-gap interpolation for *retrospective analysis only*; never use future days in prediction."""
import numpy as np
import pandas as pd

def retrospective_interpolate(series, *, max_gap_days=10):
    s = series.copy().sort_index().astype(float)
    if not isinstance(s.index, pd.DatetimeIndex): raise ValueError('DatetimeIndex required')
    if not s.index.is_unique: raise ValueError('Duplicate timestamps')
    dates = pd.date_range(s.index.min(), s.index.max(), freq='D') if len(s) else s.index
    regular = s.reindex(dates)
    # Fill only interior gaps with at most max_gap_days missing days, retaining NaN beyond that.
    filled = regular.interpolate(method='time', limit_area='inside')
    is_missing = regular.isna()
    groups = (is_missing != is_missing.shift()).cumsum()
    for _, piece in regular.groupby(groups):
        if piece.isna().all() and len(piece) > max_gap_days:
            filled.loc[piece.index] = np.nan
    return pd.DataFrame({'value':filled,'interpolated':is_missing & filled.notna()})
