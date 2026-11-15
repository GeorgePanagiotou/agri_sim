"""Run with: pytest -q tests/test_recommendation_log.py"""
from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import json
import sys

import pandas as pd
import pytest

MODULE = Path(__file__).resolve().parents[1] / "src" / "agrisim" / "decision_engine" / "recommendation_log.py"
spec = importlib.util.spec_from_file_location("recommendation_log", MODULE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

BOUNDARY = {
    "type": "Polygon", "coordinates": [
        [[23.12, 38.90], [23.13, 38.90], [23.13, 38.91], [23.12, 38.90]]
    ],
}
CURRENT = datetime(2026, 11, 15, 14, 10, tzinfo=timezone.utc)


def assessment(week="2026-11-15"):
    return pd.Series({
        "field_profile_id": "my_field", "crop_id": "winter_wheat",
        "season": "2026-2027", "week_start": week,
        "decision_priority": "insufficient_evidence",
        "recommended_action": "Observe seedbed before deciding.",
        "sowing_verdict": "unknown", "risk_evidence_status": "unavailable",
        "probability_of_establishment": float("nan"),
        "risk_reference_temporal_status": "reference_ends_before_assessment_year",
        "component_b_sowing_status": "regional_heuristic_v1",
        "greenup_current_clear_dates": 0,
    })


def weeks():
    return pd.DataFrame([
        {"crop_id": "winter_wheat", "season": "2026-2027", "week_start": "2026-11-08", "sowing_verdict": "check_worthy", "decision_priority": "candidate_for_field_check"},
        {"crop_id": "winter_wheat", "season": "2026-2027", "week_start": "2026-11-15", "sowing_verdict": "unknown", "decision_priority": "insufficient_evidence"},
        {"crop_id": "winter_wheat", "season": "2026-2027", "week_start": "2026-11-22", "sowing_verdict": "unknown", "decision_priority": "insufficient_evidence"},
    ])


def build(**kwargs):
    return mod.build_recommendation_snapshot(
        assessment(), field_id="my_field", boundary=json.dumps(BOUNDARY),
        candidate_weeks=weeks(), issued_at=CURRENT, **kwargs,
    )


def test_explicit_timestamp_and_alternatives_as_unranked_context():
    snap = build()
    assert snap["issued_at_utc"] == "2026-11-15T14:10:00.000000+00:00"
    assert snap["issue_local_date"] == "2026-11-15"
    assert snap["field_id"] == "my_field"
    assert snap["boundary_version"].startswith("sha256:")
    assert [w["candidate_week"] for w in snap["historical_regional_week_context"]] == ["2026-11-08", "2026-11-15"]
    assert all(w["comparable_score"] is None for w in snap["historical_regional_week_context"])
    assert sum(w["is_selected_current_week"] for w in snap["historical_regional_week_context"]) == 1
    assert snap["eligible_alternatives"] is None
    assert snap["model_versions"] is None
    assert snap["component_statuses"]["component_b_sowing_status"] == "regional_heuristic_v1"
    assert snap["field_assessment_snapshot"]["probability_of_establishment"] is None
    assert snap["evidence_timestamps"]["regional_forecast_issue_time"] is None
    json.dumps(snap, allow_nan=False)


def test_no_backdating_historical_or_pretending_forecast():
    for week in ("2026-11-08", "2026-11-22"):
        with pytest.raises(ValueError, match="current local crop-week"):
            mod.build_recommendation_snapshot(
                assessment(week), field_id="my_field", boundary=BOUNDARY,
                candidate_weeks=weeks(), issued_at=CURRENT,
            )


def test_require_matching_field_and_saved_boundary():
    with pytest.raises(ValueError, match="does not match"):
        mod.build_recommendation_snapshot(
            assessment(), field_id="wrong_field", boundary=BOUNDARY,
            candidate_weeks=weeks(), issued_at=CURRENT,
        )
    with pytest.raises(ValueError, match="saved field boundary"):
        mod.build_recommendation_snapshot(
            assessment(), field_id="my_field", boundary="",
            candidate_weeks=weeks(), issued_at=CURRENT,
        )


def test_missing_farm_id_is_not_string_nan():
    assert build(farm_id=float("nan"))["farm_id"] is None


def test_boundary_version_is_not_whitespace_sensitive():
    a = build()
    b = mod.build_recommendation_snapshot(
        assessment(), field_id="my_field", boundary=BOUNDARY,
        candidate_weeks=weeks(), issued_at=CURRENT,
    )
    assert a["boundary_version"] == b["boundary_version"]
    assert a["recommendation_id"] != b["recommendation_id"]


def test_requires_timezone_aware_issue_time():
    with pytest.raises(ValueError, match="timezone aware"):
        mod.build_recommendation_snapshot(
            assessment(), field_id="my_field", boundary=BOUNDARY,
            candidate_weeks=weeks(), issued_at=datetime(2026, 11, 15, 16, 10),
        )


@pytest.mark.skipif(importlib.util.find_spec("pyarrow") is None, reason="pyarrow not installed")
def test_parquet_append_only_roundtrip(tmp_path):
    path = tmp_path / "issued_recommendations.parquet"
    first = build()
    part = mod.append_recommendation(first, path)
    assert part.is_file()
    out = pd.read_parquet(path)
    assert len(out) == 1
    saved = json.loads(out.iloc[0]["snapshot_json"])
    assert saved["recommendation_id"] == first["recommendation_id"]
    assert out.iloc[0]["snapshot_sha256"] == mod._digest(out.iloc[0]["snapshot_json"])
    with pytest.raises(FileExistsError):
        mod.append_recommendation(first, path)
    second = build()
    mod.append_recommendation(second, path)
    assert len(pd.read_parquet(path)) == 2


def test_snapshot_freezes_rotation_ranking_and_field_preferences():
    rank = pd.DataFrame([{"strategy_id": "B", "priority_rank": 1,
                          "relative_priority_score": 4.5, "market": None}])
    snap = mod.build_recommendation_snapshot(
        assessment(), field_id="my_field", boundary=BOUNDARY,
        candidate_weeks=weeks(), issued_at=CURRENT,
        ranking=rank,
        field_profile={"prior:2026-2027:0": "barley", "B_market": "5",
                       "boundary": json.dumps(BOUNDARY)},
    )
    assert snap["rotation_preference_ranking"][0]["relative_priority_score"] == 4.5
    assert snap["field_history_at_issue"]["crop_1_back"] == "barley"
    assert snap["preference_scores_at_issue"]["B_market"] == "5"
    assert snap["preference_ranking_is_predicted_benefit"] is False
    assert "boundary" not in snap["preference_scores_at_issue"]
