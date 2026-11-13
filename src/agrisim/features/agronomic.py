"""Farmer-confirmed calendars and suitability attributes; no fabricated crop thresholds."""
import pandas as pd

def validate_crop_calendar(calendar):
    required={'crop_id','earliest_sowing_month','latest_sowing_month'}
    if not required.issubset(calendar): raise ValueError(f'Missing {sorted(required-set(calendar))}')
    if not calendar['earliest_sowing_month'].between(1,12).all() or not calendar['latest_sowing_month'].between(1,12).all():
        raise ValueError('Month must be in 1..12')
    return calendar

def allowed_month(month, start_month, end_month):
    if start_month<=end_month:return start_month<=month<=end_month
    return month>=start_month or month<=end_month

def attach_crop_calendar(candidates,calendar):
    valid=validate_crop_calendar(calendar)
    merged=candidates.merge(valid,left_on='candidate_crop',right_on='crop_id',how='left',validate='many_to_one')
    merged['calendar_confirmed']=merged.crop_id.notna()
    merged['calendar_month_ok']=merged.apply(
        lambda r:allowed_month(pd.Timestamp(r.candidate_week_start).month,int(r.earliest_sowing_month),int(r.latest_sowing_month)) if r.calendar_confirmed else pd.NA,
        axis=1)
    return merged
