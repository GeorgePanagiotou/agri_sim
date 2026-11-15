"""E — Conservative field × candidate-week × rotation-phase comparisons.

Only compares alternatives supported by evidence issued before the decision. A
preference ranking is not an estimate of rotation benefit. No 'sow now' action.
"""
from __future__ import annotations

from datetime import datetime, timezone
import pandas as pd


def current_week_alternatives(assessment: pd.Series, ranking: pd.DataFrame | None,
                              *, field_id: str, boundary_version: str | None = None) -> list[dict]:
    """Existing current-week candidate crossed with user-matched rotation phases.

    Future-week options require genuine issued forecasts and are NOT manufactured
    from old regional climate screens. Field history matches remain conditional.
    """
    required={'crop_id','season','week_start','sowing_verdict','decision_priority',
              'risk_evidence_status','risk_overall_level'}
    if required.difference(assessment.index):
        raise ValueError(f'Assessment lacks {sorted(required.difference(assessment.index))}')
    risk_level=pd.to_numeric(assessment.get('risk_overall_level'),errors='coerce')
    risk_status=str(assessment.get('risk_evidence_status'))
    verdict=str(assessment.get('sowing_verdict'))
    if verdict != 'check_worthy':
        status='blocked_by_sowing_screen'
    elif risk_status != 'complete' or pd.isna(risk_level):
        status='incomplete_risk_evidence'
    elif float(risk_level)>=2:
        status='regional_hazard_warning'
    else:
        status='candidate_for_seedbed_inspection_only'
    if ranking is None or ranking.empty:
        rotations=[dict(strategy_id=None,phase_match=None,relative_priority_score=None,
                        ranking_status='no_matching_or_scored_rotation')]
    else:
        rotations=[]
        for r in ranking.to_dict('records'):
            score=pd.to_numeric(r.get('relative_priority_score'),errors='coerce')
            if pd.notna(score) and not 0<=float(score)<=5:
                raise ValueError('Rotation preference score must be in [0,5]')
            rotations.append(dict(strategy_id=r.get('strategy_id'),phase_match=r.get('matches'),
                relative_priority_score=float(score) if pd.notna(score) else None,
                ranking_status=('subjective_preference_complete' if pd.notna(score)
                                else 'subjective_preference_incomplete')))
    return [dict(field_id=str(field_id),boundary_version=boundary_version,
         crop_id=str(assessment['crop_id']),season=str(assessment['season']),
         candidate_week=str(pd.Timestamp(assessment['week_start']).date()),
         strategy_id=r['strategy_id'],phase_match=r['phase_match'],
         eligibility=status,rotation_eligibility='conditional_on_farmer_confirmed_crop_history',
         preference_score_not_benefit=r['relative_priority_score'],
         preference_status=r['ranking_status'],establishment_probability=None,
         estimated_water_benefit=None,comparable_score=None,
         candidate_type='current_week_regional_screen_not_sowing_command') for r in rotations]


def forecast_candidates(week_rows: pd.DataFrame, archived_forecasts: pd.DataFrame,
                        *, decision_time_utc: datetime, field_id: str) -> pd.DataFrame:
    """Allow a future week only when a forecast for it existed at decision time.

    Forecast presence makes a week *assessable* but NOT safe. Crop-specific rule
    evaluation and field calibration still have to occur before any ranking.
    """
    if decision_time_utc.tzinfo is None:
        raise ValueError('decision_time_utc must be timezone aware')
    if archived_forecasts.empty:
        return pd.DataFrame(columns=['field_id','week_start','status','forecast_rows'])
    needed={'field_id','issued_at_utc','valid_at_utc'}
    if needed.difference(archived_forecasts.columns) or 'week_start' not in week_rows:
        raise ValueError('Missing forecast or week columns')
    issuance=pd.to_datetime(archived_forecasts.issued_at_utc,utc=True)
    validity=pd.to_datetime(archived_forecasts.valid_at_utc,utc=True)
    today=pd.Timestamp(decision_time_utc).tz_convert('UTC')
    valid=archived_forecasts.loc[archived_forecasts.field_id.astype(str).eq(str(field_id)) &
                                 issuance.le(today)].copy()
    valid['valid_at_utc']=pd.to_datetime(valid['valid_at_utc'],utc=True)
    rows=[]
    for week in pd.to_datetime(week_rows.week_start).dt.normalize().drop_duplicates():
        start=week.tz_localize('UTC') if week.tzinfo is None else week.tz_convert('UTC')
        matches=valid[valid.valid_at_utc.between(start,start+pd.Timedelta(days=7),inclusive='left')]
        rows.append(dict(field_id=str(field_id),week_start=str(start.date()),
                         status='forecast_available_requires_crop_specific_screen' if len(matches)
                                else 'missing_issued_forecast',forecast_rows=len(matches)))
    return pd.DataFrame(rows)
