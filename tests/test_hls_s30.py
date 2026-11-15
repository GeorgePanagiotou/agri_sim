"""Offline HLS S30 narrow-NIR and mixed-sensor QA test (no external requests)."""
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from affine import Affine

from agrisim.data_sources import download_evia_hls as dl
from agrisim.data_sources.hls_fields import Site
from agrisim.timeseries.vegetation_indices import read_hls_batch


def test_hls_narrow_nir_sensor_mapping():
    assert dl.bands_for('HLS.L30.T34SEH.2026320T100000.v2.0') == ('B03','B04','B05','Fmask')
    assert dl.bands_for('HLS.S30.T34SEH.2026321T100000.v2.0') == ('B03','B04','B8A','Fmask')


def test_mixed_s30_and_l30_preserves_source_in_npz_and_indices(tmp_path,monkeypatch):
    monkeypatch.setattr(dl,'RAW',tmp_path/'raw')
    monkeypatch.setattr(dl,'REPO',tmp_path)
    site=Site('mixed_sensor_test',23.43232,38.7592,9)
    l30='HLS.L30.T34SEH.2026320T100000.v2.0'
    s30='HLS.S30.T34SEH.2026321T100000.v2.0'
    directory=site.directory(dl.RAW)
    directory.mkdir(parents=True)
    features=[]
    for scene,dt in ((l30,'2026-11-16T10:00:00Z'),(s30,'2026-11-17T10:00:00Z')):
        p=directory/f'{scene}.tif'
        with rasterio.open(p,'w',driver='GTiff',width=9,height=9,count=4,
                          dtype='int16',crs='EPSG:32634',
                          transform=Affine(30,0,530000,0,-30,4290000)) as ds:
            a=np.zeros((4,9,9),dtype='int16')
            a[0]=3000;a[1]=2000;a[2]=4000;a[3]=0
            ds.write(a)
            ds.descriptions=dl.bands_for(scene)
        features.append(dict(id=scene,nasa_concept_id=scene+'-NASA',
             available_utc=dt.replace('10:00:00','16:00:00'),
             properties=dict(datetime=dt,platform='test',)))
    out=tmp_path/'batch/mixed_sensor_test/hls'
    out.mkdir(parents=True)
    chosen=dl.prepare(features,site,out=out)
    assert len(chosen)==2
    assert chosen.sensor.tolist()==['L30','S30']
    with np.load(out/'field_context.npz',allow_pickle=False) as z:
        assert z['sources'].tolist()==['NASA_HLSL30_v2','NASA_HLSS30_v2']
        assert z['nir_band_names'].tolist()==['B05','B8A']
        assert 'NIR_narrow' in z['bands'].tolist()[2]
    result=read_hls_batch(tmp_path/'batch')
    assert set(result.source)=={'NASA_HLSL30_v2','NASA_HLSS30_v2'}
    assert np.allclose(result.ndvi_median.to_numpy(),1/3,atol=1e-6)


def test_mixed_source_history_uses_both_sensors_without_future_leakage(monkeypatch):
    from agrisim.decision_engine import vegetation_history as vh
    from agrisim.timeseries.greenup import analyze_group
    monkeypatch.setattr(vh,'analyze_group',
          lambda g,**kw: analyze_group(g,method='heuristic'))
    days=pd.date_range('2026-09-10',periods=8,freq='10D')
    sources=['NASA_HLSL30_v2' if i%2==0 else 'NASA_HLSS30_v2'
             for i in range(len(days))]
    observations=pd.DataFrame(dict(field_id=['2']*8,season=['2026-2027']*8,
         source=sources,spatial_support=['user_drawn_or_uploaded_boundary']*8,
         date_utc=days.strftime('%Y-%m-%d'),
         available_utc=(days+pd.Timedelta(days=2)).strftime('%Y-%m-%dT00:00:00Z'),
         valid_pixels=[20]*8,clear_fraction=[.9]*8,
         ndvi_median=[.13,.14,.16,.43,.48,.5,.52,.54],
         evi2_median=[.08,.09,.10,.27,.28,.29,.30,.32]))
    candidates=pd.DataFrame(dict(season=['2026-2027']*2,
         week_start=pd.to_datetime(['2026-10-01','2026-12-01'])))
    hist=vh.greenup_history(candidates,observations,field_id='2',
          support='user_drawn_or_uploaded_boundary')
    assert hist.iloc[0]['greenup_current_acquisitions']==2
    assert hist.iloc[1]['greenup_current_acquisitions']==8
    assert hist.iloc[0]['greenup_current_status']=='insufficient_clear_dates'
    assert hist.iloc[1]['greenup_current_status']=='retrospective_spectral_greenup'
