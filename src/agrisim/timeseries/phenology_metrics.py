"""Extract observable greenness descriptors; not independently verified emergence."""
import numpy as np
import pandas as pd
from .greenup import quality_dates

def seasonal_metrics(frame):
    records=[]
    for keys, part in frame.groupby(['field_id','season','source'],dropna=False):
        d=quality_dates(part)
        record=dict(zip(('field_id','season','source'),keys),n_clear_dates=len(d))
        if len(d):
            x=d['ndvi_median'].astype(float).to_numpy()
            record.update(ndvi_min=float(np.min(x)),ndvi_max=float(np.max(x)),
                          ndvi_range=float(np.ptp(x)),date_of_max_ndvi=str(d.iloc[np.argmax(x)]['date_utc'].date()))
        records.append(record)
    return pd.DataFrame(records)
