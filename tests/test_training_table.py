"""Offline checks of the training-table helpers (no data files needed)."""
import numpy as np
import pandas as pd

from agrisim.pipelines import build_training_table as bt


def test_decision_date_belongs_to_the_right_calendar_year():
    # season 2025 = Oct 2024 .. Sep 2025
    assert bt.decision_date(2025, "12-01") == pd.Timestamp("2024-12-01")
    assert bt.decision_date(2025, "09-15") == pd.Timestamp("2024-09-15")
    assert bt.decision_date(2025, "03-01") == pd.Timestamp("2025-03-01")


def test_decode_ndvi_matches_cube_encoding():
    v = np.array([0, 1, 51, 201, 255], dtype="uint8")
    out = bt.decode_ndvi(v)
    assert np.isnan(out[0])
    assert np.allclose(out[1:], [-0.25, 0.0, 0.75, 1.02])


def test_rain_features_need_complete_windows():
    idx = pd.date_range("2024-06-01", "2024-12-31", freq="D")
    table = pd.DataFrame({(38.85, 23.35): 1.0, (38.85, 23.45): 2.0}, index=idx)
    f = bt.rain_features(table, pd.Timestamp("2024-12-01"))
    assert f["rain_prior_30d_mm"].tolist() == [30.0, 60.0]
    assert f["rain_since_sep1_mm"].tolist() == [91.0, 182.0]          # 1 Sep .. 30 Nov
    assert f["rain_prev_summer_jja_mm"].tolist() == [92.0, 184.0]
    table.loc["2024-11-20"] = np.nan
    assert np.isnan(bt.rain_features(table, pd.Timestamp("2024-12-01"))["rain_prior_30d_mm"]).all()


def test_indicators_have_a_row_for_the_day_after_the_data():
    from test_environmental_risk import RULES, synthetic   # same synthetic inputs as the risk-engine tests
    data = synthetic(end="2025-11-13")
    ind = bt.indicators_through_next_day(data, RULES)
    today = pd.Timestamp("2025-11-14")
    assert ind.index.max() == today
    plain = bt.er.indicators(data, RULES)
    # the new row is what the engine would say on 14 Nov with data to 13 Nov; earlier rows are unchanged
    assert np.isfinite(ind.loc[today, "rain_long_pct"])
    pd.testing.assert_frame_equal(ind.drop(index=today), plain, check_freq=False)
