"""Scenario-wise seasonal water accounting, not crop-yield prediction.

Each proposed rotation must start from an equal initial water store and use
identical weather. Kc and water-storage assumptions come from a verified crop
calendar; never infer agronomic thresholds from satellite greenness alone.
"""
import pandas as pd
from agrisim.features.soil_water import daily_bucket

def simulate_rotation(weather, phases, *, capacity_mm, initial_water_mm):
    """Return time-varying water budget; phases have start/end/crop_id/kc.

    `weather` has date, precip_mm, et0_mm; do not add additional simulated rain.
    Phase coverage is required; unassigned days are fallow (Kc=0.2 placeholder)
    unless a documented fallback is supplied explicitly in phases.
    """
    req={'date','precip_mm','et0_mm'}
    if not req.issubset(weather): raise ValueError('Need date, precip_mm, et0_mm')
    req_phases={'start','end','crop_id','kc'}
    if not req_phases.issubset(phases):raise ValueError(f'Phases need {sorted(req_phases)}')
    d=weather.copy();d['date']=pd.to_datetime(d['date']);d=d.sort_values('date')
    if d.date.duplicated().any():raise ValueError('Duplicate weather dates')
    d['crop_id']=pd.NA;d['kc']=float('nan')
    for row in phases.itertuples(index=False):
        if not 0<=float(row.kc)<=2:raise ValueError('Crop coefficient out of range')
        mask=d['date'].between(pd.Timestamp(row.start),pd.Timestamp(row.end))
        if d.loc[mask,'crop_id'].notna().any():raise ValueError('Overlapping rotation phases')
        d.loc[mask,'crop_id']=str(row.crop_id);d.loc[mask,'kc']=float(row.kc)
    if d['kc'].isna().any():raise ValueError('Every simulated day needs an explicit phase or fallow Kc')
    budget=daily_bucket(d.precip_mm,d.et0_mm,capacity_mm=capacity_mm,
                        initial_water_mm=initial_water_mm,crop_coefficient=d.kc.to_numpy())
    return pd.concat([d.reset_index(drop=True),budget.drop(columns='day')],axis=1)

def compare_scenarios(weather, scenarios, *, capacity_mm, initial_water_mm):
    """scenarios: mapping strategy ID -> phase DataFrame."""
    rows=[];traces={}
    for key,phases in scenarios.items():
        trace=simulate_rotation(weather,phases,capacity_mm=capacity_mm,initial_water_mm=initial_water_mm)
        traces[key]=trace
        rows.append({'strategy_id':key,'n_days':len(trace),
                     'estimated_actual_et_mm':trace.actual_et_mm.sum(min_count=len(trace)),
                     'estimated_drainage_mm':trace.drainage_mm.sum(min_count=len(trace)),
                     'minimum_estimated_storage_mm':trace.storage_mm.min(),
                     'model_status':'uncalibrated_water_bucket_no_yield_prediction'})
    return pd.DataFrame(rows),traces
