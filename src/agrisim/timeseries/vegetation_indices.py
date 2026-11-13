"""Extract quality-screened, date-specific vegetation indices from HLS and Sentinel-2.

Usage: uv run python -m pipeline.vegetation --hls-batch path/to/hls_batches/BATCH_ID
       uv run python -m pipeline.vegetation --sentinel-dir data/raw/sentinel2
       uv run python -m pipeline.vegetation --hls-batch ... --sentinel-dir ...

A candidate 3x3 HLS footprint is NOT a surveyed parcel. It is explicitly flagged.
No data from satellite processing are treated as independently verified crop labels.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import numpy as np
import pandas as pd

from agrisim.config import REPO as ROOT
DEFAULT_OUT = ROOT / 'data/processed/features/vegetation_observations.csv'
HLS_BANDS = ('B03','B04','B05')


def vegetation_indices(green, red, nir, valid):
    """Compute indices from PHYSICAL surface reflectance, not RGB display bytes."""
    green, red, nir = [np.asarray(a,dtype=np.float64) for a in (green,red,nir)]
    valid = np.asarray(valid,dtype=bool) & np.isfinite(green) & np.isfinite(red) & np.isfinite(nir)
    ndvi = np.full(red.shape,np.nan)
    evi2 = np.full(red.shape,np.nan)
    savi = np.full(red.shape,np.nan)
    # Reflectance can be slightly negative after atmospheric correction; mask nonphysical input.
    good = valid & (green >= 0) & (red >= 0) & (nir >= 0) & ((nir+red) > 1e-5)
    with np.errstate(divide='ignore', invalid='ignore'):
        ndvi[good] = (nir[good]-red[good])/(nir[good]+red[good])
        evi2[good] = 2.5*(nir[good]-red[good])/(nir[good]+2.4*red[good]+1)
        savi[good] = 1.5*(nir[good]-red[good])/(nir[good]+red[good]+0.5)
    # No SWIR channel in HLS B03/B04/B05: do NOT silently compute canopy-water NDWI.
    return ndvi,evi2,savi


def stats(field_id, date_utc, source, spatial_source, green,red,nir, clear,mask, *, granule='', resolution_m=30):
    if not np.asarray(mask,dtype=bool).any():
        return None
    inside = np.asarray(mask,dtype=bool)
    valid = inside & np.asarray(clear,dtype=bool)
    ndvi,evi2,savi=vegetation_indices(green,red,nir,valid)
    v=np.isfinite(ndvi)&np.isfinite(evi2)
    vals=ndvi[v]
    n_total=int(inside.sum())
    n_valid=int(v.sum())
    season_year = int(date_utc[:4]) if int(date_utc[5:7]) >= 9 else int(date_utc[:4])-1
    def median(x):
        return float(np.median(x[v])) if n_valid else float('nan')
    return dict(field_id=field_id,date_utc=date_utc,season=f'{season_year}-{season_year+1}',
                source=source,source_granule=granule,spatial_support=spatial_source,
                resolution_m=resolution_m,valid_pixels=n_valid,total_pixels=n_total,
                clear_fraction=n_valid/n_total,ndvi_median=median(ndvi),evi2_median=median(evi2),
                savi_median=median(savi),ndvi_p10=float(np.percentile(vals,10)) if n_valid else float('nan'),
                ndvi_p90=float(np.percentile(vals,90)) if n_valid else float('nan'),
                green_fraction_ndvi_03=float((vals>=0.30).mean()) if n_valid else float('nan'))


def read_hls_batch(batch:Path, parcels:Path|None=None):
    from agrisim.data_sources.hls_fields import read_parcels, interior_pixels
    fields=read_parcels(parcels) if parcels else {}
    rows=[]
    archives=sorted(batch.glob('*/hls/field_context.npz'))
    if not archives:
        raise FileNotFoundError(f'No field_context.npz found beneath {batch}/FIELD/hls/')
    for archive in archives:
        field_id=archive.parent.parent.name
        with np.load(archive,allow_pickle=False) as z:
            if tuple(z['bands'].tolist()) != HLS_BANDS:
                raise ValueError(f'Unexpected HLS band sequence in {archive}')
            if z['reflectance'].shape[0]!=len(z['dates']):
                raise ValueError(f'Archive date count mismatch: {archive}')
            granules = z['granules'].astype(str)
            if not all(g.startswith('HLS.L30.') and g.endswith('.v2.0') for g in granules):
                raise ValueError('Only NASA Landsat HLSL30 v2.0 accepted in HLS pipeline')
            mask = z['candidate_mask'].astype(bool)
            spatial='provisional_center_3x3'
            if parcels:
                if field_id not in fields:
                    raise ValueError(f'Missing parcel geometry for {field_id}')
                mask=interior_pixels(str(z['crs'].item()),tuple(z['transform'].tolist()),mask.shape,fields[field_id])
                spatial='verified_polygon_supplied' # provenance, not independently validated by script
            for i,dt in enumerate(z['dates'].astype(str)):
                arr=z['reflectance'][i]
                row=stats(field_id,dt,'NASA_HLSL30_v2',spatial,arr[0],arr[1],arr[2],z['clear'][i],mask,
                          granule=str(granules[i]),resolution_m=30)
                if row: rows.append(row)
    return pd.DataFrame(rows)


def read_sentinel_dir(folder:Path,parcels:Path|None=None):
    from agrisim.data_sources.hls_fields import read_parcels,interior_pixels
    polygons=read_parcels(parcels) if parcels else {}
    import rasterio
    rows=[]
    for tif in sorted(folder.glob('*.tif')):
        manifest=tif.with_suffix('.json')
        if not manifest.exists():
            continue
        meta=json.loads(manifest.read_text(encoding='utf-8'))
        if meta.get('dataset') != 'sentinel-2-l2a':
            raise ValueError(f'Unapproved dataset in {manifest}')
        if meta.get('is_temporal_mosaic'):
            # Date assignment of a multi-day mosaic to a single date would be false.
            continue
        if meta.get('band_order') != ['B03_green','B04_red','B08_nir','SCL','dataMask']:
            raise ValueError(f'Sentinel-2 band order mismatch: {tif}')
        if meta['start_utc'] != meta['end_utc']:
            continue
        with rasterio.open(tif) as ds:
            arr=ds.read().astype('float32')
            crs_s2=ds.crs.to_string()
            transform_s2=tuple(ds.transform)[:6]
            if ds.count != 5:
                raise ValueError(f'Expected five Sentinel-2 bands: {tif}')
        # L2A SCL classes 4 vegetation, 5 non-vegetated. Excludes clouds, shadow, water, snow.
        valid=(arr[4]>0)&np.isin(arr[3],[4,5])
        stem=tif.stem
        field_id=meta.get('field_id') or re.sub(r'[^a-zA-Z0-9_]', '_',stem.split('_202')[0])
        support='unverified_window'
        mask=np.ones(valid.shape,bool)
        if parcels:
            if field_id not in polygons:
                raise ValueError(f'Sentinel site {field_id} missing in supplied parcel GeoJSON')
            mask=interior_pixels(crs_s2,transform_s2,valid.shape,polygons[field_id])
            support='verified_polygon_supplied'
        row=stats(field_id, meta['start_utc'],'ESA_Sentinel2_L2A',support,
                  arr[0],arr[1],arr[2],valid,mask,granule=stem,resolution_m=10)
        if row:rows.append(row)
    return pd.DataFrame(rows)


def build(hls_batch=None,sentinel_dir=None,out=DEFAULT_OUT,parcels=None):
    frames=[]
    if hls_batch:frames.append(read_hls_batch(Path(hls_batch),Path(parcels) if parcels else None))
    if sentinel_dir:frames.append(read_sentinel_dir(Path(sentinel_dir),Path(parcels) if parcels else None))
    if not frames:raise ValueError('Provide --hls-batch or --sentinel-dir')
    result=pd.concat(frames,ignore_index=True).sort_values(['field_id','date_utc','source'])
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(out,index=False)
    print(f'Vegetation observations: {len(result)} rows -> {out}')
    print('Unverified geometry is flagged; NASA/ESA vegetation indices are NOT true crop-emergence labels.')
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--hls-batch',type=Path)
    ap.add_argument('--sentinel-dir',type=Path)
    ap.add_argument('--parcels',type=Path,help='Confirmed GeoJSON parcel boundaries, HLS only')
    ap.add_argument('--out',type=Path,default=DEFAULT_OUT)
    a=ap.parse_args();build(a.hls_batch,a.sentinel_dir,a.out,a.parcels)
if __name__=='__main__':main()
