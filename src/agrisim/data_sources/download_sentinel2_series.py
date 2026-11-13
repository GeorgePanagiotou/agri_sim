"""Discover official ESA Sentinel-2 L2A acquisition dates and optionally download each.

ESA Copernicus Data Space STAC catalogue only. A date is selected only if there
is a real Sentinel-2 L2A product intersecting the query point/window.

Plan first (no credentials):
  uv run python data_prep/download_sentinel2_series.py --start 2024-09-01 --end 2025-01-31
Download individually dated snapshots (requires CDSE OAuth credentials):
  uv run python data_prep/download_sentinel2_series.py --start 2024-09-01 --end 2025-01-31 --download

Dated Process API images may mosaic adjacent tiles acquired on that SAME day.
These images are NOT ground-truth crop labels.
"""
import argparse
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
import requests
try:
    from .config import RAW,SOWING_LON,SOWING_LAT
    from .download_sentinel2 import main as download_day
except ImportError:
    from .config import RAW,SOWING_LON,SOWING_LAT
    from .download_sentinel2 import main as download_day
STAC='https://stac.dataspace.copernicus.eu/v1/search'


def catalog_dates(lon,lat,start,end,max_cloud=40,max_pages=20):
    if date.fromisoformat(start)>date.fromisoformat(end):raise ValueError('Start after end')
    # Small geographic bbox around point: reference study window, NOT field boundary.
    delta=0.01
    payload={'collections':['sentinel-2-l2a'],
             'bbox':[lon-delta,lat-delta,lon+delta,lat+delta],
             'datetime':f'{start}T00:00:00Z/{end}T23:59:59Z',
             'query':{'eo:cloud_cover':{'lte':max_cloud}},'limit':100}
    rows=[]
    next_url=STAC
    method='POST'
    with requests.Session() as session:
        for _ in range(max_pages):
            r=(session.post(next_url,json=payload,timeout=(20,90)) if method=='POST'
               else session.get(next_url,timeout=(20,90)))
            r.raise_for_status()
            page=r.json()
            for item in page.get('features',[]):
                if item.get('collection')!='sentinel-2-l2a':continue
                acquired=item.get('properties',{}).get('datetime') or item.get('properties',{}).get('start_datetime')
                if not acquired:continue
                rows.append({'date_utc':acquired[:10],'scene_id':item['id'],
                             'scene_cloud_pct':item.get('properties',{}).get('eo:cloud_cover'),
                             'product':'ESA Sentinel-2 L2A','catalogue':STAC})
            link=next((l for l in page.get('links',[]) if l.get('rel')=='next'),None)
            if not link:break
            next_url=link['href']
            if urlparse(next_url).hostname != 'stac.dataspace.copernicus.eu':
                raise RuntimeError('Unexpected STAC pagination destination')
            method=link.get('method','GET').upper()
            if method=='POST':payload=link.get('body',payload)
            elif method!='GET':raise RuntimeError('Unexpected STAC pagination method')
        else:
            raise RuntimeError(f'Exceeded catalogue pagination cap ({max_pages} pages); restrict date range')
    unique={}
    for r in sorted(rows,key=lambda x:(x['date_utc'],x['scene_cloud_pct'] if x['scene_cloud_pct'] is not None else 101)):
        unique.setdefault(r['date_utc'],r)
    return sorted(unique.values(),key=lambda x:x['date_utc'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',required=True);p.add_argument('--end',required=True)
    p.add_argument('--site',default='evia_pilot');p.add_argument('--lon',type=float,default=SOWING_LON)
    p.add_argument('--lat',type=float,default=SOWING_LAT)
    p.add_argument('--max-cloud',type=int,default=40)
    p.add_argument('--max-days',type=int,default=80)
    p.add_argument('--min-gap-days',type=int,default=3)
    p.add_argument('--size-m',type=int,default=990)
    p.add_argument('--download',action='store_true',help='Otherwise only make a catalogue plan')
    a=p.parse_args()
    all_dates=catalog_dates(a.lon,a.lat,a.start,a.end,a.max_cloud)
    chosen=[]
    for row in all_dates:
        if not chosen or (date.fromisoformat(row['date_utc'])-date.fromisoformat(chosen[-1]['date_utc'])).days>=a.min_gap_days:
            chosen.append(row)
        if len(chosen)>=a.max_days:break
    out=RAW/'sentinel2';out.mkdir(parents=True,exist_ok=True)
    plan=out/f'catalogue_{a.site}_{a.start}_{a.end}.json'
    plan.write_text(json.dumps({'origin':STAC,'site':a.site,'selected':chosen,
                                 'available_unique_dates':len(all_dates),'download_requested':a.download},indent=2))
    print(f'ESA Sentinel-2 L2A: {len(chosen)} selected of {len(all_dates)} cloud-filtered dates -> {plan}')
    if a.download:
        for row in chosen:
            print('Acquiring',row['date_utc'])
            download_day(['--site',a.site,'--date',row['date_utc'],'--lon',str(a.lon),'--lat',str(a.lat),
                          '--size-m',str(a.size_m),'--max-cloud',str(a.max_cloud)])
if __name__=='__main__':main()
