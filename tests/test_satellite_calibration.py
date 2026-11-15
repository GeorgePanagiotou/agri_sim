"""Offline tests for calibration logic; real Parquet training needs pyarrow."""

import json
import numpy as np
import pandas as pd
import pytest

from agrisim.models import calibrate_satellite_proxies as uc
from agrisim.models.train_satellite_proxies import validate_table


def test_cqr_offset_is_season_conservative():
    y = np.array([0.10, .20, .30, .40, 0.50, .60, .70, .80, .90, 1.00, 1.10, 1.20])
    lo = y - np.array([.1,.1,.1,.1, .1,.1,.1,.1, .1,.1,.1,.1])
    hi = y + np.array([.1,.1,.1,.1, .1,.1,.1,.1, .1,.1,.1,.1])
    lo[[0,4,8]] += np.array([.20, .30, .40])
    seasons = np.repeat([2014,2015,2016],4)
    offset, parts = uc.season_aware_cqr_offset(y, lo, hi, seasons)
    assert set(parts) == {'2014','2015','2016'}
    assert offset >= max(parts.values())
    assert offset >= 0


def test_missing_seasons_rejected():
    with pytest.raises(ValueError, match='3 distinct'):
        uc.season_aware_cqr_offset(np.array([1.,2.,3.]),
                                   np.zeros(3),np.ones(3),np.array([2014,2014,2015]))


def test_quantile_crossings_are_sorted():
    lo, hi = uc.interval_bounds(np.array([.7,.2]), np.array([.4,.5]))
    assert lo.tolist() == [.4,.2]
    assert hi.tolist() == [.7,.5]


def test_real_xgboost_quantile_api():
    rng = np.random.default_rng(31)
    x = pd.DataFrame({'a': rng.normal(size=150), 'b': rng.normal(size=150)})
    y = (x['a']*.25+rng.normal(scale=.1, size=150)).to_numpy()
    model = uc.make_quantile_model(0.1, estimators=4)
    model.fit(x,y)
    assert np.isfinite(model.predict(x.iloc[:10])).all()


def fake_data():
    rng = np.random.default_rng(4)
    rows = []
    for season in range(2002,2027):
        for pix in range(50):
            hist = rng.uniform(.2,.8)
            ndvi = .5*hist + .01*(season-2002) + rng.normal(scale=.14)
            prob = .2+ .6*(hist>.5) + .08*(ndvi>.45)
            crop = int(rng.random() < prob)
            rows.append({'season': season, 'pixel_id': pix,
                         'block_id': pix//5, 'decision_date': f'{season}-03-01',
                         'hist_peak_mean_5y': hist,
                         'hist_crop_share_5y': min(.95, max(.05,prob)),
                         'ndvi_prior_feb': ndvi,
                         'soil_ph_0_30': 5.5 + pix/50,
                         'burn_class_2021': 1 if season >= 2022 else np.nan,
                         'post_fire': int(season>=2022),
                         'target_spring_peak_ndvi': ndvi*.5+.3+rng.normal(scale=.08),
                         'target_crop':crop,'target_class':1 if crop else 2})
    df = pd.DataFrame(rows)
    meta = {'as_of':'03-01','rows':len(df),'area':'evia',
            'features':['hist_peak_mean_5y','hist_crop_share_5y',
                        'ndvi_prior_feb','soil_ph_0_30','burn_class_2021','post_fire'],
            'targets':{'target_spring_peak_ndvi':'proxy','target_crop':'proxy','target_class':'proxy'},
            'group_columns':['season','pixel_id','block_id'],
            'id_columns':['decision_date']}
    return df,meta


def test_full_calibration_smoke(tmp_path):
    df, meta = fake_data()
    validate_table(df,meta)
    result = uc.evaluate_split(df,meta,date_code='0301',output=tmp_path,
                               estimators=8,seed=5)
    assert result['evaluation_seasons'] == list(range(2018,2027))
    assert result['calibration_seasons'] == list(range(2014,2018))
    assert 'burn_class_2021' in result['dropped_all_missing_features']
    assert 0 <= result['results']['vigour']['cqr_interval_coverage'] <= 1
    assert 0 <= result['results']['crop']['calibrated_brier'] <= 1
    assert (tmp_path/'crop_isotonic_calibrator.joblib').exists()
    assert (tmp_path/'calibration_by_season.csv').exists()
    assert len(pd.read_csv(tmp_path/'calibration_by_season.csv')) == 9
    j = json.loads((tmp_path/'calibration_manifest.json').read_text())
    assert j['model_status'].startswith('experimental')
