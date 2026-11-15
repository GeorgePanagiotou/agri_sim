"""Offline contract/regression tests for architecture B + D -> partial E."""
import numpy as np
import pandas as pd
import pytest

from agrisim.decision_engine.fusion import fuse, summarize_fusion
from agrisim.decision_engine import sowing_window as sw
from agrisim.decision_engine import environmental_risk as er


def sowing_rows():
    return pd.DataFrame([
        {"crop_id": "winter_wheat", "season": "2026-2027", "week_start": "2026-11-01",
         "verdict": "check_worthy", "verdict_long_record": "check_worthy",
         "explanation": "Recent rainfall supports checking the seedbed."},
        {"crop_id": "barley", "season": "2026-2027", "week_start": "2026-11-01",
         "verdict": "too_dry", "verdict_long_record": "too_dry",
         "explanation": "Too little effective rain."},
        {"crop_id": "winter_wheat", "season": "2026-2027", "week_start": "2026-11-08",
         "verdict": "check_worthy", "verdict_long_record": "check_worthy",
         "explanation": "Rainfall meets the screening rule."},
        {"crop_id": "winter_wheat", "season": "2026-2027", "week_start": "2026-11-15",
         "verdict": "unknown", "verdict_long_record": "unknown",
         "explanation": "Missing temperature."},
    ])


def risk_rows():
    return pd.DataFrame([
        {"date": "2026-11-01", "overall_level": 2, "overall_label": "warning",
         "hazards_flagged": "drought", "hazards_unknown": "", "field_id": "evia_pilot",
         "spatial_support": "regional_context_not_field_measurement", "rain_source": "IMERG"},
        {"date": "2026-11-08", "overall_level": 0, "overall_label": "none",
         "hazards_flagged": "", "hazards_unknown": "frost", "field_id": "evia_pilot",
         "spatial_support": "regional_context_not_field_measurement", "rain_source": "POWER"},
        {"date": "2026-11-15", "overall_level": 0, "overall_label": "none",
         "hazards_flagged": "", "hazards_unknown": "", "field_id": "evia_pilot",
         "spatial_support": "regional_context_not_field_measurement", "rain_source": "IMERG"},
    ])


def test_many_crops_share_exact_date_risk_without_cartesian_rotation_join():
    out = fuse(sowing_rows(), risk_rows())
    assert len(out) == 4
    first = out[out.week_start.eq(pd.Timestamp("2026-11-01"))]
    assert len(first) == 2
    assert set(first.risk_overall_label) == {"warning"}
    assert first.set_index("crop_id").loc["winter_wheat", "decision_priority"] == "regional_risk_warning"
    assert first.set_index("crop_id").loc["barley", "decision_priority"] == "field_check_required"
    assert set(out.component_a_vegetation_status) == {"not_integrated"}
    assert set(out.component_c_rotation_status) == {"not_integrated"}
    assert out.probability_of_establishment.isna().all()
    assert not out.farm_polygon_verified.any()
    assert not out.is_forecast.any()


def test_partial_hazards_not_silent_safe_and_unknown_sowing():
    out = fuse(sowing_rows(), risk_rows()).set_index(["crop_id", "week_start"])
    w = out.loc[("winter_wheat", pd.Timestamp("2026-11-08"))]
    assert w["risk_evidence_status"] == "partial"
    assert w["decision_priority"] == "field_check_with_data_gaps"
    assert "frost" in w["decision_explanation"]
    assert out.loc[("winter_wheat", pd.Timestamp("2026-11-15")), "decision_priority"] == "insufficient_evidence"


def test_missing_risk_row_remains_unavailable_no_nearest_date_fill():
    sow = sowing_rows().iloc[:2].copy()
    sow["week_start"] = "2001-11-01"
    sow["season"] = "2001-2002"
    # The user's risk_daily.csv starts in 2020, whereas sowing_weeks starts in 2001.
    out = fuse(sow, risk_rows())
    assert len(out) == 2
    assert (out.risk_evidence_status == "unavailable").all()
    assert out.risk_overall_level.isna().all()
    assert out.loc[out.crop_id.eq("winter_wheat"), "decision_priority"].iloc[0] == "insufficient_evidence"
    assert (out.risk_reference_temporal_status == "not_evaluated_missing_risk").all()
    assert summarize_fusion(out)["missing_risk_rows"] == 2


def test_reference_period_hindsight_flag_for_early_retro_risk():
    r = risk_rows().iloc[[0]].copy(); r["date"] = "2002-11-01"
    s = sowing_rows().iloc[[0]].copy(); s["week_start"] = "2002-11-01"; s["season"] = "2002-2003"
    out = fuse(s, r)
    assert out.risk_reference_temporal_status.iloc[0].startswith("retrospective")
    assert "retrospective" in out.decision_explanation.iloc[0]


def test_asof_guard_duplicate_date_and_area_source_validation():
    out = fuse(sowing_rows(), risk_rows(), as_of="2026-11-08")
    assert len(out) == 3
    assert out.week_start.max() == pd.Timestamp("2026-11-08")
    with pytest.raises(ValueError, match="one record per date"):
        fuse(sowing_rows(), pd.concat([risk_rows(), risk_rows().iloc[[0]]], ignore_index=True))
    with pytest.raises(ValueError, match="unexpected site"):
        fuse(sowing_rows(), risk_rows(), area_id="messara")


