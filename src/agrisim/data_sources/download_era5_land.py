"""Download official ESA/ECMWF ERA5-Land subsets (monthly) using the CDS API.

Not necessary for NASA-only demos; listed explicitly under ESA partner resources.
First accept dataset terms at the Copernicus Climate Data Store, and configure
~/.cdsapirc. Then use `uv run --extra optional-cds python data_prep/download_era5_land.py --year 2024`.

Returns original ERA5-Land hourly gridded products, NOT measured parcel weather.
"""
import argparse
import json
from pathlib import Path
from calendar import monthrange
try:
    from .config import RAW, STUDY_AREA
except ImportError:
    from .config import RAW, STUDY_AREA
DATASET='reanalysis-era5-land'
VARIABLES=['2m_temperature','total_precipitation','volumetric_soil_water_layer_1','soil_temperature_level_1',
           'potential_evaporation','surface_solar_radiation_downwards']

def request(year,month,variables=None):
    w,e,s,n=STUDY_AREA
    return {'variable':variables or VARIABLES,'year':str(year),'month':f'{month:02d}',
            'day':[f'{d:02d}' for d in range(1,monthrange(year,month)[1]+1)],
            'time':[f'{h:02d}:00' for h in range(24)],
            'area':[n,w,s,e], # N W S E in CDS
            'data_format':'netcdf','download_format':'unarchived'}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--year',type=int,required=True)
    ap.add_argument('--months',type=int,nargs='+',default=list(range(1,13)))
    args=ap.parse_args()
    try:import cdsapi
    except ImportError as e:raise SystemExit('Install optional CDS client: uv sync --extra optional-cds') from e
    out=RAW/'era5_land';out.mkdir(parents=True,exist_ok=True)
    client=cdsapi.Client()
    for m in args.months:
        if not 1<=m<=12:ap.error('Month must be 1..12')
        target=out/f'era5_land_{args.year}_{m:02d}.nc'
        if target.is_file():print('Cached:',target);continue
        payload=request(args.year,m)
        (out/f'era5_land_{args.year}_{m:02d}_request.json').write_text(json.dumps({'dataset':DATASET,'request':payload},indent=2))
        client.retrieve(DATASET,payload,str(target))
        print('Downloaded',target)
if __name__=='__main__':main()
