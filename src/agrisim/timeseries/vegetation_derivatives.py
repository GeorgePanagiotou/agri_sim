"""Per-day changes using actual acquisition gaps, not image-count differences."""
import numpy as np
import pandas as pd

def add_rates(df, *, group=('field_id','season','source')):
    d=df.copy(); d['date_utc']=pd.to_datetime(d['date_utc'])
    d=d.sort_values([*group,'date_utc'])
    g=d.groupby(list(group),sort=False)
    days=g['date_utc'].diff().dt.days
    d['elapsed_days']=days
    for col in ['ndvi_median','evi2_median']:
        if col in d:
            delta=g[col].diff()
            d['delta_'+col] = delta
            d[col.replace('_median','')+'_per_day']=(delta / days.replace(0,np.nan)).where(days>0)
    return d
