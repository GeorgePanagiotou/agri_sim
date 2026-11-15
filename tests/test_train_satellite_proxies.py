"""Lightweight offline tests; run under `uv run --extra ml pytest -q tests/test_train_satellite_proxies.py`."""
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

# Load as source when the patch is tested outside the cloned repository.
FILENAME = Path(__file__).resolve().parents[1] / 'src' / 'agrisim' / 'models' / 'train_satellite_proxies.py'
spec = importlib.util.spec_from_file_location('train_satellite_proxies', FILENAME)
ml = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ml
spec.loader.exec_module(ml)


def fake_table(seed=42):
    rng = np.random.default_rng(seed)
    years = np.repeat(np.arange(2013, 2023), 90)
    ids = np.tile(np.arange(90), 10)
    dates = [f'{int(s)}-03-01' for s in years]
    hist = rng.uniform(.15, .85, size=len(years))
    ndvi = np.clip(hist * .7 + rng.normal(0, .08, len(years)), 0, 1)
    y = np.clip(.15 + hist * .25 + ndvi * .42 + rng.normal(0, .09, len(years)), 0, 1)
    klass = np.where(y > .68, 3, np.where(y > .52, 1, 2))
    crops = (klass == 1).astype(int)
    return pd.DataFrame({
        'season': years, 'pixel_id': ids, 'block_id': ids // 10,
        'decision_date': dates,
        'burn_class_2021': np.where(ids < 45, 1, 2),
        'burn_dnbr_2021': ids / 90,
        'terrain_upslope_burned_share': ids / 90,
        'hist_peak_mean_5y': hist,
        'hist_crop_share_5y': np.clip(hist, 0, 1),
        'hist_class_lag1': np.where(hist > .5, 1, 2),
        'ndvi_prior_jan': ndvi,
        'soil_awc_mm_0_30': 80 + ids * .1,
        'post_fire': (years >= 2022).astype(float),
        'rain_prior_30d_mm': years * 2.,
        'target_spring_peak_ndvi': y,
        'target_crop': crops,
        'target_class': klass,
        'lon': 23.5, 'lat': 38.8,
    })


def metadata(table):
    return {
        'as_of': '03-01', 'area': 'evia', 'rows': len(table),
        'features': ['burn_class_2021', 'burn_dnbr_2021',
                     'terrain_upslope_burned_share', 'hist_peak_mean_5y',
                     'hist_crop_share_5y', 'hist_class_lag1',
                     'ndvi_prior_jan', 'soil_awc_mm_0_30', 'post_fire',
                     'rain_prior_30d_mm'],
        'targets': {'target_crop': 'proxy', 'target_class': 'proxy',
                    'target_spring_peak_ndvi': 'proxy'},
        'group_columns': ['season', 'pixel_id', 'block_id'],
        'id_columns': ['decision_date', 'lon', 'lat'],
    }


def test_select_features_drop_weather_and_identifiers():
    df = fake_table()
    cols = ml.select_features(metadata(df))
    assert 'ndvi_prior_jan' in cols
    assert 'hist_peak_mean_5y' in cols
    assert 'rain_prior_30d_mm' not in cols
    assert 'season' not in cols
    assert all(not c.startswith('target_') for c in cols)


def test_pre_fire_leakage_mask():
    df = fake_table()
    features = ml.make_features(df, ml.select_features(metadata(df)))
    old = df.season < 2022
    for c in ml.FUTURE_FIRE_COLUMNS:
        assert features.loc[old, c].isna().all()
    assert np.isfinite(features.loc[~old, 'burn_dnbr_2021']).all()


def test_metadata_integrity():
    df = fake_table()
    ml.validate_table(df, metadata(df))
    bad = metadata(df); bad['rows'] -= 1
    with pytest.raises(ValueError, match='row count'):
        ml.validate_table(df, bad)
    with pytest.raises(ValueError, match='Repeated'):
        ml.validate_table(pd.concat([df, df.iloc[:1]], ignore_index=True),
                          {**metadata(df), 'rows': len(df)+1})


def test_trains_all_three_and_writes_outputs(tmp_path):
    df = fake_table()
    result = ml.train_one(df, metadata(df), '0301', tmp_path, test_from=2021,
                          tasks=('vigour', 'crop', 'class'), n_estimators=15)
    for task in ('vigour', 'crop', 'class'):
        assert (tmp_path / '0301' / f'{task}_xgb.json').exists()
        assert (tmp_path / '0301' / f'{task}_forward_metrics.json').exists()
        assert result['tasks'][task]['model']['rows'] > 0
        assert result['tasks'][task]['historical_baseline']['rows'] > 0
    assert result['holdout_seasons'] == [2021, 2022]


def test_cannot_mix_live_decision_dates(tmp_path):
    df = fake_table()
    live_meta = metadata(df); live_meta['as_of'] = '11-14'
    with pytest.raises(ValueError, match='decision date'):
        ml.train_one(df, metadata(df), '0301', tmp_path, test_from=2021,
                     tasks=('vigour',), live_df=df, live_meta=live_meta, n_estimators=5)


def test_score_works_with_missing_holdout_labels():
    df = fake_table().iloc[:6].copy()
    yy = np.array([.2, .3, np.nan, .5, .6, .7])
    mask = np.array([False, False, True, True, True, True])
    p = np.array([.1, .51, .62, .68])
    results, per_season = ml.evaluate_predictions(df, yy, p, 'vigour', mask)
    assert results['model']['rows'] == 3
