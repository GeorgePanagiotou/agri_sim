"""Evidence-limited A–E evaluation. Never infer outcomes of unchosen alternatives.

All ground truth must be independently observed. Empty evidence produces explicit
not_evaluable reports. Unknown/partial establishment is NOT a negative label.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .completion_data import HAZARDS, _required, validate_issued_alerts

BINARY = {'0': 0, '1': 1, '0.0': 0, '1.0': 1}
FEATURES = ('rain_prior_mm','temp_used_c','smap_surface_prior',
            'risk_overall_level','rotation_gaez_index')


def load_snapshots(path: Path) -> pd.DataFrame:
    """Return only independently issued immutable records, never old CSV rows."""
    path=Path(path)
    if not path.exists() or not path.is_dir() or not list(path.glob('part-*.parquet')):
        return pd.DataFrame(columns=['recommendation_id','farm_id','field_id',
                         'issued_at_utc','crop_id','season','candidate_week','snapshot'])
    source = pd.read_parquet(path)
    _required(source,['recommendation_id','snapshot_json'],'issued snapshots')
    if source['recommendation_id'].duplicated().any():
        raise ValueError('Duplicate issued recommendation IDs')
    result=[]
    for r in source.itertuples(index=False):
        snapshot=json.loads(r.snapshot_json)
        if snapshot.get('recommendation_id')!=r.recommendation_id:
            raise ValueError('Snapshot ID disagrees with Parquet index')
        if snapshot.get('schema_version')!='issued_recommendation_v1':
            raise ValueError('Unsupported issued snapshot schema')
        selection=snapshot['selection']
        result.append(dict(recommendation_id=r.recommendation_id,
                   farm_id=snapshot.get('farm_id'),field_id=str(snapshot['field_id']),
                   issued_at_utc=snapshot['issued_at_utc'],crop_id=selection['crop_id'],
                   season=selection['season'],candidate_week=selection['candidate_week'],
                   snapshot=snapshot))
    return pd.DataFrame(result)


def paired_outcomes(outcomes: pd.DataFrame, issued: pd.DataFrame) -> pd.DataFrame:
    """Link assessed, actually planted episodes to issuance-time features.

    A week is evaluable only if actual sowing occurred within the recommended
    candidate week, crop matches, field identity matches and provenance exists.
    """
    cols=['recommendation_id','farm_id','field_id','season','crop_id','candidate_week',
          'issued_at_utc','actual_sowing_date','observation_date','success',
          'sowing_verdict','decision_priority',*FEATURES]
    if issued.empty or outcomes.empty:
        return pd.DataFrame(columns=cols)
    _required(outcomes,('recommendation_id','record_type','planting_status','actual_sowing_date',
                        'established_successfully','observation_date','evidence_source',
                        'observed_crop','field_id'),'field outcomes')
    index=issued.set_index('recommendation_id')
    if index.index.duplicated().any():
        raise ValueError('Issued recommendations are not unique')
    rows=[]
    for r in outcomes.to_dict('records'):
        ident=r.get('recommendation_id')
        if pd.isna(ident) or ident not in index.index or r.get('record_type')!='issued':
            continue
        snap=index.loc[ident]
        if str(r['field_id']) != str(snap['field_id']):
            raise ValueError('Observed field does not match issued recommendation')
        if r.get('planting_status')!='Planted':
            continue
        if not r.get('actual_sowing_date') or pd.isna(r.get('actual_sowing_date')):
            continue
        if not r.get('observed_crop') or pd.isna(r.get('observed_crop')) or r['observed_crop'] != snap['crop_id']:
            continue
        planted=pd.Timestamp(r['actual_sowing_date'])
        start=pd.Timestamp(snap['candidate_week'])
        if not start <= planted < start + pd.Timedelta(days=7):
            continue
        label=BINARY.get(str(r['established_successfully']))
        if label is None or not r.get('evidence_source') or r.get('evidence_source')=='Not provided':
            continue
        if not r.get('observation_date') or pd.isna(r['observation_date']):
            continue
        if pd.Timestamp(r['observation_date']) < planted:
            raise ValueError('Establishment assessment predates sowing')
        if pd.Timestamp(snap['issued_at_utc']).date() > pd.Timestamp(r['observation_date']).date():
            raise ValueError('Outcome observation predates recommendation issuance')
        assessment=snap['snapshot']['field_assessment_snapshot']
        row=dict(recommendation_id=ident,farm_id=snap['farm_id'],
                 field_id=str(snap['field_id']),season=snap['season'],crop_id=snap['crop_id'],
                 candidate_week=snap['candidate_week'],issued_at_utc=snap['issued_at_utc'],
                 actual_sowing_date=str(r['actual_sowing_date']),observation_date=r['observation_date'],
                 success=label,sowing_verdict=assessment.get('sowing_verdict'),
                 decision_priority=assessment.get('decision_priority'))
        row.update({f:assessment.get(f) for f in FEATURES})
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=cols)
    data=pd.DataFrame(rows)
    if data.recommendation_id.duplicated().any():
        raise ValueError('Duplicate outcomes for the same issued choice')
    return data


def sowing_metrics(paired: pd.DataFrame) -> pd.DataFrame:
    """Baseline is a field-check screen, not an establishment probability."""
    columns=['crop_id','season','sowing_verdict','n_evaluable','established','observed_success_fraction',
             'model_status']
    if paired.empty:
        return pd.DataFrame([dict(crop_id='ALL',season='ALL',sowing_verdict='ALL',n_evaluable=0,
                     established=pd.NA,observed_success_fraction=pd.NA,
                     model_status='not_evaluable_no_independent_issued_outcomes')],columns=columns)
    rows=[]
    for key,g in paired.groupby(['crop_id','season','sowing_verdict'],dropna=False):
        rows.append(dict(zip(('crop_id','season','sowing_verdict'),key)) | dict(
            n_evaluable=len(g),established=int(g.success.sum()),
            observed_success_fraction=float(g.success.mean()),
            model_status='descriptive_outcomes_not_calibrated_prediction'))
    return pd.DataFrame(rows,columns=columns)


def fit_sowing_research_baseline(paired: pd.DataFrame) -> dict:
    """Optional *research* logistic baseline; explicit farm+season holdout.

    Refuse to fit until enough measured episodes exist. Hold out last season and
    prevent all holdout farms from appearing in training. No model is deployed.
    """
    available=paired.copy()
    if available.empty:
        return {'status':'not_trained_no_labels','n':0}
    available=available.dropna(subset=['farm_id',*FEATURES,'success'])
    for field in FEATURES:
        available[field]=pd.to_numeric(available[field],errors='coerce')
    available=available.dropna(subset=list(FEATURES))
    if len(available)<80 or available.farm_id.nunique()<4 or available.season.nunique()<2:
        return {'status':'not_trained_need_80_measured_episodes_4_farms_2_seasons',
                'n':int(len(available)),'farms':int(available.farm_id.nunique()),
                'seasons':int(available.season.nunique())}
    latest=sorted(available.season.unique())[-1]
    test=available[available.season.eq(latest)]
    train=available[~available.season.eq(latest) & ~available.farm_id.isin(test.farm_id)]
    if min(len(train),len(test))<20 or train.success.nunique()<2 or test.success.nunique()<2:
        return {'status':'not_trained_insufficient_disjoint_farm_season_holdout',
                'train':len(train),'test':len(test)}
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score
    model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=2000))
    model.fit(train[list(FEATURES)],train.success.astype(int))
    pred=model.predict_proba(test[list(FEATURES)])[:,1]
    return {'status':'research_holdout_only_not_deployed',
            'n_train':int(len(train)),'n_holdout':int(len(test)),
            'holdout_season':str(latest),'n_train_farms':int(train.farm_id.nunique()),
            'n_holdout_farms':int(test.farm_id.nunique()),
            'holdout_brier':float(brier_score_loss(test.success.astype(int),pred)),
            'holdout_auc_roc':float(roc_auc_score(test.success.astype(int),pred)),
            'calibration_status':'not_calibrated_separately'}


def rotation_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    columns=['strategy_id','crop_id','yield_unit','site_group','weather_group',
             'n_field_seasons','n_farms','mean_measured_yield','mean_measured_water_mm',
             'status']
    if frame.empty:
        return pd.DataFrame(columns=columns)
    required=['farm_id','field_id','season','strategy_id','phase_id','predecessor_crop',
             'crop_id','harvested_yield','yield_unit','water_use_mm','site_group','weather_group','evidence_source']
    _required(frame,required,'rotation outcomes')
    d=frame.copy()
    if d.duplicated(['field_id','season','phase_id']).any():
        raise ValueError('Duplicate field-season-rotation phases')
    for col in ('harvested_yield','water_use_mm'):
        d[col]=pd.to_numeric(d[col],errors='coerce')
        if (d[col].dropna()<0).any():
            raise ValueError(f'{col} cannot be negative')
    d=d.dropna(subset=['farm_id','strategy_id','crop_id','evidence_source'])
    rows=[]
    keys=['strategy_id','crop_id','yield_unit','site_group','weather_group']
    for key,g in d.groupby(keys,dropna=False):
        farms=g.farm_id.nunique()
        rows.append(dict(zip(keys,key)) | dict(n_field_seasons=len(g),n_farms=farms,
              mean_measured_yield=g.harvested_yield.mean() if g.harvested_yield.notna().any() else np.nan,
              mean_measured_water_mm=g.water_use_mm.mean() if g.water_use_mm.notna().any() else np.nan,
              status=('descriptive_observations_not_causal_benefits' if farms>=3
                      else 'insufficient_independent_farms_for_comparison')))
    return pd.DataFrame(rows,columns=columns)


def suitability_gaps(sources: pd.DataFrame) -> pd.DataFrame:
    expected=['winter_wheat','barley','chickpea','lentil','phacelia','sainfoin','vetch_oat']
    fields=['crop_id','coverage_status','n_usable_sources','status']
    if sources.empty:
        return pd.DataFrame([dict(crop_id=c,coverage_status='missing',n_usable_sources=0,
                   status='no_verified_suitability_source') for c in expected],columns=fields)
    _required(sources,['crop_id','source','coverage_status','evidence_date','spatial_scale','unit'],
              'suitability sources')
    rows=[]
    for c in expected:
        r=sources.loc[sources.crop_id.eq(c)]
        verified=r.loc[r.coverage_status.eq('verified') & r.source.notna() &
                       r.evidence_date.notna() & r.spatial_scale.notna() & r.unit.notna()]
        rows.append(dict(crop_id=c,coverage_status='verified' if not verified.empty else 'missing_or_unverified',
                         n_usable_sources=len(verified),
                         status='source_registered_not_local_accuracy_validated' if len(verified)
                                else 'no_verified_suitability_source'))
    return pd.DataFrame(rows,columns=fields)


def hazard_metrics(alerts: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    columns=['hazard','n_alerts','n_verified','true_positives','false_positives','false_negatives',
             'true_negatives','precision','recall','false_alarm_rate','mean_lead_hours',
             'brier','status']
    if alerts.empty or events.empty:
        return pd.DataFrame([dict(hazard=h,n_alerts=0,n_verified=0,status='not_evaluable_no_issued_alerts_or_inspections')
                             for h in HAZARDS],columns=columns)
    a=validate_issued_alerts(alerts)
    required=['field_id','hazard','event_onset_utc','inspection_time_utc','severity',
              'observed_damage','assessed_absence','evidence_source']
    _required(events,required,'field hazard events')
    e=events.copy()
    if (~e.hazard.isin(HAZARDS)).any():
        raise ValueError('Unknown observed hazard')
    for c in ('inspection_time_utc','event_onset_utc'):
        e[c]=pd.to_datetime(e[c],utc=True,errors='coerce',format='mixed')
    if e.inspection_time_utc.isna().any():
        raise ValueError('Inspections require a valid inspection_time_utc')
    if (e.event_onset_utc.notna() & (e.event_onset_utc > e.inspection_time_utc)).any():
        raise ValueError('Observed event starts after its inspection')
    def truth(x):
        if x is True or str(x).lower() in ('true','1','yes'):
            return True
        if x is False or str(x).lower() in ('false','0','no'):
            return False
        return None
    e['observed_damage']=e.observed_damage.map(truth)
    e['assessed_absence']=e.assessed_absence.map(truth)
    if (e.observed_damage.eq(True) & e.assessed_absence.eq(True)).any():
        raise ValueError('Positive event cannot also be marked absent')
    results=[]
    for hazard in HAZARDS:
        sub=a[a.hazard.eq(hazard)]
        labels=[]
        for r in sub.itertuples():
            matching=e[e.hazard.eq(hazard) & e.field_id.astype(str).eq(str(r.field_id)) &
                       e.inspection_time_utc.between(r.valid_from_utc,r.valid_until_utc) &
                       e.evidence_source.notna()]
            positive=matching[matching.observed_damage.eq(True) &
                     matching.event_onset_utc.between(r.valid_from_utc,r.valid_until_utc)]
            negative=matching[matching.assessed_absence.eq(True) & matching.observed_damage.eq(False)]
            if len(positive) and len(negative):
                raise ValueError('Conflicting positive/negative inspection labels for same alert')
            if positive.empty and negative.empty:
                continue
            label=int(not positive.empty)
            onset=positive.event_onset_utc.min() if label else pd.NaT
            lead=(onset-r.issued_at_utc).total_seconds()/3600 if label else np.nan
            labels.append((int(r.warning_level>=2),label,r.probability,lead))
        if not labels:
            results.append(dict(hazard=hazard,n_alerts=len(sub),n_verified=0,
                                status='not_evaluable_no_matching_inspections'))
            continue
        d=pd.DataFrame(labels,columns=['warning','actual','prob','lead'])
        tp=int(((d.warning==1)&(d.actual==1)).sum())
        fp=int(((d.warning==1)&(d.actual==0)).sum())
        fn=int(((d.warning==0)&(d.actual==1)).sum())
        tn=int(((d.warning==0)&(d.actual==0)).sum())
        pb=d.dropna(subset=['prob'])
        results.append(dict(hazard=hazard,n_alerts=len(sub),n_verified=len(d),
             true_positives=tp,false_positives=fp,false_negatives=fn,true_negatives=tn,
             precision=tp/(tp+fp) if (tp+fp) else np.nan,
             recall=tp/(tp+fn) if (tp+fn) else np.nan,
             false_alarm_rate=fp/(fp+tn) if (fp+tn) else np.nan,
             mean_lead_hours=float(d.lead.mean()) if d.lead.notna().any() else np.nan,
             brier=float(((pb.prob-pb.actual)**2).mean()) if len(pb) else np.nan,
             status='observed_alert_validation_not_farm_independent_holdout'))
    return pd.DataFrame(results,columns=columns)


def decision_metrics(paired: pd.DataFrame, issued: pd.DataFrame) -> pd.DataFrame:
    """Report evaluated *selected* choices, never estimated outcomes for alternatives."""
    fields=['decision_priority','n_issued','n_evaluable_selected','observed_established_fraction',
            'counterfactual_status']
    if issued.empty:
        return pd.DataFrame([dict(decision_priority='ALL',n_issued=0,n_evaluable_selected=0,
              counterfactual_status='not_evaluable_no_issued_choices')],columns=fields)
    priorities={}
    for row in issued.itertuples():
        priority=row.snapshot.get('selection',{}).get('decision_priority','unknown')
        priorities.setdefault(priority,[]).append(row.recommendation_id)
    rows=[]
    for key,identifiers in priorities.items():
        sub=paired[paired.recommendation_id.isin(identifiers)]
        rows.append(dict(decision_priority=key,n_issued=len(identifiers),n_evaluable_selected=len(sub),
             observed_established_fraction=float(sub.success.mean()) if len(sub) else np.nan,
             counterfactual_status='unchosen_week_or_rotation_outcomes_not_observed'))
    return pd.DataFrame(rows,columns=fields)


def vegetation_ground_comparison(events: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """A — Compare retrospectively detected spectral intervals to observed emergence.

    Requires independent emergence evidence. Not a point-in-time performance
    estimate unless the detector's scene publication cutoffs are separately
    replayed; user-entered synthetic test polygons do not qualify as truth.
    """
    columns=['farm_id','field_id','season','n_observed_emergence',
             'n_detected_intervals','interval_contains_emergence','status']
    if events.empty or outcomes.empty:
        return pd.DataFrame([dict(farm_id=pd.NA,field_id=pd.NA,season=pd.NA,
             n_observed_emergence=0,n_detected_intervals=0,interval_contains_emergence=pd.NA,
             status='not_evaluable_no_independent_emergence_events')],columns=columns)
    _required(events,['field_id','season','status','last_low_date','first_high_date'],
              'greenup events')
    _required(outcomes,['record_type','field_id','season','farm_id',
              'actual_sowing_date','emergence_date_or_start','evidence_source'],
              'field outcomes')
    evidence=outcomes[(outcomes.record_type=='issued') &
          outcomes.actual_sowing_date.notna() &
          outcomes.emergence_date_or_start.notna() &
          outcomes.evidence_source.notna() &
          outcomes.evidence_source.ne('Not provided')]
    rows=[]
    for r in evidence.to_dict('records'):
        selections=events[events.field_id.astype(str).eq(str(r['field_id'])) &
                          events.season.astype(str).eq(str(r['season']))]
        detected=selections[selections.status.eq('retrospective_spectral_greenup')]
        if len(detected)>1:
            raise ValueError('Multiple spectral event intervals for one field-season')
        truth=pd.Timestamp(r['emergence_date_or_start'])
        hit=False
        if len(detected):
            e=detected.iloc[0]
            hit=pd.Timestamp(e.last_low_date) < truth <= pd.Timestamp(e.first_high_date)
        rows.append(dict(farm_id=r.get('farm_id'),field_id=str(r['field_id']),
             season=r['season'],n_observed_emergence=1,n_detected_intervals=int(len(detected)),
             interval_contains_emergence=bool(hit) if len(detected) else pd.NA,
             status='retrospective_comparison_not_heldout'))
    if not rows:
        return pd.DataFrame([dict(farm_id=pd.NA,field_id=pd.NA,season=pd.NA,
             n_observed_emergence=0,n_detected_intervals=0,interval_contains_emergence=pd.NA,
             status='not_evaluable_no_evidenced_issued_emergence')],columns=columns)
    return pd.DataFrame(rows,columns=columns)
