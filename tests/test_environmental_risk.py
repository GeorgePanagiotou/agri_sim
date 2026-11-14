"""Offline tests for the past-only climate indicators and the Environmental Risk Engine v1."""
import numpy as np
import pandas as pd
import pytest

from agrisim.decision_engine import environmental_risk as er
from agrisim.features import climate_indices as ci


def daily(values, start="2000-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype="float64")


# ---------- climate_indices ----------

def test_calendar_day_maps_feb29_onto_feb28():
    d = ci.calendar_day(pd.to_datetime(["2020-02-28", "2020-02-29", "2020-03-01", "2021-03-01", "2020-12-31"]))
    assert d.tolist() == [59, 59, 60, 60, 365]


def test_prior_sum_uses_only_completed_days_and_keeps_gaps():
    s = daily([1, 2, 3, 100, 5])
    out = ci.prior_sum(s, 3)
    assert np.isnan(out.iloc[2]) and out.iloc[3] == 6  # day 4 must not see its own 100 mm
    s.iloc[1] = np.nan
    assert ci.prior_sum(s, 3).iloc[3:].isna().all()     # a missing day is not a zero


def test_daily_calendar_required():
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-01", "2020-01-03"]))
    with pytest.raises(ValueError):
        ci.prior_sum(s, 1)


def test_prior_run_resets_and_unknown_breaks_run():
    cond = daily([1, 1, 0, 1, 1, 1, np.nan, 1, 0, 1])
    run = ci.prior_run(cond)
    assert run.iloc[2] == 2 and run.iloc[3] == 0 and run.iloc[6] == 3
    assert np.isnan(run.iloc[7]) and np.isnan(run.iloc[8])  # unknown until a known dry->wet reset
    assert run.iloc[9] == 0


def test_calendar_percentile_mid_rank_for_ties():
    idx = pd.date_range("2001-01-01", "2020-12-31", freq="D")
    s = pd.Series(0.0, index=idx)
    pct = ci.calendar_percentile(s, (2001, 2020), 7)
    assert pct.dropna().between(49.9, 50.1).all()        # all-zero baseline: 0 is typical, not extreme


def test_calendar_quantile_follows_season():
    idx = pd.date_range("1991-01-01", "2020-12-31", freq="D")
    seasonal = 20 + 10 * np.sin(2 * np.pi * (ci.calendar_day(idx) - 110) / 365)
    q = ci.calendar_quantile(pd.Series(seasonal, index=idx), (1991, 2020), 2, 0.9)
    assert q.loc["2000-07-20"] > q.loc["2000-01-20"] + 15


# ---------- engine ----------

RULES = er.load_rules()


def synthetic(seed=0, start="1991-01-01", end="2025-12-31"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="D")
    doy = ci.calendar_day(idx)
    season = np.sin(2 * np.pi * (doy - 110) / 365)
    rain = np.where(rng.random(len(idx)) < 0.25 - 0.15 * season, rng.gamma(0.8, 12, len(idx)), 0.0)
    return pd.DataFrame({
        "power_temp_max_c": 22 + 9 * season + rng.normal(0, 2, len(idx)),
        "power_temp_min_c": 12 + 8 * season + rng.normal(0, 2, len(idx)),
        "power_rain_mm": rain,
        "power_surface_wetness": np.clip(0.5 - 0.2 * season + rng.normal(0, 0.05, len(idx)), 0, 1),
        "power_root_wetness": np.clip(0.55 - 0.15 * season + rng.normal(0, 0.03, len(idx)), 0, 1),
        "gpm_rain_mm": np.where(idx.year >= 2001, rain, np.nan),
        "gpm_product": np.where(idx.year >= 2001, "IMERG_Final_V07", None),
        "smap_surface_m3m3": np.nan,
        "smap_soil_temp_c": np.nan,
    }, index=pd.Index(idx, name="date"))


def test_assess_columns_and_levels_are_valid():
    t = er.assess(synthetic(), RULES, "2021-01-01", "2021-12-31")
    assert len(t) == 365 and t.date.is_unique
    for h in er.HAZARDS:
        assert set(t[f"{h}_label"]) <= {"none", "watch", "warning", "severe", "unknown"}
        assert t[f"explain_{h}"].str.len().gt(20).all()
    assert (t.rain_source == "IMERG").all()
    assert t.risk_method.str.contains("not_probabilities").all()


def test_heat_counts_hot_days_before_the_date_only():
    d = synthetic()
    d.loc["2021-07-01":"2021-07-06", "power_temp_max_c"] = 45.0
    t = er.assess(d, RULES, "2021-07-01", "2021-07-10").set_index("date")
    assert t.loc["2021-07-01", "heat_level"] <= 1           # the heat starts today: not yet known
    assert t.loc["2021-07-07", "hot_days_prior"] == 6
    assert t.loc["2021-07-07", "heat_label"] == "severe"


def test_frost_and_missing_temperature_is_unknown():
    d = synthetic()
    d.loc["2021-01-10":"2021-01-12", "power_temp_min_c"] = -3.0
    d.loc["2021-02-10", "power_temp_min_c"] = np.nan
    t = er.assess(d, RULES, "2021-01-01", "2021-02-20").set_index("date")
    assert t.loc["2021-01-13", "frost_label"] == "warning"
    assert t.loc["2021-02-11", "frost_label"] == "unknown"
    assert "frost" in t.loc["2021-02-11", "hazards_unknown"]


def test_heavy_rain_on_wet_soil_goes_one_level_up():
    d = synthetic()
    d.loc["2021-11-05", ["gpm_rain_mm", "power_rain_mm"]] = 250.0
    t = er.assess(d, RULES, "2021-11-01", "2021-11-10").set_index("date")
    assert t.loc["2021-11-06", "heavy_rain_level"] >= 2
    d.loc["2021-10-18":"2021-11-01", ["gpm_rain_mm", "power_rain_mm"]] = 15.0  # two very wet weeks before
    t2 = er.assess(d, RULES, "2021-11-01", "2021-11-10").set_index("date")
    assert t2.loc["2021-11-06", "rain_antecedent_pct"] >= 90
    assert t2.loc["2021-11-06", "heavy_rain_label"] == "severe"


def test_mild_but_unusual_winter_day_is_not_heat():
    d = synthetic()
    d.loc["2021-01-10":"2021-01-16", "power_temp_max_c"] = 24.0   # far above the January norm, below 30 C
    t = er.assess(d, RULES, "2021-01-17", "2021-01-17")
    assert t.hot_days_prior.iloc[0] == 0 and t.heat_label.iloc[0] == "none"


def test_long_drought_flags_and_imerg_gap_falls_back_to_power():
    d = synthetic()
    d.loc["2022-01-01":"2022-04-30", ["gpm_rain_mm", "power_rain_mm"]] = 0.0
    d.loc["2022-01-01":"2022-04-30", "power_root_wetness"] = 0.05
    d.loc["2023-03-01":"2023-03-31", "gpm_rain_mm"] = np.nan
    t = er.assess(d, RULES, "2022-01-01", "2023-06-30").set_index("date")
    assert t.loc["2022-04-15", "drought_label"] == "severe"
    assert t.loc["2022-04-15", "dry_spell_level"] >= 2
    assert t.loc["2023-03-15", "rain_source"] == "POWER"
    assert t.loc["2022-04-15", "rain_source"] == "IMERG"
