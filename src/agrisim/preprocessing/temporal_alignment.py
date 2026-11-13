"""Backward-only time joins for dates of known environmental measurements."""
import pandas as pd

def asof_join(left, right, *, left_date='date', right_date='date', by=None, max_age_days=7):
    if max_age_days < 0: raise ValueError('max_age_days must be >=0')
    a, b = left.copy(), right.copy()
    a[left_date] = pd.to_datetime(a[left_date]); b[right_date] = pd.to_datetime(b[right_date])
    a = a.sort_values(left_date); b = b.sort_values(right_date)
    return pd.merge_asof(a, b, left_on=left_date, right_on=right_date, by=by,
                         direction='backward', tolerance=pd.Timedelta(days=max_age_days))
