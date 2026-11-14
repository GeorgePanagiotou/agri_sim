"""Offline tests for the sowing-window engine v1 (synthetic weather, no downloads)."""
import numpy as np
import pandas as pd

from agrisim.decision_engine import sowing_window as sw
from agrisim.features import climate_indices as ci

WINDOWS = pd.DataFrame({
    "crop_id": ["winter_wheat", "chickpea", "phacelia"],
    "window_start": ["11-01", "11-15", "09-10"], "window_end": ["12-15", "12-31", "10-15"],
    "tsoil_min_c": [1.3, 6.1, np.nan], "tsoil_status": ["literature", "literature_to_verify", "to_source"],
})


def synthetic(seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1991-01-01", "2024-06-30", freq="D")
    season = np.sin(2 * np.pi * (ci.calendar_day(idx) - 110) / 365)
    rain = np.where(rng.random(len(idx)) < 0.25 - 0.15 * season, rng.gamma(0.8, 10, len(idx)), 0.0)
    temp = 17 + 8 * season + rng.normal(0, 1.5, len(idx))
    return pd.DataFrame({
        "power_temp_c": temp, "power_temp_max_c": temp + 5, "power_temp_min_c": temp - 5,
        "power_rain_mm": rain, "power_surface_wetness": 0.5, "power_root_wetness": 0.6,
        "gpm_rain_mm": np.where(idx.year >= 2001, rain, np.nan),
        "gpm_product": np.where(idx.year >= 2001, "IMERG_Final_V07", None),
        "smap_surface_m3m3": np.nan, "smap_soil_temp_c": np.nan,
    }, index=pd.Index(idx, name="date"))


def run(data):
    return sw.run(data, windows=WINDOWS)


def test_candidate_weeks_every_7_days_inside_the_window():
    w = sw.candidate_weeks(WINDOWS.iloc[[0]], [2024])
    assert w.week_start.dt.strftime("%m-%d").tolist() == ["11-01", "11-08", "11-15", "11-22", "11-29", "12-06",
                                                         "12-13"]
    assert (w.season == "2024-2025").all()
    jan = sw.candidate_weeks(pd.DataFrame({"crop_id": ["x"], "window_start": ["12-20"], "window_end": ["01-10"]}),
                             [2024])
    assert jan.week_start.min() == pd.Timestamp("2024-12-20") and jan.week_start.max() == pd.Timestamp("2025-01-10")


def test_dry_then_rain_scope_example_and_no_look_ahead():
    d = synthetic()
    d.loc["2022-10-20":"2022-11-30", ["gpm_rain_mm", "power_rain_mm"]] = 0.0
    d.loc["2022-11-12", ["gpm_rain_mm", "power_rain_mm"]] = 25.0
    d.loc["2022-11-08", ["gpm_rain_mm", "power_rain_mm"]] = 0.0
    judged, *_ = run(d)
    wheat = judged[(judged.crop_id == "winter_wheat") & (judged.season == "2022-2023")].set_index("week_start")
    assert wheat.loc["2022-11-08", "verdict_long_record"] == "too_dry"
    assert wheat.loc["2022-11-15", "verdict_long_record"] == "check_worthy"
    d.loc["2022-11-08", ["gpm_rain_mm", "power_rain_mm"]] = 80.0       # rain ON the week start is not yet known
    judged2, *_ = run(d)
    w2 = judged2[(judged2.crop_id == "winter_wheat") & (judged2.season == "2022-2023")].set_index("week_start")
    assert w2.loc["2022-11-08", "verdict_long_record"] == "too_dry"


def test_cold_week_hits_chickpea_not_wheat_and_crops_without_rule_skip_it():
    d = synthetic()
    d.loc["2021-11-01":"2021-12-31", "power_temp_c"] = 4.0
    d.loc["2021-11-01":"2021-12-31", ["gpm_rain_mm", "power_rain_mm"]] = 3.0
    judged, *_ = run(d)
    s = judged[judged.season == "2021-2022"]
    assert (s[s.crop_id == "chickpea"].verdict_long_record == "too_cold").all()
    assert not (s[s.crop_id == "winter_wheat"].verdict_long_record == "too_cold").any()
    assert s[s.crop_id == "phacelia"].explanation.str.contains("no soil-temperature rule").all()


def test_smap_used_when_present_and_missing_inputs_are_unknown():
    d = synthetic()
    d.loc["2022-09-01":"2023-06-30", "smap_surface_m3m3"] = 0.30
    d.loc["2022-09-01":"2023-06-30", "smap_soil_temp_c"] = 12.0
    d.loc["2022-11-01":"2022-11-30", "smap_surface_m3m3"] = 0.45      # moist seedbed despite no rain
    d.loc["2022-10-20":"2022-11-30", ["gpm_rain_mm", "power_rain_mm"]] = 0.0
    d.loc["2023-10-01":"2023-12-31", ["gpm_rain_mm", "power_rain_mm"]] = np.nan
    judged, seasons_all, seasons_long, rel = run(d)
    w = judged[(judged.crop_id == "winter_wheat") & (judged.season == "2022-2023")].set_index("week_start")
    assert w.loc["2022-11-15", "evidence_mode"] == "imerg_smap"
    assert w.loc["2022-11-15", "verdict"] == "check_worthy"
    assert w.loc["2022-11-15", "verdict_long_record"] == "too_dry"
    gap = judged[(judged.season == "2023-2024") & judged.crop_id.isin(["winter_wheat", "chickpea"])]
    assert (gap.verdict_long_record == "unknown").all()     # rain gap Oct-Dec 2023 covers these windows
    wheat_seasons = seasons_long[seasons_long.crop_id == "winter_wheat"].set_index("season")
    assert wheat_seasons.loc["2023-2024", "weeks_unknown"] > 0
    assert rel.set_index("crop_id").loc["winter_wheat", "seasons"] == (wheat_seasons.weeks_unknown == 0).sum()
    assert rel.share_with_check_worthy_week.between(0, 1).all()
