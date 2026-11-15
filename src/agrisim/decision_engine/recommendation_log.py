"""Append-only, field-specific snapshots of *issued* Evia field-check guidance.

The output ``data/local/issued_recommendations.parquet`` is a Parquet DATASET
(directory of immutable Parquet part files), not a single mutable Parquet file.
Read it with ``pd.read_parquet(path)`` when the optional pyarrow engine is present.

Do not use this module to backfill historical assessments as if they were
recommendations issued on the original assessment date. Issuance is an explicit
user action and always records the actual UTC issue timestamp.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

LOCAL_ZONE = ZoneInfo("Europe/Athens")
LOG_SCHEMA_VERSION = "issued_recommendation_v1"


def _jsonable(value: Any) -> Any:
    """Normalize pandas/numpy values while retaining all known evidence fields."""
    if isinstance(value, pd.Series):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, (int, float, bool, str)) or value is None:
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value
    if value is pd.NA or value is pd.NaT:
        return None
    # pandas' NA check must be applied only to scalars.
    if bool(pd.isna(value)):
        return None
    raise TypeError(f"Unsupported snapshot field type: {type(value).__name__}")


def _canonical_json(obj: Any) -> str:
    return json.dumps(_jsonable(obj), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _boundary_version(boundary: str | dict) -> str:
    """Content-addressed boundary version; the same shape gets the same version."""
    try:
        parsed = json.loads(boundary) if isinstance(boundary, str) else boundary
        if not isinstance(parsed, dict) or parsed.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("Expected saved Polygon/MultiPolygon geometry")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid saved boundary GeoJSON") from exc
    return "sha256:" + _digest(_canonical_json(parsed))


def _week_date(value: Any):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("Candidate week is missing")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(LOCAL_ZONE).tz_localize(None)
    if stamp != stamp.normalize():
        raise ValueError("week_start must be a calendar date")
    return stamp.date()


def build_recommendation_snapshot(
    assessment: pd.Series,
    *,
    field_id: str,
    boundary: str | dict,
    candidate_weeks: pd.DataFrame,
    farm_id: str | None = None,
    issued_at: datetime | None = None,
    ranking: pd.DataFrame | None = None,
    field_profile: dict[str, Any] | None = None,
    alternatives: list[dict[str, Any]] | None = None,
    model_versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture the selected field assessment and all visible SAME-CROP weeks.

    Only the currently active local candidate week may be *issued*: previously
    calculated weeks are historical reviews, and later weeks are not forecasts.
    The alternatives are visible unranked regional screens, NOT validated
    field-specific or measured counterfactuals.
    """
    if not str(field_id).strip():
        raise ValueError("field_id is required")
    if boundary is None or boundary == "":
        raise ValueError("A saved field boundary is required before issuance")
    for key in ("crop_id", "season", "week_start", "decision_priority", "recommended_action"):
        if key not in assessment or pd.isna(assessment[key]):
            raise ValueError(f"Assessment is missing {key}")
    now = issued_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("issued_at must be timezone aware")
    now_utc = now.astimezone(timezone.utc)
    start = _week_date(assessment["week_start"])
    local_today = now.astimezone(LOCAL_ZONE).date()
    if not (start <= local_today < start + timedelta(days=7)):
        raise ValueError("Only the current local crop-week can be issued. Historical assessments cannot be backdated, and future weeks are not forecasts.")

    if "field_profile_id" in assessment and not pd.isna(assessment["field_profile_id"]):
        if str(assessment["field_profile_id"]) != str(field_id):
            raise ValueError("The assessed field does not match field_id")
    required = {"crop_id", "season", "week_start", "sowing_verdict", "decision_priority"}
    if required.difference(candidate_weeks.columns):
        raise ValueError("candidate_weeks is missing required columns")

    # These are only comparison context, not independently field-evaluated options.
    matches = candidate_weeks.loc[
        candidate_weeks["crop_id"].eq(assessment["crop_id"])
        & candidate_weeks["season"].eq(assessment["season"])
    ].copy()
    matches["week_start"] = pd.to_datetime(matches["week_start"], errors="raise")
    matches = matches[matches["week_start"].dt.date <= local_today]
    matches = matches.sort_values("week_start")
    if matches.duplicated("week_start").any():
        raise ValueError("Duplicate week alternatives for the selected crop/season")
    historical_alternatives = []
    for _, item in matches.iterrows():
        historical_alternatives.append({
            "crop_id": str(item["crop_id"]),
            "candidate_week": _week_date(item["week_start"]).isoformat(),
            "sowing_verdict": _jsonable(item["sowing_verdict"]),
            "decision_priority": _jsonable(item["decision_priority"]),
            "risk_evidence_status": _jsonable(item.get("risk_evidence_status")),
            "risk_overall_level": _jsonable(item.get("risk_overall_level")),
            "field_specific": False,
            "is_selected_current_week": _week_date(item["week_start"]) == start,
            "comparable_score": None,
        })

    row = _jsonable(assessment)
    selection = {
        "crop_id": str(assessment["crop_id"]),
        "season": str(assessment["season"]),
        "candidate_week": start.isoformat(),
        "decision_priority": str(assessment["decision_priority"]),
        "recommended_action": str(assessment["recommended_action"]),
        "rotation_options_unverified": row.get("rotation_options"),
        "predicted_establishment_probability": row.get("probability_of_establishment"),
    }
    version = _boundary_version(boundary)
    normalized_farm_id = _jsonable(farm_id)
    if normalized_farm_id is not None:
        normalized_farm_id = str(normalized_farm_id).strip() or None
    # Capture user-entered decision preferences at the moment of issuance.
    # These are subjective preference scores, NOT measured rotation benefits.
    profile = field_profile or {}
    history = {f"crop_{i + 1}_back": _jsonable(profile.get(f"prior:{assessment['season']}:{i}"))
               for i in range(3)}
    scores = {str(key): _jsonable(value) for key, value in profile.items()
              if key.startswith(("A_", "B_", "C_", "D_"))}
    ranked_rows = _jsonable(ranking.to_dict(orient="records")) if ranking is not None else []
    snapshot = {
        "schema_version": LOG_SCHEMA_VERSION,
        "recommendation_id": str(uuid4()),
        "issued_at_utc": now_utc.isoformat(timespec="microseconds"),
        "issue_local_date": local_today.isoformat(),
        "record_type": "issued_field_check_guidance_not_sowing_instruction",
        "farm_id": normalized_farm_id,
        "field_id": str(field_id),
        "boundary_version": version,
        "boundary_geometry": json.loads(boundary) if isinstance(boundary, str) else boundary,
        "selection": selection,
        "historical_regional_week_context": historical_alternatives,
        "eligible_alternatives": _jsonable(alternatives) if alternatives is not None else None,
        "alternatives_status": ("conditional_current_week_rotation_choices_not_joint_forecast_optimization"
                                if alternatives is not None else "not_evaluated_field_crop_week_rotation_alternatives"),
        "decision_scores": None,
        "decision_uncertainty": (
            {"type": "not_calibrated_regional_rules", "risk_evidence_status": row.get("risk_evidence_status"),
             "unscored_alternatives": sum(a.get("comparable_score") is None for a in alternatives),
             "missing_forecast_evidence": True,
             "establishment_probability_not_validated": True}
            if alternatives is not None else None),
        "component_statuses": {key: value for key, value in row.items() if key.startswith("component_") and key.endswith("_status")},
        "model_versions": _jsonable(model_versions) if model_versions is not None else None,
        "evidence_timestamps": {
            "assessment_date": row.get("assessment_date"),
            "vegetation_latest_available_utc": row.get("vegetation_latest_available_utc"),
            "regional_forecast_issue_time": None,
        },
        "evidence_limitations": {
            "historical_regional_climatology": row.get("risk_reference_temporal_status"),
            "risk_spatial_support": row.get("risk_spatial_support"),
            "regional_weather_not_field_measurement": True,
            "regional_forecast_issuance_archive_available": False,
        },
        "field_assessment_snapshot": row,
        "field_history_at_issue": history,
        "preference_scores_at_issue": scores,
        "rotation_preference_ranking": ranked_rows,
        "preference_ranking_is_predicted_benefit": False,
    }
    return snapshot


