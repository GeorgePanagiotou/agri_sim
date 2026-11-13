"""Optional field-point sampling of NASA SRTM terrain and FAO GAEZ rasters.

A point sample is not a field average. For parcel-level evaluation, clip the
verified parcel polygon and aggregate native pixels separately.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from pyproj import Transformer, Geod
from agrisim.config import REPO as ROOT


def sample_rasters(fields:pd.DataFrame,srtm=None,faogaez=None):
    out=fields[['field_id','lat','lon']].copy()
    for name,path in [('srtm_elevation_m',srtm),('gaez_raw_value',faogaez)]:
        if path is None:continue
        if name=='gaez_raw_value':
            mf=Path(path).with_suffix('.json')
            if not mf.exists() or json.loads(mf.read_text()).get('source') != 'FAO GAEZ':
                raise ValueError('FAO raster must have verified source metadata from download_fao_gaez')
        with rasterio.open(path) as ds:
            x,y=Transformer.from_crs('EPSG:4326',ds.crs,always_xy=True).transform(fields.lon.to_numpy(),fields.lat.to_numpy())
            vals=[]
            for v in ds.sample(list(zip(x,y)),masked=True):
                cell=v[0]
                vals.append(float(cell) if not np.ma.is_masked(cell) and np.isfinite(cell) else np.nan)
            out[name]=vals
            if name=='srtm_elevation_m':
                slopes=[];aspects=[]
                geod=Geod(ellps='WGS84')
                for xx,yy in zip(x,y):
                    r,c=ds.index(xx,yy)
                    patch=ds.read(1,window=Window(c-1,r-1,3,3),boundless=True,masked=True)
                    if patch.shape!=(3,3) or np.ma.getmaskarray(patch).any() or not np.isfinite(np.asarray(patch)).all():
                        slopes.append(np.nan);aspects.append(np.nan);continue
                    if ds.crs.is_geographic:
                        dx=geod.inv(xx,yy,xx+abs(ds.transform.a),yy)[2]
                        dy=geod.inv(xx,yy,xx,yy+abs(ds.transform.e))[2]
                    else:
                        dx,dy=abs(ds.transform.a),abs(ds.transform.e)
                    if min(dx,dy)<=0:
                        slopes.append(np.nan);aspects.append(np.nan);continue
                    gx=(float(patch[1,2])-float(patch[1,0]))/(2*dx)
                    gy=(float(patch[2,1])-float(patch[0,1]))/(2*dy)
                    slopes.append(float(np.degrees(np.arctan(np.hypot(gx,gy)))))
                    aspects.append(float((np.degrees(np.arctan2(-gx,gy))+360)%360))
                out['srtm_slope_deg']=slopes
                out['srtm_aspect_deg']=aspects
    out['sampling_note']='Point sample, not validated parcel mean; inspect native product scale'
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--fields',type=Path,default=ROOT/'data/reference/fields.csv')
    p.add_argument('--srtm',type=Path,help='Unzipped official SRTM raster/HGT supported by Rasterio')
    p.add_argument('--gaez',type=Path,help='Official downloaded FAO GAEZ GeoTIFF')
    p.add_argument('--out',type=Path,default=ROOT/'data/processed/features/site_characteristics.csv')
    a=p.parse_args()
    df=sample_rasters(pd.read_csv(a.fields),a.srtm,a.gaez)
    a.out.parent.mkdir(parents=True,exist_ok=True);df.to_csv(a.out,index=False)
    print('Site characteristics ->',a.out)
if __name__=='__main__':main()
