"""Shared input checks: fail loudly rather than treating missing evidence as zero."""
from pathlib import Path
import pandas as pd

def columns(frame, required, *, context='table'):
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f'{context} missing required columns: {sorted(missing)}')
    return frame

def unique_keys(frame, keys):
    columns(frame, keys)
    if frame.duplicated(keys).any():
        raise ValueError(f'Duplicate identifiers on {keys}')
    return frame

def existing_file(path):
    result = Path(path)
    if not result.is_file():
        raise FileNotFoundError(result)
    return result

def safe_dates(series):
    dates = pd.to_datetime(series, errors='raise', utc=True)
    if dates.isna().any():
        raise ValueError('Missing acquisition dates')
    return dates
