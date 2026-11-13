"""Convert optional official ERA5-Land NetCDF to regional daily covariates.

No regridding to 30 m and no unit mixing. CDS delivery may be ZIP/GRIB;
this module accepts NetCDF only. Accumulated precipitation and fluxes are
intentionally NOT decoded here without validating their accumulation convention.
"""
import argparse
from pathlib import Path
import pandas as pd
import numpy as np
from agrisim.config import REPO as ROOT

def extract_netcdf(files):
    import xarray as xr
    cols={'t2m':'era5_temp_c','swvl1':'era5_soil_water_m3m3','stl1':'era5_soil_temp_c'}
    tables=[]
    for f in files:
        with xr.open_dataset(f) as ds:
            time=next((x for x in ['valid_time','time'] if x in ds.coords),None)
            if not time:raise ValueError(f'ERA5 file lacks time coordinate: {f}')
            present={k:v for k,v in cols.items() if k in ds.data_vars}
            if not present:raise ValueError(f'Cannot find t2m / swvl1 / stl1 in {f}; inspect CDS variable names')
            d=ds[list(present)].mean(dim=[dim for dim in ['latitude','longitude','lat','lon'] if dim in ds.dims],skipna=True)
            frame=d.to_dataframe().reset_index()
            frame['date']=pd.to_datetime(frame[time],utc=True).dt.tz_convert(None).dt.normalize()
            for variable in ('t2m','stl1'):
                if variable in frame:frame[variable]=frame[variable]-273.15
            frame=frame.groupby('date')[list(present)].mean().rename(columns=present).reset_index()
            tables.append(frame)
    if not tables:raise ValueError('No ERA5 NetCDF inputs')
    return pd.concat(tables).groupby('date',as_index=False).mean().sort_values('date')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input-dir',type=Path,default=ROOT/'data/raw/era5_land')
    p.add_argument('--out',type=Path,default=ROOT/'data/processed/features/era5_land_daily.csv')
    a=p.parse_args();df=extract_netcdf(sorted(a.input_dir.glob('*.nc')))
    a.out.parent.mkdir(parents=True,exist_ok=True);df.to_csv(a.out,index=False)
    print('Daily ERA5 regional context ->',a.out)
if __name__=='__main__':main()
