"""Offline checks for time-aware Savitzky-Golay and the real ruptures PELT call path."""
import sys
import types
import numpy as np
import pandas as pd
import pytest

from agrisim.timeseries.greenup import quality_dates, smooth_group, analyze_group, pelt_breaks


def sample(n=8):
    dates=pd.date_range('2024-10-01',periods=n,freq='12D')
    nd=np.array([.11,.12,.13,.14,.42,.46,.49,.50][:n])
    ev=np.array([.09,.10,.11,.12,.34,.37,.39,.40][:n])
    return pd.DataFrame(dict(field_id='field_A',season='2024-2025',
        source='NASA_HLSL30_v2',date_utc=dates.strftime('%Y-%m-%d'),
        valid_pixels=[9]*n,clear_fraction=[1.]*n,
        ndvi_median=nd,evi2_median=ev))


def test_savgol_keeps_actual_dates_and_observation_count():
    d=quality_dates(sample())
    sm=smooth_group(d,window_days=15)
    assert len(sm)==len(d)
    assert np.array_equal(sm.date_utc.values,d.date_utc.values)
    assert sm.smoothing_applied.all()
    assert np.isfinite(sm[['ndvi_smoothed','evi2_smoothed']]).all().all()
    assert sm.ndvi_smoothed.iloc[-1] > sm.ndvi_smoothed.iloc[0]


def test_savgol_never_blends_across_long_cloud_gap():
    df=sample()
    df.loc[4:,'date_utc']=pd.date_range('2025-02-01',periods=4,freq='12D').strftime('%Y-%m-%d')
    sm=smooth_group(quality_dates(df),window_days=15,max_gap_days=40)
    assert sm.ndvi_smoothed.iloc[3]<0.2
    assert sm.ndvi_smoothed.iloc[4]>0.3


def test_pelt_uses_ruptures_and_validates_actual_signal(monkeypatch):
    seen={}
    class FakePelt:
        def __init__(self,**kwargs):seen.update(kwargs)
        def fit(self,arr):
            seen['signal']=arr
            return self
        def predict(self,pen):
            seen['penalty']=pen
            return [4,8]
    monkeypatch.setitem(sys.modules,'ruptures',types.SimpleNamespace(Pelt=FakePelt))
    d=quality_dates(sample())
    assert pelt_breaks(d,penalty=3.0)==[4]
    assert seen['model']=='l2' and seen['jump']==1 and seen['penalty']==3.0
    assert seen['signal'].shape==(8,2)
    res=analyze_group(sample(),method='pelt',pelt_penalty=3.0)
    assert res['status']=='retrospective_spectral_greenup'
    assert res['first_high_date']=='2024-11-18'
    assert res['method']=='pelt_savgol'
    assert res['pelt_breaks']=='[4]'


def test_pelt_never_equates_sparse_series_with_emergence(monkeypatch):
    class FakePelt:
        def __init__(self,**kwargs):pass
        def fit(self,arr):return self
        def predict(self,pen):return [4,8]
    monkeypatch.setitem(sys.modules,'ruptures',types.SimpleNamespace(Pelt=FakePelt))
    r=analyze_group(sample(5),method='pelt')
    assert r['status']=='insufficient_clear_dates'
    bad=sample()
    bad.loc[4:,'ndvi_median']=.16
    bad.loc[4:,'evi2_median']=.14
    r=analyze_group(bad,method='pelt')
    assert r['status']=='no_confirmed_greenup'
