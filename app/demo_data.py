"""Deterministic SYNTHETIC records for the AgriSim application/output UI.

All values, site locations, alerts, and rankings generated here are demonstration
fixtures. No predictions, real farm polygons, or real measurements are implied.
The module contains no Streamlit imports and can be tested independently.
"""
from __future__ import annotations

from datetime import date
from itertools import permutations
import hashlib
import json

import numpy as np
import pandas as pd

FIELDS = {
    "Demo site A": {"id": "DEMO-A", "lat": 38.75920, "lon": 23.43232, "note": "Synthetic point near the Evia pilot location"},
    "Demo site B": {"id": "DEMO-B", "lat": 38.75310, "lon": 23.44810, "note": "Illustrative location — not a verified parcel"},
    "Demo site C": {"id": "DEMO-C", "lat": 38.76880, "lon": 23.41870, "note": "Illustrative location — not a verified parcel"},
}
SEASONS = ["2023-2024", "2024-2025", "2025-2026"]
CROPS = ["Wheat", "Barley", "Maize", "Chickpea", "Dry pea"]
CROP_RULES = {
    "Wheat": {"months": (10, 11, 12), "temp": (8, 18), "moist": (0.23, 0.34), "suitability": 78, "water": 75, "family": "Cereal"},
    "Barley": {"months": (10, 11, 12), "temp": (7, 17), "moist": (0.20, 0.32), "suitability": 71, "water": 82, "family": "Cereal"},
    "Maize": {"months": (3, 4, 5), "temp": (15, 25), "moist": (0.25, 0.36), "suitability": 64, "water": 39, "family": "Cereal"},
    "Chickpea": {"months": (11, 12, 1, 2), "temp": (9, 19), "moist": (0.20, 0.31), "suitability": 70, "water": 86, "family": "Legume"},
    "Dry pea": {"months": (10, 11, 12, 1), "temp": (8, 17), "moist": (0.22, 0.32), "suitability": 67, "water": 80, "family": "Legume"},
}


def _seed(*parts: str) -> int:
    payload = "|".join(parts).encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest()[:8], 16)


def seasonal_dates(season: str) -> pd.DatetimeIndex:
    if season not in SEASONS:
        raise ValueError(f"Unknown season: {season}")
    year = int(season[:4])
    return pd.date_range(f"{year}-09-01", f"{year+1}-06-30", freq="D")


def make_environment(field: str, season: str) -> pd.DataFrame:
    """Generate stable, explicitly synthetic environmental time series."""
    if field not in FIELDS:
        raise ValueError(f"Unknown demo site: {field}")
    days = seasonal_dates(season)
    n = len(days)
    t = np.arange(n, dtype=float)
    rng = np.random.default_rng(_seed(field, season))
    site_offset = list(FIELDS).index(field)

    # September starts warm, winter is cooler, late spring warms again.
    air_temp = 16.6 + 10.4 * np.cos(2 * np.pi * (t + 52) / 365) + site_offset * 0.4 + rng.normal(0, 1.6, n)
    soil_temp = air_temp * 0.73 + 4.2 + rng.normal(0, 0.7, n)
    wet_season = 0.29 + 0.11 * np.cos(2 * np.pi * (t - 115) / 365)
    rain = np.where(rng.random(n) < wet_season, rng.gamma(1.6, 5.5, n), 0.0)
    rain = np.maximum(rain, 0.0)
    recent_rain = pd.Series(rain).rolling(8, min_periods=1).sum().to_numpy()
    soil_moisture = np.clip(
        0.245 + 0.07 * np.sin(2 * np.pi * (t - 83) / 365)
        + 0.00065 * recent_rain + rng.normal(0, 0.014, n) - 0.005 * site_offset,
        0.12, 0.43,
    )
    sigmoid = lambda x: 1.0 / (1.0 + np.exp(-x))
    vegetation = np.clip(
        0.145 + 0.66 * sigmoid((t - 168) / 26) - 0.56 * sigmoid((t - 270) / 9)
        + rng.normal(0, 0.027, n) + 0.012 * site_offset,
        0.06, 0.91,
    )
    # Simulate a quality-masked satellite acquisition about every 5 days.
    observation = (np.arange(n) % 5 == site_offset) & (rng.random(n) > 0.26)
    ndvi = np.where(observation, vegetation, np.nan)
    clear_fraction = np.where(observation, rng.uniform(0.80, 1.0, n), np.nan)

    frame = pd.DataFrame({
        "date": days,
        "field_id": FIELDS[field]["id"],
        "season": season,
        "air_temp_c": air_temp.round(2),
        "soil_temp_c": soil_temp.round(2),
        "rain_mm": rain.round(2),
        "soil_moisture_m3m3": soil_moisture.round(4),
        "ndvi": np.round(ndvi, 4),
        "clear_fraction": np.round(clear_fraction, 2),
    })
    # Features for assessment at the START of a day use prior days only.
    frame["rain_prior_7d_mm"] = frame["rain_mm"].shift(1).rolling(7, min_periods=7).sum().round(2)
    frame["rain_prior_14d_mm"] = frame["rain_mm"].shift(1).rolling(14, min_periods=14).sum().round(2)
    frame["temp_prior_7d_c"] = frame["air_temp_c"].shift(1).rolling(7, min_periods=7).mean().round(2)
    frame["soil_moisture_prior_7d"] = frame["soil_moisture_m3m3"].shift(1).rolling(7, min_periods=7).mean().round(4)
    frame["soil_temp_prior_7d_c"] = frame["soil_temp_c"].shift(1).rolling(7, min_periods=7).mean().round(2)
    frame["season_day"] = np.arange(n)
    return frame


