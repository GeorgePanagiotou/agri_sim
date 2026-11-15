"""Run from project root: uv run python -m pytest -q tests/test_outcome_store.py"""
from datetime import date
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

MODULE = Path(__file__).resolve().parents[1] / "src/agrisim/decision_engine/outcome_store.py"
spec = importlib.util.spec_from_file_location("outcome_store", MODULE)
store = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = store
spec.loader.exec_module(store)

TODAY = date(2026, 11, 15)


def issued(rec_id="12345678-1234-1234-1234-123456789012"):
    return {
        "schema_version": "issued_recommendation_v1", "recommendation_id": rec_id,
        "issued_at_utc": "2026-11-15T12:00:00+00:00", "field_id": "3", "farm_id": None,
        "boundary_version": "sha256:abc", "boundary_geometry": {"type": "Polygon", "coordinates": []},
        "selection": {"crop_id": "winter_wheat", "candidate_week": "2026-11-15"},
        "field_assessment_snapshot": {"crop_id": "winter_wheat", "season": "2026-2027",
                                      "week_start": "2026-11-15", "recommended_action": "Inspect field"},
        "rotation_preference_ranking": [{"strategy_id": "B", "relative_priority_score": 4.5}],
        "field_history_at_issue": {"crop_1_back": "barley"},
        "preference_scores_at_issue": {"B_market": 5},
    }


def save(db):
    ident, created = store.record_issued_snapshot(db, issued())
    assert created
    return ident


def update(db, ident, **overrides):
    args = dict(database=db, record_id=ident, field_id=3, revision=0,
                actual_crop=None, planting_status="Not yet known", planted=None,
                emerged=None, emergence_end=None, establishment="Not assessed",
                observation_date=None, evidence_source="Not provided", stress=None,
                today=TODAY)
    args.update(overrides)
    return store.update_observation(**args)


def test_preserves_legacy_records_in_migration(tmp_path):
    db = tmp_path / "field_profiles.sqlite3"
    with sqlite3.connect(db) as con:
        con.execute("""CREATE TABLE field_outcomes(id INTEGER PRIMARY KEY,
                field_id INTEGER NOT NULL, digest TEXT NOT NULL,
                snapshot TEXT NOT NULL, saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                crop TEXT, planted TEXT, emerged TEXT, establishment TEXT,
                stress TEXT, revision INTEGER NOT NULL DEFAULT 0, UNIQUE(field_id,digest))""")
        con.execute("INSERT INTO field_outcomes(field_id,digest,snapshot, crop,planted,emerged,establishment) VALUES(?,?,?,?,?,?,?)",
                    (3, "old", json.dumps({"assessment": {"crop_id": "barley", "week_start": "2025-10-01"}, "ranking": []}),
                     "barley", "2025-10-03", "2025-10-09", "Established"))
    store.ensure_schema(db)
    store.ensure_schema(db)
    r = store.records_for_field(db, 3)[0]
    assert r["id"] == 1 and r["recommendation_id"] is None
    assert r["planted"] == "2025-10-03" and r["establishment"] == "Established"
    out = store.as_export_records(db)[0]
    assert out["record_type"] == "legacy_unverified"
    assert out["planting_status"] == "Planted"
    assert out["established_successfully"] is None  # Legacy label lacks dated/evidenced provenance


def test_issue_idempotency_and_frozen_preferences(tmp_path):
    db = tmp_path / "farm.sqlite3"
    number = save(db)
    assert store.record_issued_snapshot(db, issued()) == (number, False)
    row = store.records_for_field(db, 3)[0]
    frozen = json.loads(row["snapshot"])
    assert row["recommendation_id"] == issued()["recommendation_id"]
    assert frozen["field_history"] == {"crop_1_back": "barley"}
    assert frozen["ranking"][0]["relative_priority_score"] == 4.5
    assert frozen["boundary_version"] == "sha256:abc"


def test_no_planting_is_not_failure(tmp_path):
    db = tmp_path / "farm.sqlite3"
    number = save(db)
    assert update(db, number, planting_status="Not planted",
                  observation_date="2026-11-15", evidence_source="Field visit")
    output = store.as_export_records(db)[0]
    assert output["planting_status"] == "Not planted"
    assert output["established_successfully"] is None
    assert output["actual_sowing_date"] is None
    assert output["recommendation_id"] == issued()["recommendation_id"]
    assert output["observation_date"] == "2026-11-15"
    target = tmp_path / "field_outcomes.csv"
    store.export_outcomes_csv(db, target)
    data = target.read_text(encoding="utf-8")
    assert "recommendation_id" in data and "Not planted" in data


