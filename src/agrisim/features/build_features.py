"""Build as-of-date environmental and sowing-window features for North Evia.

Crucial: forecasts are NOT present. Candidate-date features use only completed
prior days of observed/reanalysis weather. Retrospective evaluation is not an
operational weather forecast. The input grids are regional, not parcel sensors.

python -m pipeline.features --fields data/reference/fields.csv
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from agrisim.config import REPO as ROOT
OUT=ROOT/'data/processed/features'


def latest_file(folder,pattern):
    files=list(Path(folder).glob(pattern))
    # Prefer the longest available historical range for robust 1991-2020 baselines.
    def interval_days(path):
        import re
        m=re.search(r'(\d{4,8})_(\d{4,8})',path.stem)
        if m:
            try:
                a=pd.to_datetime(m.group(1),format='%Y%m%d' if len(m.group(1))==8 else '%Y')
                b=pd.to_datetime(m.group(2),format='%Y%m%d' if len(m.group(2))==8 else '%Y')
                return (b-a).days
            except (ValueError,TypeError):pass
        return -1
    return max(files,key=lambda x:(interval_days(x),x.stat().st_mtime)) if files else None


def read_table(path):
    path=Path(path)
    return pd.read_csv(path) if path.suffix.lower()=='.csv' else pd.read_parquet(path)

def power_daily(path):
    df=read_table(path).reset_index(drop=False) if Path(path).suffix.lower()!='.csv' else read_table(path)
    if 'date' not in df.columns:df=df.rename(columns={df.columns[0]:'date'})
    df['date']=pd.to_datetime(df['date']).dt.normalize()
    df=df.sort_values('date').drop_duplicates('date')
    rename={'T2M':'temp_c','T2M_MAX':'max_temp_c','T2M_MIN':'min_temp_c',
            'GWETTOP':'power_surface_wetness','GWETROOT':'power_root_wetness',
            'RH2M':'relative_humidity_pct','WS2M':'wind_ms','ALLSKY_SFC_SW_DWN':'solar_kwh_m2_day'}
    return df.rename(columns=rename)


def gpm_daily(path):
    df=read_table(path).reset_index(drop=False) if Path(path).suffix.lower()!='.csv' else read_table(path)
    if 'date' not in df.columns:df=df.rename(columns={df.columns[0]:'date'})
    df['date']=pd.to_datetime(df['date']).dt.normalize()
    if 'precip_mm' not in df.columns:raise ValueError('IMERG needs precip_mm')
    if df.date.duplicated().any():
        # If gridded NASA table, use the area mean; this is NOT a field mean.
        df=df.groupby('date',as_index=False)['precip_mm'].mean()
    return df[['date','precip_mm']].rename(columns={'precip_mm':'gpm_rain_mm'})


def smap_daily(path):
    df=pd.read_csv(path)
    if 'date_utc' not in df:raise ValueError('SMAP daily needs date_utc')
    df['date']=pd.to_datetime(df.date_utc).dt.normalize()
    cols=['date']+[c for c in ['sm_surface_m3m3','soil_temp_layer1_C','sm_samples'] if c in df]
    return df[cols].drop_duplicates('date')


def environmental_daily(power_path,gpm_path=None,smap_path=None,era5_path=None):
    w=power_daily(power_path)
    if gpm_path and Path(gpm_path).exists():w=w.merge(gpm_daily(gpm_path),on='date',how='left',validate='one_to_one')
    else:w['gpm_rain_mm']=np.nan
    if smap_path and Path(smap_path).exists():w=w.merge(smap_daily(smap_path),on='date',how='left',validate='one_to_one')
    else:w['sm_surface_m3m3']=np.nan;w['soil_temp_layer1_C']=np.nan
    if era5_path and Path(era5_path).exists():
        era=pd.read_csv(era5_path)
        era['date']=pd.to_datetime(era.date).dt.normalize()
        w=w.merge(era,on='date',how='left',validate='one_to_one')
    w=w.sort_values('date').set_index('date')
    # Daily gaps remain NaN. Never manufacture a dry day from a missing IMERG estimate.
    full=pd.date_range(w.index.min(),w.index.max(),freq='D')
    w=w.reindex(full)
    for col in ('gpm_rain_mm','temp_c','power_surface_wetness'):
        if col not in w:w[col]=np.nan
    # Observation cutoff: candidate sowing date cannot use that day's full rainfall.
    w['rain_prior_7d_mm']=w['gpm_rain_mm'].rolling(7,min_periods=7).sum().shift(1)
    w['rain_prior_14d_mm']=w['gpm_rain_mm'].rolling(14,min_periods=14).sum().shift(1)
    w['rain_prior_7d_max_mm']=w['gpm_rain_mm'].rolling(7,min_periods=7).max().shift(1)
    w['temp_prior_7d_c']=w['temp_c'].rolling(7,min_periods=7).mean().shift(1)
    w['gdd5_prior_14d']=((w['temp_c']-5).clip(lower=0)).rolling(14,min_periods=14).sum().shift(1)
    w['power_wetness_prior_7d']=w['power_surface_wetness'].rolling(7,min_periods=7).mean().shift(1)
    w['smap_moisture_prior_7d']=w['sm_surface_m3m3'].rolling(7,min_periods=3).mean().shift(1)
    w['soil_temp_prior_7d_c']=w['soil_temp_layer1_C'].rolling(7,min_periods=3).mean().shift(1)
    if 'era5_temp_c' in w:
        w['era5_temp_prior_7d_c']=w['era5_temp_c'].rolling(7,min_periods=5).mean().shift(1)
    if 'era5_soil_water_m3m3' in w:
        w['era5_soil_water_prior_7d']=w['era5_soil_water_m3m3'].rolling(7,min_periods=5).mean().shift(1)
    # True regional historical distribution (prior baseline years), same calendar month.
    baseline=w.loc['1991':'2020'] if len(w.loc['1991':'2020']) else w.iloc[:0]
    if len(baseline):
        cutoff=baseline.groupby(baseline.index.month)['power_surface_wetness'].quantile([0.2,0.8]).unstack()
        w['power_wetness_historical_p20']=pd.Series(w.index.month,index=w.index).map(cutoff[0.2])
        w['power_wetness_historical_p80']=pd.Series(w.index.month,index=w.index).map(cutoff[0.8])
    else:
        w['power_wetness_historical_p20']=np.nan
        w['power_wetness_historical_p80']=np.nan
    w.index.name='date'
    w['data_spatial_scale']='regional: GPM ~10km, SMAP ~9km, POWER coarse grid'
    return w.reset_index()


def candidate_sowing_dates(env,fields_path,months=(9,10,11,12,1),weekday=0):
    fields=pd.read_csv(fields_path)
    required={'field_id','farm_id','lat','lon'}
    if not required.issubset(fields):raise ValueError(f'Field CSV missing: {sorted(required-set(fields))}')
    if fields.field_id.duplicated().any():raise ValueError('Duplicate field IDs')
    dates=env[(env.date.dt.month.isin(months))&(env.date.dt.weekday==weekday)].copy()
    if dates.empty:raise ValueError('No dates within the given season/months')
    rows=fields.merge(dates,how='cross')
    rows['agricultural_season']=np.where(rows.date.dt.month>=9,rows.date.dt.year,rows.date.dt.year-1)
    rows['candidate_week_start']=rows.date.dt.strftime('%Y-%m-%d')
    return rows.drop(columns='date')


def run(fields, power=None, gpm=None, smap=None,era5=None,output_dir=OUT):
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    power=power or latest_file(ROOT/'data/processed','power_daily_*.parquet')
    gpm=gpm or latest_file(ROOT/'data/processed','imerg_area_mean_*.parquet')
    smap=smap or ROOT/'data/processed/evia_sowing/smap/smap_daily.csv'
    if not power:raise FileNotFoundError('Download NASA POWER daily data first')
    if not gpm:print('Warning: no IMERG area mean; rainfall inputs will remain missing')
    era5=era5 or ROOT/'data/processed/features/era5_land_daily.csv'
    env=environmental_daily(power,gpm,smap,era5)
    env.to_parquet(output_dir/'environment_daily.parquet',index=False)
    c=candidate_sowing_dates(env,fields)
    site=output_dir/'site_characteristics.csv'
    if site.exists():
        characteristic=pd.read_csv(site).drop(columns=['lat','lon'],errors='ignore')
        c=c.merge(characteristic,on='field_id',how='left',validate='many_to_one')
    c.to_csv(output_dir/'sowing_candidate_features.csv',index=False)
    print(f'Environment: {len(env)} dates; candidate field-weeks: {len(c)}')
    return c


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fields',type=Path,default=ROOT/'data/reference/fields.csv')
    p.add_argument('--power',type=Path)
    p.add_argument('--gpm',type=Path)
    p.add_argument('--smap',type=Path)
    p.add_argument('--era5',type=Path)
    p.add_argument('--out',type=Path,default=OUT)
    a=p.parse_args();run(a.fields,a.power,a.gpm,a.smap,a.era5,a.out)
if __name__=='__main__':main()
