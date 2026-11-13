"""Time-step aggregation with explicit minimum observation counts."""
import pandas as pd

def aggregate(df, *, date_col='date', value_columns, frequency='W-MON', method='mean', min_count=1):
    if method not in ('mean','median','sum'): raise ValueError('Unknown aggregation method')
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col])
    d = d.sort_values(date_col).set_index(date_col)
    grouped = d[list(value_columns)].resample(frequency)
    values = getattr(grouped, method)()
    counts = grouped.count()
    return values.where(counts >= min_count).reset_index()