def test_establishment_positive_and_days_to_emergence(tmp_path):
    db = tmp_path / "farm.sqlite3"
    number = save(db)
    assert update(db, number, planting_status="Planted", actual_crop="winter_wheat",
                  planted="2026-11-08", emerged="2026-11-13",
                  establishment="Established", observation_date="2026-11-15",
                  evidence_source="Farmer report")
    outcome = store.as_export_records(db)[0]
    assert outcome["established_successfully"] == 1
    assert outcome["days_to_emergence"] == 5
    assert outcome["days_to_emergence_min"] == 5
    assert outcome["days_to_emergence_max"] == 5
    assert update(db, number, planting_status="Planted", planted="2026-11-08",
                  establishment="Failed to establish", observation_date="2026-11-15",
                  evidence_source="Field visit", revision=1)
    assert store.as_export_records(db)[0]["established_successfully"] == 0


def test_emergence_interval_and_partial_are_not_exact_or_binary(tmp_path):
    db = tmp_path / "farm.sqlite3"
    number = save(db)
    assert update(db, number, planting_status="Planted", planted="2026-11-07",
                  emerged="2026-11-11", emergence_end="2026-11-14",
                  establishment="Partially established", observation_date="2026-11-15",
                  evidence_source="Field visit")
    result = store.as_export_records(db)[0]
    assert result["established_successfully"] is None
    assert result["days_to_emergence"] is None
    assert result["days_to_emergence_min"] == 4
    assert result["days_to_emergence_max"] == 7


def test_rejects_unsupported_outcome_inference(tmp_path):
    db = tmp_path / "farm.sqlite3"
    number = save(db)
    with pytest.raises(ValueError, match="cannot have sowing"):
        update(db, number, planting_status="Not planted", planted="2026-11-10")
    with pytest.raises(ValueError, match="[Ee]mergence"):
        update(db, number, planting_status="Planted", planted="2026-11-12",
               emerged="2026-11-10", observation_date="2026-11-15", evidence_source="Field visit")
    with pytest.raises(ValueError, match="observation date"):
        update(db, number, planting_status="Not planted", evidence_source="Field visit")
    with pytest.raises(ValueError, match="evidence source"):
        update(db, number, planting_status="Not planted", observation_date="2026-11-15")
    with pytest.raises(ValueError, match="future"):
        update(db, number, planting_status="Planted", planted="2026-11-16")


def test_optimistic_concurrency_preserved(tmp_path):
    db = tmp_path / "farm.sqlite3"
    number = save(db)
    assert update(db, number, planting_status="Planted", planted="2026-11-10")
    assert not update(db, number, planting_status="Planted", planted="2026-11-11")
    assert store.as_export_records(db)[0]["actual_sowing_date"] == "2026-11-10"


def test_legacy_reviews_are_not_issued(tmp_path):
    db = tmp_path / "farm.sqlite3"
    a, created = store.save_legacy_review(db, 3, {"week_start": "2025-09-10", "crop_id": "wheat"}, None, [])
    assert created
    assert store.save_legacy_review(db, 3, {"week_start": "2025-09-10", "crop_id": "wheat"}, None, []) == (a, False)
    assert store.as_export_records(db)[0]["recommendation_id"] is None


def test_relink_no_directory_safe(tmp_path):
    assert store.sync_from_parquet(tmp_path / "farm.sqlite3", tmp_path / "missing.parquet") == 0


def test_existing_unmanaged_csv_is_never_overwritten(tmp_path):
    db = tmp_path / "farm.sqlite3"
    save(db)
    target = tmp_path / "field_outcomes.csv"
    target.write_text("my farm data\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not managed"):
        store.export_outcomes_csv(db, target)
    assert target.read_text(encoding="utf-8") == "my farm data\n"


def test_external_edits_to_generated_csv_are_preserved(tmp_path):
    db = tmp_path / "farm.sqlite3"
    save(db)
    target = tmp_path / "field_outcomes.csv"
    store.export_outcomes_csv(db, target)
    store.export_outcomes_csv(db, target)  # unchanged generated file can be regenerated
    target.write_text(target.read_text(encoding="utf-8") + "manual row\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed outside"):
        store.export_outcomes_csv(db, target)
    assert "manual row" in target.read_text(encoding="utf-8")
