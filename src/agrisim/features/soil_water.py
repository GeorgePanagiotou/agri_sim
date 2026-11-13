"""Reference ET0 and transparent, simplified daily bucket water balance.

This is an exploratory FAO-56 Penman-Monteith *reference* ET0 calculation.
Assumes daily net radiation is supplied in MJ/m²/day, not raw POWER solar kWh.
Net radiation needs outgoing longwave treatment; do not use solar input as net
radiation. Without suitable radiation data, Hargreaves estimate is fallback.
"""
import numpy as np
import pandas as pd

def fao56_reference_et0(temp_c, net_radiation_mj_m2_day, wind_2m_ms, relative_humidity_pct,
                        *, pressure_kpa=101.3, soil_heat_flux_mj=0.0):
    """FAO-56 daily reference ET0 (mm/day), for net radiation Rn and actual RH inputs."""
    t=np.asarray(temp_c,dtype=float)
    rn=np.asarray(net_radiation_mj_m2_day,dtype=float)
    u=np.asarray(wind_2m_ms,dtype=float)
    rh=np.asarray(relative_humidity_pct,dtype=float)
    p=np.asarray(pressure_kpa,dtype=float)
    es=0.6108*np.exp(17.27*t/(t+237.3))
    ea=es*rh/100
    delta=4098*es/((t+237.3)**2)
    gamma=0.000665*p
    et=(0.408*delta*(rn-soil_heat_flux_mj)+gamma*(900/(t+273))*u*(es-ea))/(delta+gamma*(1+0.34*u))
    return np.maximum(et,0)

def hargreaves_et0(tmin_c,tmax_c,tmean_c,extraterrestrial_radiation_mj_m2_day):
    """Temperature-based reference ET0 estimate; radiation Ra must be computed for latitude/DOY."""
    lo=np.asarray(tmin_c,dtype=float);hi=np.asarray(tmax_c,dtype=float)
    return 0.0023*(np.asarray(tmean_c,dtype=float)+17.8)*np.sqrt(np.maximum(hi-lo,0))*np.asarray(extraterrestrial_radiation_mj_m2_day,dtype=float)*0.408

def daily_bucket(rain_mm,et0_mm,*,capacity_mm,initial_water_mm,crop_coefficient=1.0,
                 irrigation_mm=None,runoff_fraction=0.0):
    """Simple storage model (not calibrated crop yield or deep hydrological simulation)."""
    rain=np.asarray(rain_mm,dtype=float); et0=np.asarray(et0_mm,dtype=float)
    if rain.shape!=et0.shape: raise ValueError('Rain and ET0 dimensions differ')
    if capacity_mm<=0 or not 0<=initial_water_mm<=capacity_mm: raise ValueError('Invalid capacity / initial storage')
    if not 0<=runoff_fraction<=1:raise ValueError('runoff_fraction must be 0..1')
    irrigation=np.zeros_like(rain) if irrigation_mm is None else np.broadcast_to(irrigation_mm,rain.shape)
    kc=np.broadcast_to(np.asarray(crop_coefficient,dtype=float),rain.shape)
    stored=float(initial_water_mm); rows=[]
    for i,(r,e,ir,k) in enumerate(zip(rain,et0,irrigation,kc)):
        if not np.isfinite([r,e,ir,k]).all():
            rows.append({'day':i,'storage_mm':np.nan,'drainage_mm':np.nan,'actual_et_mm':np.nan,'data_missing':True})
            stored=np.nan;continue
        if np.isnan(stored):
            rows.append({'day':i,'storage_mm':np.nan,'drainage_mm':np.nan,'actual_et_mm':np.nan,'data_missing':True});continue
        available=stored+(r+ir)*(1-runoff_fraction)
        drainage=max(available-capacity_mm,0)
        available=min(available,capacity_mm)
        actual_et=min(available,max(e*k,0))
        stored=available-actual_et
        rows.append({'day':i,'storage_mm':stored,'drainage_mm':drainage,'actual_et_mm':actual_et,'data_missing':False})
    return pd.DataFrame(rows)
