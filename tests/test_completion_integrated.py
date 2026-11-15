"""Offline regression checks for Module A–E evidence contracts."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from agrisim.decision_engine.completion_data import (imagery_manifest,
      validate_issued_weather,validate_issued_alerts,HAZARDS)
from agrisim.decision_engine.completion_evaluation import (
      paired_outcomes,sowing_metrics,fit_sowing_research_baseline,
      rotation_evidence,suitability_gaps,hazard_metrics,
      vegetation_ground_comparison,decision_metrics)
from agrisim.decision_engine.completion_alternatives import (
      current_week_alternatives,forecast_candidates)


def issued():
    snap={'schema_version':'issued_recommendation_v1',
        'selection':{'crop_id':'winter_wheat','season':'2026-2027',
                     'candidate_week':'2026-11-15','decision_priority':'candidate_for_field_check'},
        'field_assessment_snapshot':{'sowing_verdict':'check_worthy',
            'decision_priority':'candidate_for_field_check','rain_prior_mm':19.0,
            'temp_used_c':13.0,'smap_surface_prior':0.2,
            'risk_overall_level':0,'rotation_gaez_index':7000}}
    return pd.DataFrame([dict(recommendation_id='rec1',farm_id='farmA',
       field_id='2',issued_at_utc='2026-11-15T10:00:00+00:00',
       crop_id='winter_wheat',season='2026-2027',candidate_week='2026-11-15',snapshot=snap)])


def outcome(**kwargs):
    r=dict(recommendation_id='rec1',record_type='issued',field_id=2,season='2026-2027',
       farm_id='farmA',planting_status='Planted',actual_sowing_date='2026-11-16',
       observed_crop='winter_wheat',established_successfully=1,
       observation_date='2026-11-22',emergence_date_or_start='2026-11-20',
       evidence_source='Field visit')
    r.update(kwargs)
    return pd.DataFrame([r])


def test_a_manifest_quality_and_timestamps():
    d=pd.DataFrame([dict(granule='sceneA',date_utc='2026-10-11',acquired_utc='2026-10-11T11:00:00Z',
         available_utc='2026-10-13T13:00:00Z',full_interior_pixels=30,
         clear_interior_pixels=29,selected=True)])
    r=imagery_manifest(d,field_id='2',boundary_version='sha256:abc')
    assert r.quality_60pct.iloc[0] and r.field_id.iloc[0]=='2'
    d.loc[0,'available_utc']='2026-10-10T13:00:00Z'
    with pytest.raises(ValueError,match='precedes'):
        imagery_manifest(d,field_id='2',boundary_version='sha256:abc')


def test_a_ground_comparison_is_retrospective():
    events=pd.DataFrame([dict(field_id='2',season='2026-2027',
        status='retrospective_spectral_greenup',last_low_date='2026-11-18',
        first_high_date='2026-11-21')])
    r=vegetation_ground_comparison(events,outcome())
    assert r.interval_contains_emergence.iloc[0] == True
    assert 'retrospective' in r.status.iloc[0]


def test_b_issued_forecast_temporal_integrity():
    d=pd.DataFrame([dict(field_id='2',source='ECMWF',grid_id='gridA',
        issued_at_utc='2026-11-15T09:00:00Z',valid_at_utc='2026-11-17T09:00:00Z',
        precip_mm=4,temp_c=14,ensemble_member='0',source_run_id='g1')])
    assert len(validate_issued_weather(d))==1
    d.loc[0,'valid_at_utc']='2026-11-14T00:00:00Z'
    with pytest.raises(ValueError,match='precede'):
        validate_issued_weather(d)


def test_b_planting_outcome_has_correct_week_label():
    obs=paired_outcomes(outcome(),issued())
    assert len(obs)==1 and obs.success.iloc[0]==1
    assert sowing_metrics(obs).n_evaluable.iloc[0]==1
    assert fit_sowing_research_baseline(obs)['status'].startswith('not_trained')
    assert paired_outcomes(outcome(planting_status='Not planted',actual_sowing_date=None),issued()).empty
    assert paired_outcomes(outcome(actual_sowing_date='2026-11-25'),issued()).empty
    assert paired_outcomes(outcome(observed_crop='barley'),issued()).empty
    assert paired_outcomes(outcome(established_successfully=None),issued()).empty


def test_b_rejects_cross_field_outcome():
    with pytest.raises(ValueError,match='field'):
        paired_outcomes(outcome(field_id=999),issued())


def test_c_rotation_is_descriptive_and_rejects_duplicate_phase():
    d=pd.DataFrame([dict(farm_id='farmA',field_id='2',season='2026-2027',
        strategy_id='A',phase_id='A1',predecessor_crop='barley',crop_id='winter_wheat',
        harvested_yield=3.2,yield_unit='t/ha',water_use_mm=200,
        site_group='north',weather_group='wet',evidence_source='harvest')])
    r=rotation_evidence(d)
    assert r.n_field_seasons.iloc[0]==1
    assert r.status.iloc[0]=='insufficient_independent_farms_for_comparison'
    with pytest.raises(ValueError,match='Duplicate'):
        rotation_evidence(pd.concat([d,d],ignore_index=True))


def test_c_missing_suitability_sources_remain_missing():
    r=suitability_gaps(pd.DataFrame())
    assert len(r)==7 and r.n_usable_sources.sum()==0
    assert 'lentil' in r.crop_id.to_list()


def alert():
    return pd.DataFrame([dict(field_id='2',hazard='heavy_rain',
        issued_at_utc='2026-11-15T06:00:00Z',valid_from_utc='2026-11-15T12:00:00Z',
        valid_until_utc='2026-11-16T23:59:00Z',warning_level=2,
        probability=0.8,evidence_source='issued_forecast',source_run_id='runA')])


def event():
    return pd.DataFrame([dict(field_id='2',hazard='heavy_rain',
        event_onset_utc='2026-11-16T12:00:00Z',inspection_time_utc='2026-11-16T16:00:00Z',
        severity=2,observed_damage=True,assessed_absence=False,evidence_source='Field visit')])


def test_d_risk_metrics_from_independent_inspections():
    result=hazard_metrics(alert(),event())
    heavy=result[result.hazard=='heavy_rain'].iloc[0]
    assert heavy.true_positives == 1 and heavy.n_verified==1
    assert heavy.mean_lead_hours==30
    assert round(heavy.brier,5)==0.04
    missing=result[result.hazard=='frost'].iloc[0]
    assert missing.n_verified == 0


def test_d_absence_must_be_explicit():
    e=event();e['observed_damage']=False;e['assessed_absence']=False
    assert hazard_metrics(alert(),e).query('hazard=="heavy_rain"').n_verified.iloc[0]==0
    e['assessed_absence']=True
    r=hazard_metrics(alert(),e).query('hazard=="heavy_rain"').iloc[0]
    assert r.false_positives == 1
    e['observed_damage']=True
    with pytest.raises(ValueError,match='cannot also'):
        hazard_metrics(alert(),e)


def test_d_alerts_validate_range_and_hazard():
    d=alert()
    assert len(validate_issued_alerts(d))==1
    d['hazard']='fire'
    with pytest.raises(ValueError,match='Unknown'):
        validate_issued_alerts(d)


def test_e_alternatives_safety():
    a=pd.Series({'crop_id':'winter_wheat','season':'2026-2027',
      'week_start':'2026-11-15','sowing_verdict':'check_worthy',
      'decision_priority':'candidate_for_field_check',
      'risk_evidence_status':'complete','risk_overall_level':0})
    ranking=pd.DataFrame([dict(strategy_id='A',matches='Year 2 after barley',
                               relative_priority_score=4.5)])
    r=current_week_alternatives(a,ranking,field_id='2')
    assert r[0]['preference_score_not_benefit']==4.5
    assert r[0]['establishment_probability'] is None
    assert 'conditional' in r[0]['rotation_eligibility']
    a['risk_evidence_status']='partial'
    assert current_week_alternatives(a,ranking,field_id='2')[0]['eligibility']=='incomplete_risk_evidence'


def test_e_future_windows_require_issued_forecasts():
    now=pd.Timestamp('2026-11-15T09:00:00Z').to_pydatetime()
    rows=pd.DataFrame({'week_start':['2026-11-16']})
    result=forecast_candidates(rows,pd.DataFrame(),decision_time_utc=now,field_id='2')
    assert result.empty
    f=pd.DataFrame([dict(field_id='2',issued_at_utc='2026-11-14T10:00:00Z',
                        valid_at_utc='2026-11-17T12:00:00Z')])
    assert forecast_candidates(rows,f,decision_time_utc=now,field_id='2').forecast_rows.iloc[0]==1
    f['issued_at_utc']='2026-11-16T10:00:00Z'
    assert forecast_candidates(rows,f,decision_time_utc=now,field_id='2').forecast_rows.iloc[0]==0


def test_e_decision_results_do_not_claim_counterfactuals():
    r=decision_metrics(paired_outcomes(outcome(),issued()),issued())
    assert r.n_evaluable_selected.iloc[0]==1
    assert 'not_observed' in r.counterfactual_status.iloc[0]


def test_e_issued_snapshot_persists_new_alternatives_without_relabeling_history():
    from datetime import datetime,timezone
    from agrisim.decision_engine.recommendation_log import build_recommendation_snapshot
    import json
    a=pd.Series({'field_profile_id':'2','crop_id':'winter_wheat','season':'2026-2027',
                 'week_start':'2026-11-15','decision_priority':'candidate_for_field_check',
                 'recommended_action':'Inspect seedbed','sowing_verdict':'check_worthy',
                 'risk_evidence_status':'complete','risk_overall_level':0})
    weeks=pd.DataFrame([dict(crop_id='winter_wheat',season='2026-2027',
                     week_start='2026-11-15',sowing_verdict='check_worthy',
                     decision_priority='candidate_for_field_check')])
    boundary={'type':'Polygon','coordinates':[[[23.438,38.764],[23.439,38.764],
               [23.439,38.765],[23.438,38.764]]]}
    options=current_week_alternatives(a,None,field_id='2')
    snap=build_recommendation_snapshot(a,field_id='2',boundary=boundary,
         candidate_weeks=weeks,issued_at=datetime(2026,11,15,12,tzinfo=timezone.utc),
         alternatives=options)
    assert snap['eligible_alternatives']==options
    assert len(snap['historical_regional_week_context'])==1
    assert snap['eligible_alternatives'][0]['comparable_score'] is None
    assert json.dumps(snap,allow_nan=False)


def test_e_source_manifest_hashes_or_flags_missing(tmp_path):
    from agrisim.decision_engine.completion_provenance import source_manifest
    known=tmp_path/'configs/sowing_rules.yaml'
    known.parent.mkdir(parents=True)
    known.write_text('version: v1',encoding='utf-8')
    m=source_manifest(tmp_path)
    assert len(m['source_file_hashes']['configs/sowing_rules.yaml'])==64
    assert m['source_file_hashes']['configs/risk_rules.yaml'] is None
    assert m['replay_status'].startswith('hashes_only')
