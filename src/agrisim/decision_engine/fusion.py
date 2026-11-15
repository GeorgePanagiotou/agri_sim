"""Fuse regional sowing and risk screens with point-in-time pilot vegetation history.

The older crop/week cross-join fusion interface is superseded by this contract.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from agrisim.decision_engine.vegetation_history import apply_greenup

HAZARDS = ("drought", "dry_spell", "heat", "frost", "heavy_rain")
VERDICTS = {"unknown", "too_cold", "too_dry", "too_wet", "check_worthy"}
RISK_FIELDS = (
    "overall_level", "overall_label", "hazards_flagged", "hazards_unknown",
    "rain_source", "rain_support", "confidence_note", "risk_method",
    "field_id", "spatial_support",
    *(f"{h}_level" for h in HAZARDS),
    *(f"{h}_label" for h in HAZARDS),
    *(f"explain_{h}" for h in HAZARDS),
)


def _dates(series: pd.Series, name: str) -> pd.Series:
    result = pd.to_datetime(series, errors="raise", utc=True).dt.tz_localize(None)
    if result.isna().any() or not (result == result.dt.normalize()).all():
        raise ValueError(f"{name} must contain complete calendar dates (no times)")
    return result


def _required(frame: pd.DataFrame, names: set[str], source: str) -> None:
    missing = names.difference(frame.columns)
    if missing:
        raise ValueError(f"{source} missing columns: {sorted(missing)}")


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _priority(row: pd.Series) -> tuple[str, str]:
    """Prefer an observed unsafe sowing screen over inferred safety.

    Missing risk evidence must not be interpreted as low risk. A 'check_worthy'
    verdict is a recommendation to INSPECT the seedbed, never to sow.
    """
    verdict = row["sowing_verdict"]
    level = row["risk_overall_level"]
    risk_status = row["risk_evidence_status"]
    if verdict == "unknown":
        return ("insufficient_evidence",
                "Missing sowing evidence. Inspect the field and obtain the necessary observations before deciding.")
    if verdict == "too_wet":
        return ("field_check_required",
                "Regional heavy-rain warning: check drainage and field access before considering sowing.")
    if verdict == "too_cold":
        return ("field_check_required",
                "Regional temperature is below the crop-screening rule: check the seedbed and crop-specific guidance.")
    if verdict == "too_dry":
        return ("field_check_required",
                "Regional moisture or recent rainfall is inadequate by the screening rule: check seedbed moisture.")
    if risk_status == "unavailable":
        return ("insufficient_evidence",
                "Sowing screen is check-worthy, but regional risk evidence is missing. Obtain hazard data and inspect the field.")
    if pd.notna(level) and float(level) >= 2:
        return ("regional_risk_warning",
                "At least one regional hazard is at warning or severe level. Review the hazard before a field check.")
    if risk_status == "partial":
        return ("field_check_with_data_gaps",
                "Candidate week may deserve a field check, but some regional hazards are unknown. Do not treat missing hazards as safe.")
    return ("candidate_for_field_check",
            "Regional screening found no blocking rule. Walk the field and verify the seedbed; this is not a sow-now instruction.")


def fuse(sowing: pd.DataFrame, risk: pd.DataFrame, *, area_id: str = "evia",
         season: str | None = None, crop_id: str | None = None,
         as_of: str | pd.Timestamp | None = None, vegetation: pd.DataFrame | None = None) -> pd.DataFrame:
    """Fuse real B/D tables into one auditable, per-crop-week regional assessment.

    Parameters
    ----------
    sowing : output of decision_engine.sowing_window (or its sowing_weeks.csv).
    risk : output of decision_engine.environmental_risk (or risk_daily.csv).
    area_id : geographic origin; both source tables MUST refer to the same area.
        The current upstream risk loader builds regional data for the active
        AGRISIM_AREA. This function deliberately does not guess area from points.
    as_of : only candidate weeks already reached as of this date are returned.

    No future-weather forecast, farm measurement, crop-yield model or crop rotation
    is silently manufactured. Missing risk rows are kept and explicitly flagged.
    """
    if not area_id or not str(area_id).strip():
        raise ValueError("area_id is required")
    _required(sowing, {"crop_id", "season", "week_start", "verdict", "verdict_long_record", "explanation"}, "sowing")
    _required(risk, {"date", "overall_level", "overall_label", "hazards_unknown", "field_id", "spatial_support"}, "risk")

    sw = sowing.copy()
    sw["week_start"] = _dates(sw["week_start"], "sowing.week_start")
    if not sw["verdict"].isin(VERDICTS).all():
        raise ValueError("Unexpected sowing verdict(s)")
    if sw.duplicated(["crop_id", "season", "week_start"]).any():
        raise ValueError("Duplicate crop/season/week sowing records")
    if season is not None:
        sw = sw.loc[sw["season"].eq(season)].copy()
    if crop_id is not None:
        sw = sw.loc[sw["crop_id"].eq(crop_id)].copy()
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is not None:
            cutoff = cutoff.tz_convert("UTC").tz_localize(None)
        cutoff = cutoff.normalize()
        sw = sw.loc[sw["week_start"].le(cutoff)].copy()
    if sw.empty:
        raise ValueError("No sowing candidates match season, crop and as-of date")

    r = risk.copy()
    if not r.empty:
        if r["field_id"].isna().any():
            raise ValueError("Risk rows lack a regional source site identifier")
        sites = set(r["field_id"].astype(str))
        if not all(site == f"{area_id}_pilot" for site in sites):
            raise ValueError(f"Risk source belongs to unexpected site(s): {sorted(sites)}; requested area={area_id}")
        if not r["spatial_support"].eq("regional_context_not_field_measurement").all():
            raise ValueError("Risk source is not the expected regional, non-field measurement product")
    r["date"] = _dates(r["date"], "risk.date")
    if r["date"].duplicated().any():
        raise ValueError("Risk table must have one record per date for the configured area")
    # Do not merge risk.field_id with provisional crop/field IDs: this dataset is
    # area-scale, not an observed farm parcel. Explicitly retain provenance.
    have = [field for field in RISK_FIELDS if field in r]
    r = r[["date", *have]].rename(columns={field: f"risk_{field}" for field in have})
    r["risk_row_available"] = True
    out = sw.merge(r, how="left", left_on="week_start", right_on="date", validate="many_to_one")
    if len(out) != len(sw):
        raise AssertionError("Risk join changed the number of crop-week candidates")

    out = out.rename(columns={"verdict": "sowing_verdict",
                              "verdict_long_record": "sowing_verdict_long_record",
                              "explanation": "sowing_explanation"})
    out["risk_row_available"] = out["risk_row_available"].eq(True)
    for name in ("risk_hazards_unknown", "risk_hazards_flagged", "risk_confidence_note", "risk_overall_label"):
        if name not in out:
            out[name] = pd.NA
    out["risk_overall_level"] = pd.to_numeric(out["risk_overall_level"], errors="coerce")

    def status(row: pd.Series) -> str:
        if not row["risk_row_available"]:
            return "unavailable"
        unknown = _text(row["risk_hazards_unknown"])
        if unknown or pd.isna(row["risk_overall_level"]):
            return "partial"
        return "complete"

    out["risk_evidence_status"] = out.apply(status, axis=1)
    out["area_id"] = str(area_id)
    out["assessment_date"] = out["week_start"]  # evidence known at START of this date
    out["spatial_support"] = "regional_weather_context_not_verified_parcel"
    out["farm_polygon_verified"] = False
    out["component_a_vegetation_status"] = "not_integrated"
    out["component_b_sowing_status"] = "regional_heuristic_v1"
    out["component_c_rotation_status"] = "not_integrated"
    out["component_d_risk_status"] = "regional_heuristic_v1"
    out["component_e_fusion_status"] = "partial_B_D_only"
    out["risk_reference_temporal_status"] = np.where(
        ~out["risk_row_available"], "not_evaluated_missing_risk",
        np.where(out["week_start"].dt.year <= 2020,
                 "retrospective_climatology_1991_2020_or_2001_2020_not_available_at_historical_date",
                 "reference_ends_before_assessment_year"),
    )
    decisions = out.apply(_priority, axis=1)
    out["decision_priority"] = decisions.map(lambda pair: pair[0])
    out["recommended_action"] = decisions.map(lambda pair: pair[1])

    def explanation(row: pd.Series) -> str:
        parts = [str(row["sowing_explanation"])]
        if row["risk_evidence_status"] == "unavailable":
            parts.append("No matching risk row on the candidate week's start date; no safe-risk assumption made.")
        else:
            parts.append(f"Regional risk: {_text(row['risk_overall_label']) or 'unknown'}"
                         f"; flagged: {_text(row['risk_hazards_flagged']) or 'none documented'}"
                         f"; unknown: {_text(row['risk_hazards_unknown']) or 'none documented'}.")
            if _text(row["risk_confidence_note"]):
                parts.append("Provenance: " + _text(row["risk_confidence_note"]))
        if row["risk_reference_temporal_status"].startswith("retrospective"):
            parts.append("Risk climate reference includes future years relative to this historical week: retrospective only.")
        parts.append("Regional heuristic; independent crop establishment/yield outcomes are unavailable.")
        return " ".join(parts)

    out["decision_explanation"] = out.apply(explanation, axis=1)
    if vegetation is not None:
        if area_id != "evia":
            raise ValueError("Pilot vegetation history requires the Evia area")
        out = apply_greenup(out, vegetation)
    out["is_forecast"] = False
    out["probability_of_establishment"] = np.nan
    out["crop_rotation_recommendation"] = pd.NA
    out["target_architecture"] = "A:vegetation B:sowing C:rotation D:risk E:fusion"
    return out.drop(columns=["date"], errors="ignore").sort_values(["week_start", "crop_id"]).reset_index(drop=True)


def summarize_fusion(table: pd.DataFrame) -> dict:
    """Machine-readable manifest without pretending the partial A-E engine is complete."""
    vegetation = "greenup_current_status" in table
    return {
        "architecture": "A-vegetation, B-sowing, C-rotation, D-risk, E-fusion",
        "implemented_in_this_output": (["A_vegetation"] if vegetation else []) + (["C_rotation_phases"] if "rotation_options" in table else []) + ["B_sowing", "D_regional_risk", "E_partial_fusion"],
        "pending_integration": ([] if vegetation else ["A_vegetation"]) + ([] if "rotation_options" in table else ["C_crop_rotation"]) + ["E_complete_decision_fusion"],
        "vegetation_status_counts": table.component_a_vegetation_status.value_counts().to_dict(),
        "rows": int(len(table)),
        "areas": sorted(table.area_id.unique().tolist()),
        "seasons": sorted(table.season.unique().tolist()),
        "decision_priority_counts": {str(k): int(v) for k, v in table.decision_priority.value_counts().items()},
        "missing_risk_rows": int((~table.risk_row_available).sum()),
        "partially_known_risk_rows": int(table.risk_evidence_status.eq("partial").sum()),
        "historically_retrospective_risk_rows": int(table.risk_reference_temporal_status.str.startswith("retrospective").sum()),
        "disclaimer": "Regional evidence screening and field-check actions only; no sow-now command, forecast, or verified farm probability.",
    }
