"""Shared, immutable point-in-time evidence contracts for Modules A, B and D.

No historical reanalysis is treated as an issued forecast. No synthetic field
observations are created. Files ending in .parquet are dataset DIRECTORIES.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

HAZARDS = ('drought', 'dry_spell', 'heat', 'frost', 'heavy_rain')
WEATHER_FIELDS = ('field_id', 'source', 'grid_id', 'issued_at_utc', 'valid_at_utc',
                  'precip_mm', 'temp_c', 'ensemble_member', 'source_run_id')
ALERT_FIELDS = ('field_id', 'hazard', 'issued_at_utc', 'valid_from_utc', 'valid_until_utc',
                'warning_level', 'probability', 'evidence_source', 'source_run_id')
IMAGERY_FIELDS = ('field_id', 'boundary_version', 'granule', 'source', 'platform',
                  'date_utc', 'acquired_utc', 'available_utc', 'full_interior_pixels',
                  'clear_interior_pixels', 'quality_60pct', 'selected')


def _required(df, fields, label):
    missing = set(fields) - set(df.columns)
    if missing:
        raise ValueError(f'{label}: missing required columns {sorted(missing)}')


def _utc(values, label):
    stamps = pd.to_datetime(values, utc=True, errors='coerce', format='mixed')
    if stamps.isna().any():
        raise ValueError(f'{label}: invalid or missing UTC timestamps')
    return stamps


def imagery_manifest(acquisitions: pd.DataFrame, *, field_id: str,
                     boundary_version: str, source: str = 'NASA_HLSL30_v2') -> pd.DataFrame:
    """Scene-level inventory; 60% cloud threshold is metadata only, not NDVI QA.

    Conservatively exclude scenes with missing publication timestamps from any
    point-in-time evaluation. Never treat a candidate 3x3 as parcel evidence.
    """
    _required(acquisitions, ('granule','date_utc','available_utc','full_interior_pixels',
                            'clear_interior_pixels'), 'acquisitions')
    d = acquisitions.copy()
    d['acquired_utc'] = d['acquired_utc'] if 'acquired_utc' in d else d['date_utc']
    d['platform'] = d['platform'] if 'platform' in d else ''
    d['selected'] = d['selected'] if 'selected' in d else ~d['date_utc'].duplicated()
    d['selected'] = d['selected'].map(lambda x: str(x).lower() in ('true','1','yes') if not isinstance(x,bool) else x)
    if d['granule'].duplicated().any():
        raise ValueError('acquisitions contains duplicated granules')
    d['date_utc'] = pd.to_datetime(d['date_utc'], errors='coerce').dt.strftime('%Y-%m-%d')
    if d['date_utc'].isna().any():
        raise ValueError('acquisitions contains invalid calendar dates')
    d['acquired_utc'] = _utc(d['acquired_utc'], 'acquired_utc')
    d['available_utc'] = pd.to_datetime(d['available_utc'], utc=True, errors='coerce', format='mixed')
    if (d['available_utc'] < d['acquired_utc']).any():
        raise ValueError('A catalog publication precedes its acquisition')
    full = pd.to_numeric(d['full_interior_pixels'], errors='coerce')
    clear = pd.to_numeric(d['clear_interior_pixels'], errors='coerce')
    if (full.isna() | clear.isna() | (full < 0) | (clear < 0) | (clear > full)).any():
        raise ValueError('Invalid field pixel accounting')
    d['full_interior_pixels'] = full.astype(int)
    d['clear_interior_pixels'] = clear.astype(int)
    d['quality_60pct'] = (full >= 4) & (clear >= 4) & (clear >= 0.6 * full)
    d['field_id'], d['boundary_version'], d['source'] = str(field_id), str(boundary_version), source
    for col in ('acquired_utc','available_utc'):
        d[col] = d[col].dt.strftime('%Y-%m-%dT%H:%M:%S%z')
    return d[list(IMAGERY_FIELDS)].sort_values(['date_utc','granule']).reset_index(drop=True)


def validate_issued_weather(frame: pd.DataFrame) -> pd.DataFrame:
    _required(frame, WEATHER_FIELDS, 'issued forecast')
    d = frame.copy()
    if d.empty:
        return d
    for c in ('field_id','source','grid_id','source_run_id'):
        if d[c].isna().any() or d[c].astype(str).str.strip().eq('').any():
            raise ValueError(f'Forecast {c} cannot be blank')
    d['issued_at_utc'] = _utc(d['issued_at_utc'], 'forecast issue time')
    d['valid_at_utc'] = _utc(d['valid_at_utc'], 'forecast valid time')
    if (d['valid_at_utc'] < d['issued_at_utc']).any():
        raise ValueError('Forecast valid time cannot precede the actual issue time')
    for field in ('precip_mm','temp_c'):
        d[field] = pd.to_numeric(d[field],errors='coerce')
        if not np.isfinite(d[field]).all():
            raise ValueError(f'Forecast {field} must be a finite numerical value')
    if (d['precip_mm'] < 0).any():
        raise ValueError('Forecast precipitation cannot be negative')
    d['ensemble_member'] = d['ensemble_member'].fillna('deterministic').astype(str)
    if d.duplicated(['field_id','source','source_run_id','issued_at_utc',
                     'valid_at_utc','ensemble_member']).any():
        raise ValueError('Duplicate issued forecast grid/time/member')
    return d


def validate_issued_alerts(frame: pd.DataFrame) -> pd.DataFrame:
    _required(frame, ALERT_FIELDS, 'issued alerts')
    d = frame.copy()
    if d.empty:
        return d
    if (~d['hazard'].isin(HAZARDS)).any():
        raise ValueError('Unknown hazard type')
    for c in ('field_id', 'evidence_source','source_run_id'):
        if d[c].isna().any() or d[c].astype(str).str.strip().eq('').any():
            raise ValueError(f'Alert {c} cannot be blank')
    for field in ('issued_at_utc','valid_from_utc','valid_until_utc'):
        d[field] = _utc(d[field],field)
    if (d['valid_until_utc'] < d['valid_from_utc']).any():
        raise ValueError('Alert has reversed valid interval')
    if (d['valid_until_utc'] < d['issued_at_utc']).any():
        raise ValueError('Alert expired before issuance')
    level = pd.to_numeric(d['warning_level'],errors='coerce')
    if (level.isna() | ~level.isin([0,1,2,3])).any():
        raise ValueError('warning_level must be 0, 1, 2 or 3')
    d['warning_level'] = level.astype(int)
    d['probability'] = pd.to_numeric(d['probability'],errors='coerce')
    if ((d['probability'] < 0) | (d['probability'] > 1)).any():
        raise ValueError('probability must be between 0 and 1 if supplied')
    if d.duplicated(['field_id','hazard','issued_at_utc','valid_from_utc','valid_until_utc']).any():
        raise ValueError('Duplicate issued field/hazard/interval')
    return d


def append_archive(frame: pd.DataFrame, directory: Path, kind: str) -> Path:
    """Append one immutable snapshot; requires pyarrow, preserves exact issue timestamps."""
    if kind not in ('forecasts','alerts'):
        raise ValueError('kind must be forecasts or alerts')
    validated = (validate_issued_weather(frame) if kind == 'forecasts'
                 else validate_issued_alerts(frame))
    if validated.empty:
        raise ValueError('Cannot archive an empty issued evidence snapshot')
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('Install pyarrow: uv add pyarrow') from exc
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    uid = uuid4().hex
    stage = directory / f'.{uid}.tmp.parquet'
    destination = directory / f'part-{uid}.parquet'
    try:
        validated.to_parquet(stage,index=False)
        os.link(stage,destination)
    finally:
        stage.unlink(missing_ok=True)
    return destination


def read_archive(directory: Path, *, kind: str) -> pd.DataFrame:
    fields = WEATHER_FIELDS if kind == 'forecasts' else ALERT_FIELDS
    directory = Path(directory)
    if not directory.exists() or not list(directory.glob('part-*.parquet')):
        return pd.DataFrame(columns=fields)
    d = pd.concat((pd.read_parquet(p) for p in sorted(directory.glob('part-*.parquet'))),ignore_index=True)
    return validate_issued_weather(d) if kind == 'forecasts' else validate_issued_alerts(d)
