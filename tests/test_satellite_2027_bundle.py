"""Offline synthetic tests for the 2027 staging bundle and fire-feature ablation."""
import json
import numpy as np
import pandas as pd
import pytest
from agrisim.models import satellite_bundle_2027 as bundle
from agrisim.models import ablate_satellite_fire as fire
from test_satellite_rolling_calibration import synthetic_data


def test_bundle_fixed_features_no_fire():
    df, meta = synthetic_data()
    seasons = df.season.to_numpy()
    names = bundle.fixed_feature_names(meta, df, seasons <= 2023)
    assert 'burn_class_2021' not in names
    assert 'hist_peak_mean_5y' in names
    assert 'post_fire' in names


def test_bundle_train_and_infer_matching_2027(tmp_path):
    df, meta = synthetic_data()
    result = bundle.create_2027_bundle(df, meta, date_code='0301',
                                       output_dir=tmp_path / '2027', estimators=6)
    assert result['fit_seasons'][-1] == 2023
    assert result['calibration_seasons'] == [2024, 2025, 2026]
    assert result['crop_probability_method'] == 'sigmoid'
    assert not set(result['features']) & bundle.FUTURE_FIRE_COLUMNS
    assert all((tmp_path / '2027' / name).exists() for name in [
        'vigour_xgb.json', 'crop_xgb.json', 'vigour_q10_xgb.json', 'vigour_q90_xgb.json',
        'crop_sigmoid_calibrator.joblib', 'bundle_manifest.json'])
    # Build a true 2027-labeled prediction DATE, but NO known future targets.
    future = df[df.season == 2026].copy()
    future['season'] = 2027
    future['decision_date'] = '2027-03-01'
    for target in ('target_crop', 'target_class', 'target_spring_peak_ndvi'):
        future[target] = np.nan
    live_meta = dict(meta, rows=len(future))
    preds = bundle.infer_bundle(future, live_meta, bundle_dir=tmp_path / '2027')
    assert len(preds) == len(future)
    assert np.isfinite(preds['pred_spring_peak_ndvi']).all()
    assert (preds.ndvi_interval_lower_80_target <= preds.ndvi_interval_upper_80_target).all()
    assert preds.crop_proxy_probability_experimental.between(0, 1).all()
    wrong = dict(live_meta, as_of='04-01')
    with pytest.raises(ValueError, match='as_of'):
        bundle.infer_bundle(future, wrong, bundle_dir=tmp_path / '2027')
    with pytest.raises(ValueError, match='empty'):
        previous = future.copy();previous['target_crop']=1
        bundle.infer_bundle(previous, live_meta, bundle_dir=tmp_path / '2027')


def test_april_bundle_uses_raw_probabilities(tmp_path):
    df, meta = synthetic_data()
    # synthetic table is March data; mutate decision_date & as_of to April for test only.
    df['decision_date'] = df.season.astype(str) + '-04-01'
    meta['as_of'] = '04-01'
    result = bundle.create_2027_bundle(df, meta, date_code='0401',
                                       output_dir=tmp_path / '0401', estimators=6)
    assert result['crop_probability_method'] == 'raw'


def test_ablation_variants_and_delta_report(tmp_path):
    df, meta = synthetic_data()
    result = fire.run_ablation(df, meta, date_code='0301', output_dir=tmp_path / 'ablation',
                               estimators=6, start_season=2026, end_season=2026)
    assert result['seasons'] == [2026]
    row = result['comparison'][0]
    assert row['features_dynamic'] == row['features_fixed'] + 1
    assert (tmp_path / 'ablation' / 'ablation_by_season.csv').exists()
    d = json.loads((tmp_path / 'ablation' / 'fixed_no_fire' / 'rolling_manifest.json').read_text())
    assert d['feature_variant'] == 'fixed_no_fire'
    assert 'burn_class_2021' not in d['folds'][0]['features']