def append_recommendation(snapshot: dict[str, Any], path: Path) -> Path:
    """Write one immutable Parquet part. Never overwrite an issued snapshot.

    ``path`` denotes the Parquet dataset directory. A staging file is kept in
    a sibling directory to avoid exposing partial writes to dataset readers.
    Requires pyarrow (``uv add pyarrow`` in the project environment).
    """
    if snapshot.get("schema_version") != LOG_SCHEMA_VERSION:
        raise ValueError("Unsupported snapshot schema version")
    record_id = snapshot.get("recommendation_id")
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("recommendation_id is missing")
    path = Path(path)
    payload = _canonical_json(snapshot)
    row = {
        "recommendation_id": record_id,
        "issued_at_utc": snapshot["issued_at_utc"],
        "farm_id": snapshot.get("farm_id") or "",
        "field_id": snapshot["field_id"],
        "boundary_version": snapshot["boundary_version"],
        "crop_id": snapshot["selection"]["crop_id"],
        "season": snapshot["selection"]["season"],
        "candidate_week": snapshot["selection"]["candidate_week"],
        "decision_priority": snapshot["selection"]["decision_priority"],
        "record_type": snapshot["record_type"],
        "snapshot_sha256": _digest(payload),
        "snapshot_json": payload,
    }
    frame = pd.DataFrame({key: pd.Series([str(value)], dtype="string") for key, value in row.items()})
    # Explicitly verify dependency before touching disk.
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Parquet logging requires pyarrow. Install with: uv add pyarrow") from exc

    path.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(path.name + ".staging")
    stage.mkdir(parents=True, exist_ok=True)
    destination = path / f"part-{record_id}.parquet"
    temporary = stage / f".{record_id}.{uuid4().hex}.parquet"
    if destination.exists():
        raise FileExistsError(f"Recommendation was already stored: {record_id}")
    try:
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        # Link creation fails if another writer unexpectedly generated same ID.
        # The hard link is atomic and Windows-compatible on a local NTFS volume.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def issue_recommendation(
    assessment: pd.Series, *, field_id: str, boundary: str | dict,
    candidate_weeks: pd.DataFrame, path: Path, farm_id: str | None = None,
    issued_at: datetime | None = None,
    ranking: pd.DataFrame | None = None,
    field_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and persist an explicitly issued field-check recommendation."""
    snapshot = build_recommendation_snapshot(
        assessment, field_id=field_id, boundary=boundary,
        candidate_weeks=candidate_weeks, farm_id=farm_id, issued_at=issued_at,
        ranking=ranking, field_profile=field_profile,
    )
    append_recommendation(snapshot, path)
    return snapshot
