"""Cross-module completion/evidence report for Evia.

Run: uv run python -m agrisim.decision_engine.completion_cli
All outputs are descriptive; missing ground truth yields not_evaluable statuses.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

import pandas as pd

from agrisim.config import REPO
from .completion_data import imagery_manifest, read_archive, append_archive
from .completion_evaluation import (load_snapshots, paired_outcomes, sowing_metrics,
    fit_sowing_research_baseline, rotation_evidence, suitability_gaps,
    hazard_metrics, decision_metrics, vegetation_ground_comparison)

TEMPLATES = {
 'data/local/rotation_outcomes.csv':
   'farm_id,field_id,season,strategy_id,phase_id,predecessor_crop,crop_id,management,harvested_yield,yield_unit,water_use_mm,soil_indicator,soil_indicator_unit,site_group,weather_group,evidence_source\n',
 'data/local/field_hazard_events.csv':
   'farm_id,field_id,crop_id,hazard,event_onset_utc,inspection_time_utc,severity,observed_damage,assessed_absence,evidence_source\n',
 'data/reference/rotation_suitability_sources.csv':
   'crop_id,source,scenario,spatial_scale,unit,coverage_status,evidence_date,coverage_gaps\n',
 'data/processed/forecasts/issued_weather_template.csv':
   'field_id,source,grid_id,issued_at_utc,valid_at_utc,precip_mm,temp_c,ensemble_member,source_run_id\n',
 'data/local/issued_hazard_alerts_template.csv':
   'field_id,hazard,issued_at_utc,valid_from_utc,valid_until_utc,warning_level,probability,evidence_source,source_run_id\n',
}


def optional_csv(path: Path) -> pd.DataFrame:
    path=Path(path)
    if not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _find_saved_field(root: Path, field_id: str) -> tuple[Path, str]:
    """Find the most recent complete batch for the actually saved boundary."""
    from agrisim.data_sources.field_hls import field_hls_plan
    from .recommendation_log import _boundary_version
    db_path = root/'data/local/field_profiles.sqlite3'
    if not db_path.is_file():
        raise FileNotFoundError(f'No field profiles SQLite database at {db_path}')
    with sqlite3.connect(db_path) as con:
        row = con.execute('SELECT value FROM inputs WHERE field_id=? AND setting=?',
                          (int(field_id),'boundary')).fetchone()
    if row is None or not row[0]:
        raise ValueError(f'Field {field_id} has no saved boundary')
    geometry=row[0]
    plan=field_hls_plan(geometry,field_id)
    batches=root/'data/processed/evia_sowing/hls_batches'
    candidates=sorted((p for p in batches.glob(f'*/{plan.site.name}/hls/acquisitions.csv')
                 if not p.parents[2].name.endswith('.partial')),reverse=True)
    if not candidates:
        raise FileNotFoundError('No field-specific HLS archive matching the saved boundary. Acquire field imagery in Streamlit first.')
    return candidates[0],_boundary_version(geometry)


def run(root: Path, *, acquisitions: Path | None = None, field_id: str | None = None,
        boundary_version: str | None = None, greenup_events: Path | None = None,
        export_dir: Path | None = None, create_templates: bool = False,
        scan_hls: bool = False) -> dict:
    root=Path(root).resolve()
    out=Path(export_dir) if export_dir else root/'outputs/decision_completion'
    out.mkdir(parents=True,exist_ok=True)
    written_templates=[]
    if create_templates:
        for rel,header in TEMPLATES.items():
            target=root/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():
                target.write_text(header,encoding='utf-8')
                written_templates.append(rel)
    if scan_hls:
        if not field_id or acquisitions is not None:
            raise ValueError('--scan-hls requires --field-id and excludes --acquisitions')
        acquisitions,boundary_version=_find_saved_field(root,str(field_id))
    # A: imagery inventory cannot be field-specific without an explicit field ID
    # and boundary version. Existing acquisitions may contain pilot 3x3 evidence.
    if acquisitions is not None:
        if not field_id or not boundary_version:
            raise ValueError('An acquisition manifest requires --field-id and --boundary-version')
        a=imagery_manifest(optional_csv(acquisitions),field_id=field_id,
                           boundary_version=boundary_version)
        a.to_csv(out/'field_imagery_manifest.csv',index=False)
        try:
            import pyarrow  # noqa: F401
            parquet_path=root/'data/processed/features/field_imagery_manifest.parquet'
            parquet_path.parent.mkdir(parents=True,exist_ok=True)
            a.to_parquet(parquet_path,index=False)
        except ImportError:
            pass  # CSV remains available; report explicitly states missing parquet dependency
    else:
        a=pd.DataFrame()
    outcomes=optional_csv(root/'data/local/field_outcomes.csv')
    issued=load_snapshots(root/'data/local/issued_recommendations.parquet')
    paired=paired_outcomes(outcomes,issued)
    events=optional_csv(greenup_events or root/'data/processed/features/greenup_events.csv')
    vegetation=vegetation_ground_comparison(events,outcomes)
    sowing=sowing_metrics(paired)
    rotation=rotation_evidence(optional_csv(root/'data/local/rotation_outcomes.csv'))
    suitability=suitability_gaps(optional_csv(root/'data/reference/rotation_suitability_sources.csv'))
    # Immutable actual issued evidence, not historical observed POWER reanalysis.
    forecast=read_archive(root/'data/processed/forecasts/issued_weather.parquet',kind='forecasts')
    alerts=read_archive(root/'data/local/issued_hazard_alerts.parquet',kind='alerts')
    risks=hazard_metrics(alerts,optional_csv(root/'data/local/field_hazard_events.csv'))
    decisions=decision_metrics(paired,issued)
    tables={'a_vegetation_validation':vegetation,'b_sowing_evaluation':sowing,
            'c_rotation_evidence':rotation,'c_suitability_gaps':suitability,
            'd_risk_evaluation':risks,'e_decision_evaluation':decisions}
    for name,table in tables.items():
        table.to_csv(out/(name+'.csv'),index=False)
    report={
      'report_type':'engineering_and_evidence_status_not_predictive_accuracy',
      'a_vegetation':{'manifest_rows':len(a),
                      'date_rows_selected':int(a.selected.sum()) if len(a) else 0,
                      'field_quality60_dates':int(a.loc[a.selected,'quality_60pct'].sum()) if len(a) else 0,
                      'independently_observed_emergence':int(vegetation.n_observed_emergence.sum()),
                      'status':'geometry_and_quality_inventory_only_not_ground_validated'},
      'b_sowing':{'issued_forecast_records':len(forecast),'evaluable_planting_outcomes':len(paired),
                   'training':fit_sowing_research_baseline(paired)},
      'c_rotation':{'measured_records':len(optional_csv(root/'data/local/rotation_outcomes.csv')),
                    'verified_crop_sources':int(suitability.n_usable_sources.sum())},
      'd_risk':{'issued_alert_records':len(alerts),'evaluated_alerts':int(risks.n_verified.fillna(0).sum())},
      'e_fusion':{'issued_recommendations':len(issued),'observed_selected_outcomes':len(paired),
                  'alternative_outcomes':'not_observed_do_not_estimate_counterfactuals'},
      'new_templates':written_templates,
      'limitations':['No factual validation without independent observed farm data',
                     'Live S30 acquisition not verified against the remote catalogs',
                     'No deployment of calibrated models without external holdout',
                     'Risk validation is conditional on logged alert/inspection pairs',
                     'No causal benefits for unchosen rotation or sowing alternatives'],
    }
    (out/'completion_status.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=REPO)
    parser.add_argument('--acquisitions',type=Path)
    parser.add_argument('--field-id')
    parser.add_argument('--scan-hls',action='store_true',help='Find latest archive matching saved SQLite boundary')
    parser.add_argument('--boundary-version')
    parser.add_argument('--greenup-events',type=Path)
    parser.add_argument('--ingest-issued-weather',type=Path,help='CSV of actual issued forecasts; archived immutably')
    parser.add_argument('--ingest-issued-alerts',type=Path,help='CSV of actual issued hazard alerts; archived immutably')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--create-templates',action='store_true')
    args=parser.parse_args()
    # Explicit operator action. Never interpret downloaded historical climate
    # observations as an issued forecast or field alert.
    if args.ingest_issued_weather:
        target=Path(args.root)/'data/processed/forecasts/issued_weather.parquet'
        created=append_archive(pd.read_csv(args.ingest_issued_weather),target,'forecasts')
        print(f'Archived issued weather evidence: {created}')
    if args.ingest_issued_alerts:
        target=Path(args.root)/'data/local/issued_hazard_alerts.parquet'
        created=append_archive(pd.read_csv(args.ingest_issued_alerts),target,'alerts')
        print(f'Archived issued risk alerts: {created}')
    report=run(args.root,acquisitions=args.acquisitions,field_id=args.field_id,
               boundary_version=args.boundary_version,greenup_events=args.greenup_events,
               export_dir=args.out,create_templates=args.create_templates,
               scan_hls=args.scan_hls)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