def _bounded(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return round(float(np.clip(value, lo, hi)), 1)


def risk_scores(row: pd.Series) -> dict[str, dict]:
    """Explainable mock indicator scores. NOT calibrated probabilities."""
    moisture = float(row["soil_moisture_m3m3"])
    temp = float(row["air_temp_c"])
    rain7 = float(row["rain_prior_7d_mm"]) if pd.notna(row["rain_prior_7d_mm"]) else np.nan
    rain14 = float(row["rain_prior_14d_mm"]) if pd.notna(row["rain_prior_14d_mm"]) else np.nan
    moisture_dry = max(0, (0.31 - moisture) / 0.19 * 100)
    # Unknown prior rainfall must not be silently replaced by 0 mm.
    dry = _bounded(0.65 * moisture_dry + 0.35 * max(0, (28 - rain14) / 28 * 100)) if np.isfinite(rain14) else _bounded(moisture_dry)
    low_moisture = _bounded((0.34 - moisture) / 0.19 * 100)
    heat = _bounded((temp - 22) / 15 * 100)
    excess = _bounded(max((rain7 - 18) / 45 if np.isfinite(rain7) else 0.0, (moisture - 0.32) / 0.10) * 100)
    rain14_note = f"prior 14-day rainfall {rain14:.1f} mm" if np.isfinite(rain14) else "prior 14-day rainfall unavailable"
    rain7_note = f"prior 7-day rainfall {rain7:.1f} mm" if np.isfinite(rain7) else "prior 7-day rainfall unavailable"
    return {
        "Drought": {"score": dry, "driver": f"{rain14_note}; soil moisture {moisture:.2f} m³/m³"},
        "Low moisture": {"score": low_moisture, "driver": f"Synthetic soil moisture {moisture:.2f} m³/m³"},
        "Heat": {"score": heat, "driver": f"Synthetic air temperature {temp:.1f} °C"},
        "Excess water": {"score": excess, "driver": f"{rain7_note}; soil moisture {moisture:.2f} m³/m³"},
    }


def risk_level(score: float) -> str:
    return "High" if score >= 70 else "Moderate" if score >= 40 else "Low"


def rank_sowing_windows(frame: pd.DataFrame, crop: str) -> pd.DataFrame:
    """Weekly retrospective mock ranking using past-only weather summaries."""
    if crop not in CROP_RULES:
        raise ValueError(crop)
    c = CROP_RULES[crop]
    data = frame[(frame["date"].dt.month.isin(c["months"])) & frame["rain_prior_7d_mm"].notna() & frame["soil_temp_prior_7d_c"].notna()].copy()
    rows = []
    for start in data.iloc[::7].itertuples(index=False):
        temp = float(start.soil_temp_prior_7d_c)
        moist = float(start.soil_moisture_prior_7d)
        rain = float(start.rain_prior_7d_mm)
        temp_center = sum(c["temp"]) / 2
        moisture_center = sum(c["moist"]) / 2
        temp_fit = _bounded(100 - abs(temp - temp_center) * 12)
        moisture_fit = _bounded(100 - abs(moist - moisture_center) * 550)
        rain_fit = _bounded(100 - abs(rain - 13) * 2.0)
        score = _bounded(0.42 * temp_fit + 0.38 * moisture_fit + 0.20 * rain_fit)
        # A UI demo proxy for agreement among three heuristic components; NOT calibrated model confidence.
        confidence_proxy = _bounded(100 - 1.15 * np.std([temp_fit, moisture_fit, rain_fit]))
        rows.append({
            "window_start": pd.Timestamp(start.date).date(),
            "window_end": (pd.Timestamp(start.date) + pd.Timedelta(days=13)).date(),
            "demo_score": score,
            "demo_confidence_proxy": confidence_proxy,
            "soil_temp_c": round(temp, 1),
            "soil_moisture_m3m3": round(moist, 3),
            "rain_prior_7d_mm": round(rain, 1),
        })
    if not rows:
        return pd.DataFrame(columns=["window_start", "window_end", "demo_score", "demo_confidence_proxy", "soil_temp_c", "soil_moisture_m3m3", "rain_prior_7d_mm"])
    return pd.DataFrame(rows).sort_values(["demo_score", "window_start"], ascending=[False, True]).reset_index(drop=True)


def rank_rotations(previous_crop: str, weights: dict[str, int]) -> pd.DataFrame:
    """Rank hypothetical crop sequences. No yield or soil-health claims."""
    if previous_crop not in CROPS:
        raise ValueError(previous_crop)
    keys = ("Suitability", "Water efficiency", "Diversity")
    if set(weights) != set(keys) or sum(weights.values()) <= 0:
        raise ValueError("Supply a positive weight for one or more criteria")
    result = []
    for candidate in permutations(CROPS, 3):
        family = [CROP_RULES[previous_crop]["family"]] + [CROP_RULES[x]["family"] for x in candidate]
        diverse = sum(a != b for a, b in zip(family[:-1], family[1:])) / 3 * 100
        suitability = np.mean([CROP_RULES[x]["suitability"] for x in candidate])
        water = np.mean([CROP_RULES[x]["water"] for x in candidate])
        score = (
            weights["Suitability"] * suitability
            + weights["Water efficiency"] * water
            + weights["Diversity"] * diverse
        ) / sum(weights.values())
        soil_health_proxy = _bounded(35 + 12 * sum(CROP_RULES[x]["family"] == "Legume" for x in candidate) + 9 * sum(a != b for a, b in zip(family[:-1], family[1:])))
        result.append({
            "rotation": " → ".join(candidate),
            "sequence": candidate,
            "demo_score": _bounded(score),
            "suitability": _bounded(suitability),
            "yield_fit_proxy": _bounded(suitability),
            "soil_health_proxy": soil_health_proxy,
            "water_efficiency": _bounded(water),
            "family_switches": sum(a != b for a, b in zip(family[:-1], family[1:])),
            "includes_legume": any(CROP_RULES[x]["family"] == "Legume" for x in candidate),
        })
    return pd.DataFrame(result).sort_values(["demo_score", "rotation"], ascending=[False, True]).reset_index(drop=True)


def report_markdown(field: str, season: str, crop: str, day: date, frame: pd.DataFrame, recommendation: pd.Series, risk: dict, rotations: pd.DataFrame) -> str:
    """Markdown report with unmistakable synthetic-data caveat."""
    score = max(v["score"] for v in risk.values())
    return f"""# AgriSim AI — Demonstration Report

> **SYNTHETIC DEMO DATA.** Not a real forecast, verified parcel assessment, crop success probability, or agronomic recommendation.

- **Demo site:** {field}
- **Growing season:** {season}
- **Example crop:** {crop}
- **Assessment date:** {day.isoformat()}
- **Environmental records:** {len(frame)} synthetic daily rows

## Sowing-window demonstration

- Suggested illustrative period: **{recommendation['window_start']} – {recommendation['window_end']}**
- **Demo suitability score:** {recommendation['demo_score']}/100 (not a probability)
- **Mock confidence indicator:** {recommendation['demo_confidence_proxy']}/100 (not calibrated)

## Environmental risk indicators

- Highest illustrative risk score: **{score:.1f}/100**
""" + "\n".join(f"- {k}: {v['score']:.1f}/100 — {v['driver']}" for k, v in risk.items()) + f"""

## Highest-ranked sample rotation

- **{rotations.iloc[0]['rotation']}** — illustrative weighted score {rotations.iloc[0]['demo_score']:.1f}/100

## Limitations

All source values and site markers in this demo are synthetic fixtures. Real AgriSim deployment requires dated, quality-controlled environmental observations, verified field boundaries, crop histories, and validation of decision rules. The app intentionally makes no yield or success-probability claims.
"""
