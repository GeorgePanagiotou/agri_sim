"""Offline checks for the new reusable modules. No credentials or imagery required."""
import numpy as np
import pandas as pd
import pytest
from agrisim.preprocessing.quality_masks import hls_clear_mask,sentinel2_clear_mask,reflectance_valid
from agrisim.preprocessing.gap_filling import retrospective_interpolate
from agrisim.preprocessing.temporal_alignment import asof_join
from agrisim.timeseries.vegetation_derivatives import add_rates
from agrisim.features.weather import growing_degree_days,longest_dry_spell,add_daily_weather_features
from agrisim.features.soil_water import fao56_reference_et0,daily_bucket
from agrisim.features.agronomic import allowed_month
from agrisim.decision_engine.rotation_simulator import simulate_rotation
from agrisim.utils.geospatial import within_lonlat

def test_masks():
    q=hls_clear_mask(np.array([0,1<<1,1<<3,1<<5,255],dtype='uint8'))
    assert q.tolist()==[True,False,False,False,False]
    assert sentinel2_clear_mask(np.array([4,5,6,8])).tolist()==[True,True,False,False]
    assert reflectance_valid(np.array([.2,-.1]),np.array([.3,.3])).tolist()==[True,False]

def test_interpolation_only_short_gaps():
    series=pd.Series([1.,np.nan,3.,np.nan,np.nan,np.nan,7.],index=pd.date_range('2024-01-01',periods=7))
    d=retrospective_interpolate(series,max_gap_days=1)
    assert d.value.iloc[1]==pytest.approx(2)
    assert d.value.iloc[4]!=d.value.iloc[4]

def test_asof_does_not_peek_forward():
    a=pd.DataFrame({'date':pd.to_datetime(['2024-01-02','2024-01-04'])})
    b=pd.DataFrame({'date':pd.to_datetime(['2024-01-03']), 'rain':[99]})
    out=asof_join(a,b,max_age_days=2)
    assert np.isnan(out.rain.iloc[0]) and out.rain.iloc[1]==99

def test_vegetation_derivatives_use_elapsed_days():
    d=pd.DataFrame({'field_id':['a','a'],'season':['2024','2024'],'source':['hls','hls'],
                    'date_utc':['2024-10-01','2024-10-11'],'ndvi_median':[.1,.4],
                    'evi2_median':[.1,.3]})
    o=add_rates(d)
    assert o.ndvi_per_day.iloc[1]==pytest.approx(.03)

def test_weather_asof_uses_yesterday_not_today():
    d=pd.DataFrame({'date':pd.date_range('2024-01-01',periods=35),
                    'precip_mm':[1.]*34+[80.],'temp_c':[15.]*35})
    out=add_daily_weather_features(d)
    assert out.rain_last7_mm.iloc[-1]==pytest.approx(7.)
    assert longest_dry_spell([0,0,np.nan,0,0,0,2.])==3
    assert growing_degree_days(np.array([2.,8.])).tolist()==[0.,3.]

def test_bucket_and_reference_et0():
    et=fao56_reference_et0(temp_c=20,net_radiation_mj_m2_day=10,wind_2m_ms=2,relative_humidity_pct=50)
    assert 0 < float(et) < 10
    out=daily_bucket([10,0],[3,3],capacity_mm=100,initial_water_mm=50)
    assert out.storage_mm.iloc[0]==pytest.approx(57)
    assert out.storage_mm.iloc[1]==pytest.approx(54)

def test_rotation_budget_requires_full_phases():
    weather=pd.DataFrame({'date':pd.date_range('2024-11-01',periods=3),
                           'precip_mm':[0.,10.,0.],'et0_mm':[1.,1.,1.]})
    phases=pd.DataFrame({'start':['2024-11-01'],'end':['2024-11-03'],'crop_id':['wheat'],'kc':[1.]})
    out=simulate_rotation(weather,phases,capacity_mm=80,initial_water_mm=40)
    assert out.storage_mm.iloc[-1]==pytest.approx(47)
    with pytest.raises(ValueError):simulate_rotation(weather,phases.iloc[:0],capacity_mm=80,initial_water_mm=40)

def test_misc():
    assert allowed_month(11,10,2)
    assert not allowed_month(6,10,2)
    assert within_lonlat(23.42,38.81,(23.32,23.5,38.75,38.95))
