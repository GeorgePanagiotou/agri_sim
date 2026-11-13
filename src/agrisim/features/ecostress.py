"""Optional ECOSTRESS ET point-sampling of NASA AppEEARS GeoTIFF granules.

This uses overpass dates encoded in NASA filenames, no temporal interpolation.
The result is a sampled point (not an agricultural parcel mean), and no field-
scale labels. Use only ECO_L3T_JET files actually downloaded via AppEEARS.
"""
import argparse
import re
from pathlib import Path
import pandas as pd
import numpy as np
import rasterio
from pyproj import Transformer
from agrisim.config import REPO as ROOT

def extract(fields,root):
    fields=pd.read_csv(fields)
    rows=[]
    for tif in sorted(Path(root).glob('**/*.tif')):
        if 'ECO_L3T_JET' not in tif.name and 'ETdaily' not in tif.name:
            continue
        # Check the parent is a downloaded NASA AppEEARS task with a source record.
        task=tif.parent/'nasa_request.json'
        if not task.exists() or 'ECO_L3T_JET' not in task.read_text(encoding='utf-8'):
            continue
        d=re.search(r'(20\d{6})T',tif.name)
        if not d:
            # A NASA granule with no reliable date cannot be assigned to a field-date.
            continue
        dt=pd.to_datetime(d.group(1),format='%Y%m%d').strftime('%Y-%m-%d')
        with rasterio.open(tif) as ds:
            x,y=Transformer.from_crs('EPSG:4326',ds.crs,always_xy=True).transform(fields.lon.to_numpy(),fields.lat.to_numpy())
            for (ix,field),value in zip(fields.iterrows(),ds.sample(zip(x,y),masked=True)):
                v=value[0]
                rows.append({'field_id':field.field_id,'date_utc':dt,
                             'ecostress_ETdaily_mm_day':float(v) if not np.ma.is_masked(v) and np.isfinite(v) else np.nan,
                             'source_file':tif.name,'spatial_support':'point_sample_not_parcel_mean'})
    return pd.DataFrame(rows)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--fields',type=Path,default=ROOT/'data/reference/fields.csv')
    p.add_argument('--input-dir',type=Path,default=ROOT/'data/raw/appeears')
    p.add_argument('--out',type=Path,default=ROOT/'data/processed/features/ecostress_overpasses.csv')
    a=p.parse_args();df=extract(a.fields,a.input_dir)
    a.out.parent.mkdir(parents=True,exist_ok=True);df.to_csv(a.out,index=False)
    print(f'ECOSTRESS samples: {len(df)} -> {a.out}; no inferred dates or pixels')
if __name__=='__main__':main()
