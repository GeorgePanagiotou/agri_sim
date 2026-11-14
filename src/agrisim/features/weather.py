"""Daily meteorological features for *retrospective* and *as-of-date* analysis."""
import numpy as np
import pandas as pd


def add_rainfall_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate historical rainfall without future data leakage."""
    df = df.copy().sort_index()

    for window in [7, 14, 30]:
        df[f"rainfall_prev_{window}d_mm"] = (
            df["PRECTOTCORR"]
            .shift(1)
            .rolling(window, min_periods=window)
            .sum()
        )

    return df

def growing_degree_days(temp_c, base_c=5.0, upper_c=None):
    t=np.asarray(temp_c,dtype=float)
    if upper_c is not None: t=np.minimum(t,upper_c)
    return np.maximum(t-base_c,0)

def longest_dry_spell(rain_mm, threshold_mm=1.0):
    rain=np.asarray(rain_mm,dtype=float)
    best=run=0
    for x in rain:
        if not np.isfinite(x): run=0 # unknown is not a dry day
        elif x < threshold_mm:run+=1;best=max(best,run)
        else:run=0
    return best

def add_daily_weather_features(df, *, candidate_mode=True):
    """Features available at the start of each day when candidate_mode=True."""
    d=df.copy();d['date']=pd.to_datetime(d['date']);d=d.sort_values('date').set_index('date')
    for k in ('precip_mm','temp_c'):
        if k not in d: raise ValueError(f'Missing {k}')
    d['gdd5']=growing_degree_days(d['temp_c'])
    shift = 1 if candidate_mode else 0
    d['rain_last7_mm']=d['precip_mm'].rolling(7,min_periods=7).sum().shift(shift)
    d['rain_last30_mm']=d['precip_mm'].rolling(30,min_periods=25).sum().shift(shift)
    d['gdd5_last14']=d['gdd5'].rolling(14,min_periods=14).sum().shift(shift)
    return d.reset_index()
