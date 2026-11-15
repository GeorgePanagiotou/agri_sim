"""Offline regression tests. No satellite download, Parquet dependency or plot package needed."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from agrisim.models import calibrate_satellite_rolling as rc
from agrisim.models import calibrate_satellite_proxies as fixed


def synthetic_data():
    rng = np.random.default_rng(33)
    rows = []
    for season in range(2002, 2027):
        for pixel in range(120):
            history = 0.25 + pixel / 400
            ndvi = 0.5 * history + rng.normal(0, 0.14)
            probability = min(0.90, max(.08, .25 + .9 * history + .3 * ndvi))
            crop = int(rng.random() < probability)
            rows.append({"season": season, "pixel_id": pixel, "block_id": pixel // 5,
                         "decision_date": f"{season}-03-01",
                         "hist_peak_mean_5y": history,
                         "hist_crop_share_5y": probability,
                         "ndvi_prior_feb": ndvi,
                         "soil_ph_0_30": 5.2 + pixel / 100,
                         "burn_class_2021": 1 if season >= 2022 else float('nan'),
                         "post_fire": int(season >= 2022),
                         "target_spring_peak_ndvi": ndvi * .5 + .35 + rng.normal(0, .07),
                         "target_crop": crop, "target_class": 1 if crop else 2})
    df = pd.DataFrame(rows)
    meta = {"as_of": "03-01", "rows": len(df), "area": "evia",
            "features": ["hist_peak_mean_5y", "hist_crop_share_5y", "ndvi_prior_feb",
                         "soil_ph_0_30", "burn_class_2021", "post_fire"],
            "targets": {"target_crop": "proxy", "target_class": "proxy",
                        "target_spring_peak_ndvi": "proxy"},
            "group_columns": ["season", "pixel_id", "block_id"],
            "id_columns": ["decision_date"]}
    return df, meta


def test_splits_use_past_only_and_evolve():
    folds = rc.season_splits(np.repeat(np.arange(2002, 2027), 7))
    assert len(folds) == 9
    for fold in folds:
        assert all(t < fold.calibration[0] for t in fold.train)
        assert max(fold.calibration) == fold.evaluation - 1
        assert not (set(fold.train) & set(fold.calibration))
        assert fold.evaluation not in fold.train + fold.calibration
    assert folds[0].train[-1] == 2014
    assert folds[0].calibration == (2015, 2016, 2017)
    assert folds[-1].train[-1] == 2022
    assert folds[-1].calibration == (2023, 2024, 2025)


def test_rejects_no_valid_split():
    with pytest.raises(ValueError):
        rc.season_splits(np.arange(2002, 2010), start_season=2018)
    with pytest.raises(ValueError, match="three"):
        rc.season_splits(np.arange(2002, 2027), calibration_seasons=2)


def test_probability_calibrators_and_weights():
    rng = np.random.default_rng(7)
    s = np.repeat([2014, 2015, 2016], [5, 20, 100])
    weights = rc.season_equal_weights(s)
    sums = [weights[s == y].sum() for y in [2014, 2015, 2016]]
    assert np.allclose(sums, sums[0])
    p = np.clip(rng.beta(2, 3, size=len(s)), .01, .99)
    y = (rng.random(len(s)) < p).astype(int)
    sigmoid, iso = rc.fit_probability_calibrators(p, y, s)
    pred = rc.probability_predictions(np.linspace(.01, .99, 20), sigmoid, iso)
    for method in pred.values():
        assert np.isfinite(method).all()
        assert ((method >= 0) & (method <= 1)).all()
        assert np.all(np.diff(method) >= -1e-8)


def test_reliability_counts_are_complete():
    example = pd.DataFrame({"season": [2018, 2018, 2019, 2019],
                            "actual_crop": [0, 1, 1, 0],
                            "crop_probability_raw": [.2, .8, .7, .3],
                            "crop_probability_sigmoid": [.25, .6, .5, .3],
                            "crop_probability_isotonic": [.1, .8, .9, .1]})
    overall = rc.reliability_table(example)
    per_year = rc.reliability_table(example, include_season=True)
    for name in ("raw", "sigmoid", "isotonic"):
        assert overall.loc[overall.method == name, "count"].sum() == 4
        assert per_year.loc[per_year.method == name, "count"].sum() == 4


def test_full_rolling_smoke_with_two_unseen_seasons(tmp_path):
    df, meta = synthetic_data()
    result = rc.run_rolling_calibration(df, meta, date_code="0301", output=tmp_path,
                                         start_season=2018, end_season=2019,
                                         estimators=6, seed=9)
    assert result["evaluation_rows"] == 240
    assert [row["test_season"] for row in result["folds"]] == [2018, 2019]
    assert result["folds"][0]["train_seasons"][-1] == 2014
    assert result["folds"][1]["train_seasons"][-1] == 2015
    assert "burn_class_2021" in result["folds"][0]["dropped_all_missing_training_features"]
    assert 0 <= result["aggregate_metrics"]["ndvi"]["conformal"]["coverage"] <= 1
    assert set(result["aggregate_metrics"]["crop"]) == {"raw", "sigmoid", "isotonic"}
    assert (tmp_path / "rolling_by_season.csv").exists()
    assert len(pd.read_csv(tmp_path / "rolling_by_season.csv")) == 2
    assert len(pd.read_csv(tmp_path / "rolling_evaluation_predictions.csv.gz")) == 240
    assert (tmp_path / "crop_reliability_diagram.svg").exists()
    assert (tmp_path / "ndvi_coverage_by_season.svg").exists()
    assert "<svg" in (tmp_path / "crop_reliability_diagram.svg").read_text()
    assert len(json.loads((tmp_path / "rolling_manifest.json").read_text())["folds"]) == 2


def test_original_calibration_remains_supported():
    assert callable(fixed.evaluate_split)
    assert callable(fixed.season_aware_cqr_offset)