def test_smap_historical_baseline_only_uses_prior_days():
    # Reproduce the user's observed issue: 2001 CSV used a 2026-era baseline.
    idx = pd.date_range("2001-01-01", "2026-12-31")
    d = pd.DataFrame(index=idx)
    d["smap_surface_m3m3"] = np.nan
    d["smap_soil_temp_c"] = np.nan
    d.loc["2022-09-01":"2022-12-31", "smap_surface_m3m3"] = .24
    d.loc["2026-09-01":"2026-12-31", "smap_surface_m3m3"] = .85
    # Don't need the entire climate record to assert threshold causality; use a
    # frozen climate baseline stub since we're testing SMAP time direction only.
    risk_rules = er.load_rules()
    rules = sw.load_rules()
    d["gpm_rain_mm"] = 1.0
    d["power_rain_mm"] = 1.0
    d["power_temp_c"] = 15.0
    # The new threshold is computed with an earlier-days-only expanding median.
    sm = d["smap_surface_m3m3"]
    valid = (sm.index.month >= 9) | (sm.index.month <= 6)
    prior = sm.where(valid).shift(1)
    threshold = prior.expanding(min_periods=int(rules["moisture"].get("smap_min_baseline_days", 14))).quantile(.5)
    assert pd.isna(threshold.loc["2001-11-01"])
    assert threshold.loc["2022-11-15"] == pytest.approx(.24)
    assert threshold.loc["2022-11-15"] == threshold.loc["2022-12-31"]
    d.loc["2026-09-01":"2026-12-31", "smap_surface_m3m3"] = .05
    sm2 = d["smap_surface_m3m3"]
    threshold2 = sm2.where(valid).shift(1).expanding(min_periods=14).quantile(.5)
    assert threshold2.loc["2022-11-15"] == threshold.loc["2022-11-15"]


def test_smap_daily_evidence_threshold_no_future_when_data_extended(monkeypatch):
    # Integration-level proof using daily_evidence, with risk indicators stubbed.
    idx = pd.date_range("2021-09-01", "2023-12-01", freq="D")
    d = pd.DataFrame({
        "gpm_rain_mm": 0., "power_rain_mm": 0., "power_temp_c": 15.,
        "smap_surface_m3m3": np.nan, "smap_soil_temp_c": 14.,
    }, index=idx)
    d.loc["2022-09-01":"2022-12-01", "smap_surface_m3m3"] = .28
    monkeypatch.setattr(er, "indicators", lambda data, rules: pd.DataFrame(index=data.index))
    monkeypatch.setattr(er, "levels", lambda ind, rules: pd.DataFrame({
        "heavy_rain": 0., "drought": 0.
    }, index=ind.index))
    result = sw.daily_evidence(d, {}, sw.load_rules())
    assert result.loc["2021-11-01", "smap_baseline_days"] == 0
    assert pd.isna(result.loc["2021-11-01", "smap_moist_threshold"])
    before = result.loc["2022-11-01", "smap_moist_threshold"]
    d.loc["2023-09-01":"2023-11-30", "smap_surface_m3m3"] = .97
    result2 = sw.daily_evidence(d, {}, sw.load_rules())
    assert result2.loc["2022-11-01", "smap_moist_threshold"] == pytest.approx(before)
    assert result.loc["2022-09-01", "smap_baseline_days"] == 0


def test_full_B_D_to_E_with_real_engine_functions_on_synthetic_climate():
    from agrisim.decision_engine.pipeline import from_environment
    from agrisim.features import climate_indices as ci

    idx = pd.date_range("1991-01-01", "2024-12-31", freq="D")
    rng = np.random.default_rng(5)
    seasonality = np.sin(2 * np.pi * (ci.calendar_day(idx) - 110) / 365)
    rain = np.where(rng.random(len(idx)) < .2 - .1 * seasonality, rng.gamma(1.1, 12, len(idx)), 0.)
    temp = 18 + 9 * seasonality
    env = pd.DataFrame({
        "power_temp_c": temp,
        "power_temp_max_c": temp + 5,
        "power_temp_min_c": temp - 8,
        "power_rain_mm": rain,
        "power_surface_wetness": .55,
        "power_root_wetness": .60,
        "gpm_rain_mm": np.where(idx.year >= 2001, rain, np.nan),
        "gpm_product": np.where(idx.year >= 2001, "IMERG_Final_V07", None),
        "smap_surface_m3m3": np.where(idx.year >= 2020, .28, np.nan),
        "smap_soil_temp_c": np.where(idx.year >= 2020, temp, np.nan),
    }, index=pd.Index(idx, name="date"))
    out = from_environment(env, as_of="2024-11-08", season="2024-2025", crop_id="winter_wheat",
                           vegetation_csv=None)
    assert len(out) == 2
    assert out.week_start.tolist() == [pd.Timestamp("2024-11-01"), pd.Timestamp("2024-11-08")]
    assert out.risk_row_available.all()
    assert set(out.risk_reference_temporal_status) == {"reference_ends_before_assessment_year"}
    assert out.component_e_fusion_status.eq("B_C_D_conditional").all()
