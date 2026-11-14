"""Sowing-window engine v1: which candidate weeks deserve a seedbed check, per crop and season.

For every crop window (data/reference/sowing_windows.csv) and every season, candidate weeks start every 7 days from
the window start. Each week is judged with what was known at its start (completed days only):

    too_cold      soil temperature (SMAP L4 0-5 cm; POWER 2 m air as long-record proxy) below the crop minimum
    too_dry       no effective rain recently (IMERG; POWER where IMERG is missing) and SMAP surface not moist
    too_wet       heavy-rain warning/severe from the Environmental Risk Engine: wait, check field access
    check_worthy  none of the above: worth walking the field; the farmer decides
    unknown       an input is missing

Two verdicts per week: `verdict` uses all evidence available (SMAP for the seasons we hold), `verdict_long_record`
uses only IMERG + POWER so every season since 2001 is judged the same way; reliability statistics use the latter.
Regional data (IMERG ~10 km, SMAP ~9 km, POWER ~50 km): the verdict describes the area, never the seedbed itself.

    python -m agrisim.decision_engine.sowing_window
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from agrisim.config import REF, REPO
from agrisim.decision_engine import environmental_risk as er
from agrisim.features import climate_indices as ci

RULES = REPO / "configs" / "sowing_rules.yaml"
WINDOWS = REF / "sowing_windows.csv"
OUT = REPO / "outputs"


def load_rules(path: Path = RULES) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_windows(path: Path = WINDOWS) -> pd.DataFrame:
    w = pd.read_csv(path, dtype={"window_start": str, "window_end": str})
    if w.crop_id.duplicated().any():
        raise ValueError("Duplicate crop_id in sowing windows")
    for col in ("window_start", "window_end"):
        if not w[col].str.fullmatch(r"\d{2}-\d{2}").all():
            raise ValueError(f"{col} must be MM-DD")
    return w


def _season_date(mmdd: str, first_year: int) -> pd.Timestamp:
    """Agricultural season first_year-(first_year+1): Jul-Dec dates fall in first_year, Jan-Jun in the next."""
    month = int(mmdd[:2])
    return pd.Timestamp(f"{first_year if month >= 7 else first_year + 1}-{mmdd}")


def candidate_weeks(windows: pd.DataFrame, first_years, step_days: int = 7) -> pd.DataFrame:
    rows = []
    for w in windows.itertuples(index=False):
        for y in first_years:
            start, end = _season_date(w.window_start, y), _season_date(w.window_end, y)
            if end < start:
                raise ValueError(f"{w.crop_id}: window end before start")
            for i, day in enumerate(pd.date_range(start, end, freq=f"{step_days}D")):
                rows.append({"crop_id": w.crop_id, "season": f"{y}-{y + 1}", "week_index": i,
                             "week_start": day, "window_start": start, "window_end": end})
    return pd.DataFrame(rows)


def daily_evidence(data: pd.DataFrame, risk_rules: dict, rules: dict) -> pd.DataFrame:
    """Past-only daily evidence on the full calendar (index = date)."""
    m, t = rules["moisture"], rules["temperature"]
    ev = pd.DataFrame(index=data.index)
    gpm = ci.prior_sum(data["gpm_rain_mm"], m["rain_window_days"])
    pwr = ci.prior_sum(data["power_rain_mm"], m["rain_window_days"])
    ev["rain_prior_mm"] = gpm.where(gpm.notna(), pwr)
    ev["rain_source"] = np.where(gpm.notna(), "IMERG", np.where(pwr.notna(), "POWER", "none"))
    ev["smap_surface_prior"] = ci.prior_mean(data["smap_surface_m3m3"], m["smap_window_days"],
                                             min_valid=m["smap_window_days"])
    ev["smap_soil_temp_prior_c"] = ci.prior_mean(data["smap_soil_temp_c"], t["smap_window_days"],
                                                 min_valid=t["smap_window_days"] - 2)
    ev["power_temp_prior_c"] = ci.prior_mean(data["power_temp_c"], t["power_proxy_window_days"])
    sm = data["smap_surface_m3m3"]
    season_days = sm[(sm.index.month >= 9) | (sm.index.month <= 6)].dropna()
    ev["smap_moist_threshold"] = float(season_days.quantile(m["smap_moist_quantile"])) if len(season_days) else np.nan
    ev["smap_baseline_days"] = len(season_days)
    levels = er.levels(er.indicators(data, risk_rules), risk_rules)
    ev["heavy_rain_level"] = levels["heavy_rain"]
    ev["drought_level"] = levels["drought"]
    return ev


def _verdict(known, cold, dry, wet):
    return np.select([~known, cold, dry, wet], ["unknown", "too_cold", "too_dry", "too_wet"], default="check_worthy")


def judge(weeks: pd.DataFrame, ev: pd.DataFrame, windows: pd.DataFrame, rules: dict) -> pd.DataFrame:
    m = rules["moisture"]
    w = weeks.merge(windows[["crop_id", "tsoil_min_c", "tsoil_status"]], on="crop_id", how="left")
    w = w.join(ev, on="week_start")
    tmin = w["tsoil_min_c"]
    has_rule = tmin.notna()
    wet = w["heavy_rain_level"] >= rules["too_wet"]["heavy_rain_min_level"]
    rain_ok = w["rain_prior_mm"] >= m["effective_rain_mm"]
    rain_known = w["rain_prior_mm"].notna()

    # All evidence: SMAP where available, else the long-record inputs.
    smap_moist = w["smap_surface_prior"] >= w["smap_moist_threshold"]
    smap_known = w["smap_surface_prior"].notna() & w["smap_moist_threshold"].notna()
    temp = w["smap_soil_temp_prior_c"].where(w["smap_soil_temp_prior_c"].notna(), w["power_temp_prior_c"])
    w["temp_used_c"] = temp
    w["temp_source"] = np.where(w["smap_soil_temp_prior_c"].notna(), "SMAP_L4_soil_0_5cm",
                                np.where(w["power_temp_prior_c"].notna(), "POWER_air_2m_proxy", "none"))
    w["evidence_mode"] = np.where(smap_known, "imerg_smap", "imerg_power")
    known = (rain_known | smap_known) & (~has_rule | temp.notna()) & w["heavy_rain_level"].notna()
    w["verdict"] = _verdict(known, has_rule & (temp < tmin), ~(rain_ok | smap_moist), wet)

    # Long record: IMERG/POWER rain + POWER air temperature only, identical for every season.
    t_long = w["power_temp_prior_c"]
    known_long = rain_known & (~has_rule | t_long.notna()) & w["heavy_rain_level"].notna()
    w["verdict_long_record"] = _verdict(known_long, has_rule & (t_long < tmin), ~rain_ok, wet)

    def text(r):
        parts = [f"rain last {m['rain_window_days']} days {r.rain_prior_mm:.0f} mm ({r.rain_source}; effective "
                 f">= {m['effective_rain_mm']} mm)" if pd.notna(r.rain_prior_mm) else "rain unknown"]
        if pd.notna(r.smap_surface_prior):
            parts.append(f"SMAP surface moisture {r.smap_surface_prior:.3f} m3/m3 (moist >= "
                         f"{r.smap_moist_threshold:.3f}, Sep-Jun median)")
        if pd.notna(r.tsoil_min_c):
            parts.append(f"soil temp {r.temp_used_c:.1f} C ({r.temp_source}; crop minimum {r.tsoil_min_c:.1f} C)"
                         if pd.notna(r.temp_used_c) else "soil temperature unknown")
        else:
            parts.append("no soil-temperature rule for this crop (to source)")
        if r.heavy_rain_level >= rules["too_wet"]["heavy_rain_min_level"]:
            parts.append("heavy rain in the last days: check field access / waterlogging first")
        return f"{r.verdict.replace('_', ' ')}: " + "; ".join(parts) + "."
    w["explanation"] = w.apply(text, axis=1)
    w["method"] = rules["version"] + "_regional_screen_not_success_probability"
    return w


def season_summary(judged: pd.DataFrame, column: str) -> pd.DataFrame:
    def one(g):
        ok = g.loc[g[column].eq("check_worthy"), "week_start"]
        first = ok.min() if len(ok) else pd.NaT
        return pd.Series({
            "weeks": len(g), "weeks_check_worthy": int(len(ok)),
            "weeks_unknown": int(g[column].eq("unknown").sum()),
            "first_check_worthy_week": first,
            "days_after_window_start": (first - g["window_start"].iloc[0]).days if pd.notna(first) else np.nan,
            "verdicts": ",".join(g.sort_values("week_start")[column].str.replace("check_worthy", "ok")),
        })
    return judged.groupby(["crop_id", "season"]).apply(one, include_groups=False).reset_index()


def reliability(seasons: pd.DataFrame) -> pd.DataFrame:
    """Per crop over fully known seasons: share with a workable week, median / latest first week."""
    full = seasons[seasons.weeks_unknown.eq(0)]
    g = full.groupby("crop_id")
    out = pd.DataFrame({
        "seasons": g.size(),
        "first_season": g.season.min(), "last_season": g.season.max(),
        "seasons_with_check_worthy_week": g.weeks_check_worthy.apply(lambda s: int((s > 0).sum())),
        "median_days_to_first_week": g.days_after_window_start.median(),
        "latest_days_to_first_week": g.days_after_window_start.max(),
    })
    out["share_with_check_worthy_week"] = out.seasons_with_check_worthy_week / out.seasons
    out["basis"] = "verdict_long_record (IMERG + POWER, same rules every season); regional, not field-level"
    return out.reset_index()


def run(data: pd.DataFrame | None = None, *, rules: dict | None = None, windows: pd.DataFrame | None = None):
    rules = rules or load_rules()
    windows = windows if windows is not None else load_windows()
    risk_rules = er.load_rules()
    data = data if data is not None else er.load_inputs()
    ev = daily_evidence(data, risk_rules, rules)
    first = int(data["gpm_rain_mm"].first_valid_index().year)
    last = int(data.index.max().year)
    weeks = candidate_weeks(windows, range(first, last + 1), rules["week_step_days"])
    # Weeks after the last data day stay in as "unknown", so a running season never counts as complete.
    weeks = weeks[weeks.window_start <= data.index.max()]
    judged = judge(weeks, ev, windows, rules)
    seasons_all = season_summary(judged, "verdict")
    seasons_long = season_summary(judged, "verdict_long_record")
    return judged, seasons_all, seasons_long, reliability(seasons_long)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args(argv)
    judged, seasons_all, seasons_long, rel = run()
    a.out.mkdir(parents=True, exist_ok=True)
    judged.to_csv(a.out / "sowing_weeks.csv", index=False, float_format="%.3f")
    seasons_all.to_csv(a.out / "sowing_seasons.csv", index=False)
    seasons_long.to_csv(a.out / "sowing_seasons_long_record.csv", index=False)
    rel.to_csv(a.out / "sowing_reliability.csv", index=False, float_format="%.2f")
    print(f"{len(judged)} crop-weeks, {judged.season.nunique()} seasons -> {a.out}")
    print(rel.drop(columns="basis").to_string(index=False))


if __name__ == "__main__":
    main()
