"""Environmental Risk Engine v1: transparent daily drought, dry-spell, heat, frost and heavy-rain levels.

For every date the engine reports what was known at the START of that day (completed days only):
observed indicator values, their percentile against the same calendar dates of a fixed reference period,
a level per hazard (none / watch / warning / severe, or unknown when inputs are missing) and a plain sentence.
Thresholds and their sources live in configs/risk_rules.yaml.

These are heuristic, uncalibrated REGIONAL indicators (POWER ~0.5 deg, IMERG 0.1 deg, SMAP ~9 km). They are not
probabilities, not forecasts and not field measurements.

    python -m agrisim.decision_engine.environmental_risk [--start 2020-09-01] [--end 2026-06-30]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from agrisim.config import PROC, RAW, REPO
from agrisim.features import climate_indices as ci
from agrisim.features.build_environment_multisource import imerg_daily, load_power, smap_daily
from agrisim.features.build_multisource_environment import power_input

RULES = REPO / "configs" / "risk_rules.yaml"
LEVELS = {0: "none", 1: "watch", 2: "warning", 3: "severe"}
HAZARDS = ("drought", "dry_spell", "heat", "frost", "heavy_rain")
SUPPORT = {
    "IMERG": "GPM IMERG 0.1 deg (~10 km) mean over the study area",
    "POWER": "NASA POWER ~0.5 deg regional cell",
}


def load_rules(path: Path = RULES) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_inputs(raw: Path = RAW, processed: Path = PROC, power_path: Path | None = None) -> pd.DataFrame:
    """One row per calendar day from the first POWER day to the last day of any source; gaps stay NaN."""
    power = load_power(power_input(processed, power_path))
    gpm = imerg_daily(raw)
    smap = smap_daily(processed / "evia_sowing" / "smap")
    frames = [power[["date", "power_temp_c", "power_temp_max_c", "power_temp_min_c", "power_rain_mm",
                     "power_surface_wetness", "power_root_wetness"]]]
    if not gpm.empty:
        frames.append(gpm[["date", "gpm_rain_mm", "gpm_product"]])
    if not smap.empty:
        frames.append(smap[["date", "smap_surface_m3m3", "smap_soil_temp_c"]])
    frames = [f.copy() for f in frames]
    for frame in frames:
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        if frame["date"].duplicated().any():
            raise ValueError("Duplicate dates in an input source")
    start = min(f["date"].min() for f in frames)
    end = max(f["date"].max() for f in frames)
    data = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    for frame in frames:
        data = data.merge(frame, on="date", how="left", validate="one_to_one")
    for col in ("gpm_rain_mm", "gpm_product", "smap_surface_m3m3", "smap_soil_temp_c"):
        if col not in data:
            data[col] = np.nan
    return data.set_index("date")


def _flag(condition: pd.Series, known: pd.Series) -> pd.Series:
    """Boolean condition as 1.0/0.0, NaN where the input is unknown."""
    return condition.astype("float64").where(known)


def _rain_indicators(rain: pd.Series, years: tuple[int, int], rules: dict) -> pd.DataFrame:
    dr, ds, hr = rules["drought"], rules["dry_spell"], rules["heavy_rain"]
    out = pd.DataFrame(index=rain.index)
    out["rain_prior_long_mm"] = ci.prior_sum(rain, dr["rain_window_days"])
    out["rain_prior_short_mm"] = ci.prior_sum(rain, dr["rain_short_window_days"])
    out["rain_long_pct"] = ci.calendar_percentile(out["rain_prior_long_mm"], years, dr["half_window_days"])
    dry = _flag(rain < ds["dry_day_max_mm"], rain.notna())
    out["dry_spell_days"] = ci.prior_run(dry)
    out["dry_spell_pct"] = ci.calendar_percentile(out["dry_spell_days"], years, ds["half_window_days"])
    out["rain_max_1d_prior_mm"] = ci.prior_max(rain, hr["window_days"])
    # Rain in the `antecedent_days` before the heavy-rain window (days d-w-a .. d-w-1).
    out["rain_antecedent_mm"] = ci.prior_sum(rain, hr["antecedent_days"]).shift(hr["window_days"])
    out["rain_antecedent_pct"] = ci.calendar_percentile(out["rain_antecedent_mm"], years,
                                                        hr["antecedent_half_window_days"])
    out["heavy_rain_watch_mm"] = ci.wet_day_quantile(rain, years, hr["watch_quantile"], hr["wet_day_min_mm"])
    out["heavy_rain_warning_mm"] = ci.wet_day_quantile(rain, years, hr["warning_quantile"], hr["wet_day_min_mm"])
    return out


def indicators(data: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """Observed, past-only indicator values and percentiles (no levels yet)."""
    p_years = tuple(rules["reference_periods"]["power"])
    g_years = tuple(rules["reference_periods"]["imerg"])
    dr, ht, fr, hr = rules["drought"], rules["heat"], rules["frost"], rules["heavy_rain"]
    out = pd.DataFrame(index=data.index)

    # Rain: IMERG first; POWER (against its own baseline) only on dates where the IMERG window is incomplete.
    gpm = _rain_indicators(data["gpm_rain_mm"], g_years, rules)
    pwr = _rain_indicators(data["power_rain_mm"], p_years, rules)
    use_gpm = gpm["rain_prior_long_mm"].notna()
    for col in gpm:
        out[col] = gpm[col].where(use_gpm, pwr[col])
    out["rain_source"] = np.where(use_gpm, "IMERG", np.where(pwr["rain_prior_long_mm"].notna(), "POWER", "none"))
    product = data["gpm_product"].where(data["gpm_product"].notna(), "")
    late = product.eq("IMERG_Late_V07").astype(float).rolling(dr["rain_window_days"], min_periods=1).max().shift(1)
    out["rain_includes_imerg_late"] = use_gpm & late.fillna(0).astype(bool)

    out["root_wetness_prior"] = ci.prior_mean(data["power_root_wetness"], dr["root_wetness_window_days"])
    out["root_wetness_pct"] = ci.calendar_percentile(out["root_wetness_prior"], p_years, dr["half_window_days"])

    tmax = data["power_temp_max_c"]
    tx90 = ci.calendar_quantile(tmax, p_years, ht["half_window_days"], ht["hot_day_quantile"])
    hot = (tmax > tx90) & (tmax >= ht["min_tmax_c"])
    out["hot_days_prior"] = ci.prior_count(_flag(hot, tmax.notna() & tx90.notna()), ht["window_days"])
    out["tmax_prior_max_c"] = ci.prior_max(tmax, ht["window_days"])
    out["tx90_threshold_c"] = tx90
    tmin = data["power_temp_min_c"]
    out["frost_days_prior"] = ci.prior_count(_flag(tmin < fr["frost_day_max_c"], tmin.notna()), fr["window_days"])
    out["tmin_prior_min_c"] = ci.prior_max(-tmin, fr["window_days"]) * -1

    out["surface_wetness_prior"] = data["power_surface_wetness"].shift(1)  # context only, not used in levels

    out["smap_surface_prior_7d_m3m3"] = ci.prior_mean(data["smap_surface_m3m3"], 7, min_valid=3)
    out["smap_soil_temp_prior_7d_c"] = ci.prior_mean(data["smap_soil_temp_c"], 7, min_valid=3)
    return out


def _band_low(pct: pd.Series, r: dict) -> pd.Series:
    level = np.select([pct <= r["severe_percentile_max"], pct <= r["warning_percentile_max"],
                       pct <= r["watch_percentile_max"]], [3, 2, 1], default=0).astype(float)
    return pd.Series(level, index=pct.index).where(pct.notna())


def levels(ind: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """Integer level per hazard: 0 none .. 3 severe; NaN = unknown (missing input)."""
    dr, ds, ht, fr, hr = (rules[k] for k in ("drought", "dry_spell", "heat", "frost", "heavy_rain"))
    out = pd.DataFrame(index=ind.index)
    out["drought"] = _band_low(ind["rain_long_pct"], dr)

    run, pct = ind["dry_spell_days"], ind["dry_spell_pct"]
    spell = np.select([pct >= ds["severe_percentile_min"], pct >= ds["warning_percentile_min"],
                       pct >= ds["watch_percentile_min"]], [3, 2, 1], default=0).astype(float)
    spell = pd.Series(spell, index=ind.index).where(run >= ds["min_run_days"], 0.0)
    out["dry_spell"] = spell.where(run.notna() & (pct.notna() | (run < ds["min_run_days"])))

    hot = ind["hot_days_prior"]
    out["heat"] = pd.Series(np.select([hot >= ht["severe_min_days"], hot >= ht["warning_min_days"],
                                       hot >= ht["watch_min_days"]], [3, 2, 1], default=0).astype(float),
                            index=ind.index).where(hot.notna())

    frost = ind["frost_days_prior"]
    out["frost"] = pd.Series(np.select([frost >= fr["warning_min_days"], frost >= fr["watch_min_days"]],
                                       [2, 1], default=0).astype(float), index=ind.index).where(frost.notna())

    mx = ind["rain_max_1d_prior_mm"]
    heavy = pd.Series(np.select([mx >= ind["heavy_rain_warning_mm"], mx >= ind["heavy_rain_watch_mm"]],
                                [2, 1], default=0).astype(float), index=ind.index)
    wet_soil = ind["rain_antecedent_pct"] >= hr["antecedent_percentile_min"]
    heavy = heavy.where(~((heavy > 0) & wet_soil), heavy + 1)
    out["heavy_rain"] = heavy.where(mx.notna())
    return out


def _fmt(v: float, nd: int = 0) -> str:
    return "n/a" if pd.isna(v) else f"{v:.{nd}f}"


def explain(ind: pd.DataFrame, lev: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """One plain-language sentence per hazard, quoting the numbers and sources behind the level."""
    p0, p1 = rules["reference_periods"]["power"]
    g0, g1 = rules["reference_periods"]["imerg"]
    dr = rules["drought"]
    out = pd.DataFrame(index=ind.index)
    rows = ind.join(lev.add_prefix("level_"))
    text = {h: [] for h in HAZARDS}
    for r in rows.itertuples():
        src = r.rain_source
        ref = f"{g0}-{g1}" if src == "IMERG" else f"{p0}-{p1}"
        late = " (includes IMERG Late Run days)" if r.rain_includes_imerg_late else ""
        name = lambda h: "unknown (missing input)" if pd.isna(getattr(r, f"level_{h}")) \
            else LEVELS[int(getattr(r, f"level_{h}"))]
        text["drought"].append(
            f"Drought {name('drought')}: rain in the last {dr['rain_window_days']} days {_fmt(r.rain_prior_long_mm)} mm, "
            f"percentile {_fmt(r.rain_long_pct)} of the same dates in {ref} ({src}{late}; low = drier than "
            f"usual). Context only: POWER root-zone wetness percentile {_fmt(r.root_wetness_pct)}.")
        text["dry_spell"].append(
            f"Dry spell {name('dry_spell')}: {_fmt(r.dry_spell_days)} days in a row with < "
            f"{rules['dry_spell']['dry_day_max_mm']} mm ({src}), percentile {_fmt(r.dry_spell_pct)} for this date.")
        text["heat"].append(
            f"Heat {name('heat')}: {_fmt(r.hot_days_prior)} of the last {rules['heat']['window_days']} days "
            f"above the usual-hot threshold ({_fmt(r.tx90_threshold_c, 1)} C = 90th percentile {p0}-{p1}) "
            f"and >= {rules['heat']['min_tmax_c']:.0f} C; "
            f"highest Tmax {_fmt(r.tmax_prior_max_c, 1)} C (POWER).")
        text["frost"].append(
            f"Frost {name('frost')}: {_fmt(r.frost_days_prior)} of the last {rules['frost']['window_days']} days "
            f"below {rules['frost']['frost_day_max_c']:.0f} C; lowest Tmin {_fmt(r.tmin_prior_min_c, 1)} C "
            f"(POWER 2 m air over a ~50 km cell; valley ground frost can be colder).")
        text["heavy_rain"].append(
            f"Heavy rain {name('heavy_rain')}: wettest day of the last {rules['heavy_rain']['window_days']} days "
            f"{_fmt(r.rain_max_1d_prior_mm, 1)} mm ({src}); very wet >= {_fmt(r.heavy_rain_watch_mm, 1)} mm, "
            f"extremely wet >= {_fmt(r.heavy_rain_warning_mm, 1)} mm; rain in the "
            f"{rules['heavy_rain']['antecedent_days']} days before: {_fmt(r.rain_antecedent_mm)} mm, percentile "
            f"{_fmt(r.rain_antecedent_pct)} (one level up if >= {rules['heavy_rain']['antecedent_percentile_min']}: "
            f"ground already wet).")
    for h in HAZARDS:
        out[f"explain_{h}"] = text[h]
    return out


def assess(data: pd.DataFrame, rules: dict, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Full daily risk table for [start, end]; indicators are computed on the whole record first."""
    ind = indicators(data, rules)
    lev = levels(ind, rules)
    window = slice(pd.Timestamp(start) if start else None, pd.Timestamp(end) if end else None)
    ind, lev = ind.loc[window], lev.loc[window]
    table = ind.copy()
    for h in HAZARDS:
        table[f"{h}_level"] = lev[h].astype("Int64")
        table[f"{h}_label"] = lev[h].map(LEVELS).fillna("unknown")
    table["overall_level"] = lev.max(axis=1, skipna=True).astype("Int64")
    table["overall_label"] = lev.max(axis=1, skipna=True).map(LEVELS).fillna("unknown")
    table["hazards_flagged"] = lev.apply(lambda r: ",".join(h for h in HAZARDS if r[h] >= 1), axis=1)
    table["hazards_unknown"] = lev.apply(lambda r: ",".join(h for h in HAZARDS if pd.isna(r[h])), axis=1)
    table = table.join(explain(ind, lev, rules))
    table["rain_support"] = table["rain_source"].map(SUPPORT).fillna("no rain data")
    table["confidence_note"] = np.where(table["rain_source"].eq("POWER"), rules["confidence"]["power_rain_note"],
                                        np.where(table["rain_includes_imerg_late"],
                                                 "IMERG Late Run (not bias-checked against Final) in rain windows",
                                                 ""))
    table["field_id"] = "evia_pilot"
    table["spatial_support"] = "regional_context_not_field_measurement"
    table["risk_method"] = rules["version"] + "_heuristic_levels_not_probabilities"
    return table.reset_index()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default="2020-09-01")
    p.add_argument("--end", default=None, help="Default: last day with any input")
    p.add_argument("--power", type=Path, default=None, help="POWER parquet (default: latest full-span file)")
    p.add_argument("--rules", type=Path, default=RULES)
    p.add_argument("--out", type=Path, default=REPO / "outputs" / "risk_daily.csv")
    a = p.parse_args(argv)
    rules = load_rules(a.rules)
    table = assess(load_inputs(power_path=a.power), rules, a.start, a.end)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(a.out, index=False, float_format="%.3f")
    manifest = {"rules": rules["version"], "rows": len(table),
                "first_day": str(table.date.min().date()), "last_day": str(table.date.max().date()),
                "reference_periods": rules["reference_periods"], "sources": rules["sources"],
                "level_counts": {h: table[f"{h}_label"].value_counts().to_dict() for h in HAZARDS},
                "rain_source_days": table["rain_source"].value_counts().to_dict()}
    a.out.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{len(table)} days -> {a.out}")
    print(json.dumps(manifest["level_counts"], indent=1))


if __name__ == "__main__":
    main()
