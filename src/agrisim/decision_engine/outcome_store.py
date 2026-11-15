"""SQLite outcome records linked to immutable issued recommendation snapshots.

Existing ``field_outcomes`` rows are preserved as unverified/legacy reviews.
Only rows carrying a real ``recommendation_id`` from an issued Parquet
snapshot are treated as linked *issued* recommendations.
"""
from __future__ import annotations

import csv
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

ESTABLISHMENT = ("Not assessed", "Established", "Partially established", "Failed to establish")
PLANTING = ("Not yet known", "Planted", "Not planted")
EVIDENCE = ("Not provided", "Farmer report", "Field visit", "Photograph", "Sensor", "Other")
ATHENS = ZoneInfo("Europe/Athens")

# Additive migration: NEVER destroy or rename legacy field_outcomes rows.
ADDED_COLUMNS = {
    "recommendation_id": "TEXT",
    "planting_status": "TEXT NOT NULL DEFAULT 'Not yet known'",
    "emergence_end": "TEXT",
    "observation_date": "TEXT",
    "evidence_source": "TEXT",
    "observation_updated_at": "TEXT",
}
EXPORT_FIELDS = [
    "record_id", "record_type", "recommendation_id", "issued_at_utc", "farm_id",
    "field_id", "boundary_version", "season", "recommended_crop", "candidate_week",
    "observed_crop", "planting_status", "actual_sowing_date", "emergence_date_or_start",
    "emergence_interval_end", "establishment_result", "established_successfully",
    "observation_date", "evidence_source", "days_to_emergence",
    "days_to_emergence_min", "days_to_emergence_max", "stress_notes",
    "revision", "saved_at_utc", "observation_updated_at_utc",
]


def ensure_schema(database: Path) -> None:
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS field_outcomes (
            id INTEGER PRIMARY KEY, field_id INTEGER NOT NULL, digest TEXT NOT NULL,
            snapshot TEXT NOT NULL, saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            crop TEXT, planted TEXT, emerged TEXT, establishment TEXT, stress TEXT,
            revision INTEGER NOT NULL DEFAULT 0, UNIQUE(field_id,digest))""")
        old_columns = {row[1] for row in db.execute("PRAGMA table_info(field_outcomes)")}
        for column, definition in ADDED_COLUMNS.items():
            if column not in old_columns:
                db.execute(f"ALTER TABLE field_outcomes ADD COLUMN {column} {definition}")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_outcomes_issued_id
                      ON field_outcomes(recommendation_id)
                      WHERE recommendation_id IS NOT NULL""")


def _serialized(obj: dict) -> tuple[str, str]:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_issued_snapshot(database: Path, issued: dict) -> tuple[int, bool]:
    """Idempotently link a *previously written* issued Parquet snapshot to SQLite.

    A stale/legacy record is never retroactively promoted to 'issued'.
    """
    ident = issued.get("recommendation_id")
    selection = issued.get("selection", {})
    if (issued.get("schema_version") != "issued_recommendation_v1"
            or not isinstance(ident, str) or not ident.strip()
            or not issued.get("issued_at_utc") or not issued.get("field_id")
            or not selection.get("crop_id") or not selection.get("candidate_week")):
        raise ValueError("Invalid issued recommendation snapshot")
    field_id = int(issued["field_id"])
    frozen = {
        "assessment": issued["field_assessment_snapshot"],
        "boundary": issued["boundary_geometry"],
        "ranking": issued.get("rotation_preference_ranking") or [],
        "field_history": issued.get("field_history_at_issue"),
        "preference_scores": issued.get("preference_scores_at_issue"),
        "recommendation_id": ident,
        "issued_at_utc": issued["issued_at_utc"],
        "boundary_version": issued.get("boundary_version"),
        "farm_id": issued.get("farm_id"),
        "record_type": "issued_field_check_guidance_not_sowing_instruction",
        "alternatives": issued.get("eligible_alternatives"),
    }
    payload, digest = _serialized(frozen)
    ensure_schema(database)
    with sqlite3.connect(database) as db:
        existing = db.execute("SELECT id FROM field_outcomes WHERE recommendation_id=?", (ident,)).fetchone()
        if existing:
            return existing[0], False
        cur = db.execute("""INSERT INTO field_outcomes
            (field_id, digest, snapshot, recommendation_id)
            VALUES(?, ?, ?, ?)""", (field_id, digest, payload, ident))
        return cur.lastrowid, True


def save_legacy_review(database: Path, field_id: int, assessment: dict,
                       boundary: str | None, ranking: list) -> tuple[int, bool]:
    """Preserve previous 'save selected assessment' behavior, not an issuance."""
    frozen = {"assessment": assessment, "boundary": boundary,
              "ranking": ranking, "record_type": "unverified_review_not_issued"}
    payload, digest = _serialized(frozen)
    ensure_schema(database)
    with sqlite3.connect(database) as db:
        db.execute("""INSERT INTO field_outcomes(field_id, digest, snapshot)
                      VALUES(?,?,?) ON CONFLICT(field_id,digest) DO NOTHING""",
                   (int(field_id), digest, payload))
        result = db.execute("SELECT id FROM field_outcomes WHERE field_id=? AND digest=?",
                            (int(field_id), digest)).fetchone()
        return result[0], db.total_changes > 0


def records_for_field(database: Path, field_id: int) -> list[dict]:
    ensure_schema(database)
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute(
            "SELECT * FROM field_outcomes WHERE field_id=? ORDER BY id DESC", (int(field_id),))]


def _as_date(value: str | date | None, label: str, *, today: date) -> date | None:
    if value is None or value == "":
        return None
    try:
        result = date.fromisoformat(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError(f"{label} must be a calendar date") from exc
    if not isinstance(result, date) or isinstance(result, datetime):
        raise ValueError(f"{label} must be a calendar date")
    if result > today:
        raise ValueError(f"{label} cannot be in the future")
    return result


def update_observation(
    database: Path, *, record_id: int, field_id: int, revision: int,
    actual_crop: str | None, planting_status: str,
    planted: str | date | None, emerged: str | date | None,
    emergence_end: str | date | None, establishment: str,
    observation_date: str | date | None, evidence_source: str | None,
    stress: str | None, today: date | None = None,
) -> bool:
    """Save independently observed facts, with optimistic concurrency.

    Returns False on a stale revision. A not-planted recommendation never gains
    a fabricated negative success label; partially established is not binary.
    """
    today = today or datetime.now(ATHENS).date()
    if planting_status not in PLANTING or establishment not in ESTABLISHMENT:
        raise ValueError("Unsupported planting or establishment status")
    if evidence_source not in EVIDENCE:
        raise ValueError("Unsupported evidence source")
    sowed = _as_date(planted, "Actual sowing", today=today)
    first = _as_date(emerged, "Emergence start", today=today)
    last = _as_date(emergence_end, "Emergence end", today=today)
    observed = _as_date(observation_date, "Observation", today=today)
    actual_crop = (actual_crop or "").strip() or None
    stress = (stress or "").strip() or None
    if planting_status == "Planted":
        if sowed is None:
            raise ValueError("Planted fields require an actual sowing date")
    elif sowed or first or last or establishment != "Not assessed":
        raise ValueError("Unplanted/unknown fields cannot have sowing, emergence, or establishment outcomes")
    if first and sowed and first < sowed:
        raise ValueError("Emergence cannot precede actual sowing")
    if last and not first:
        raise ValueError("Enter the start of the emergence interval first")
    if last and first and last < first:
        raise ValueError("Emergence interval end cannot precede its start")
    if (first or establishment != "Not assessed" or planting_status == "Not planted") and observed is None:
        raise ValueError("An observation date is required for assessed outcomes or confirmed non-planting")
    if (first or establishment != "Not assessed" or planting_status == "Not planted") and evidence_source == "Not provided":
        raise ValueError("An evidence source is required for assessed outcomes or confirmed non-planting")
    if observed and sowed and observed < sowed and (first or establishment != "Not assessed"):
        raise ValueError("Establishment observation cannot predate sowing")

    ensure_schema(database)
    with sqlite3.connect(database) as db:
        found = db.execute("SELECT field_id FROM field_outcomes WHERE id=?", (record_id,)).fetchone()
        if found is None or found[0] != int(field_id):
            raise ValueError("Unknown field outcome record")
        cursor = db.execute("""UPDATE field_outcomes SET
            crop=?, planted=?, emerged=?, emergence_end=?, establishment=?, stress=?,
            planting_status=?, observation_date=?, evidence_source=?,
            observation_updated_at=CURRENT_TIMESTAMP, revision=revision+1
            WHERE id=? AND field_id=? AND revision=?""",
            (actual_crop, sowed.isoformat() if sowed else None,
             first.isoformat() if first else None, last.isoformat() if last else None,
             establishment, stress, planting_status,
             observed.isoformat() if observed else None, evidence_source,
             record_id, int(field_id), revision))
        return cursor.rowcount == 1


def as_export_records(database: Path) -> list[dict]:
    """Flatten observed (not inferred) outcomes; keep missing targets empty."""
    ensure_schema(database)
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM field_outcomes ORDER BY id").fetchall()
    result = []
    for item in rows:
        row = dict(item)
        frozen = json.loads(row["snapshot"])
        assessment = frozen.get("assessment") or {}
        planted = row["planted"]
        emerged = row["emerged"]
        end = row["emergence_end"]
        days = (date.fromisoformat(emerged) - date.fromisoformat(planted)).days if emerged and planted else None
        end_days = (date.fromisoformat(end) - date.fromisoformat(planted)).days if end and planted else None
        interval = end is not None and emerged is not None and end != emerged
        status = row["planting_status"]
        # Infer 'Planted' for older records with an actual sowing date; don't infer
        # 'Not planted' merely from a missing sowing date.
        if status == "Not yet known" and planted:
            status = "Planted"
        established = row["establishment"] or "Not assessed"
        credible_outcome = planted and row["observation_date"] and row["evidence_source"] not in (None, "Not provided")
        target = (1 if established == "Established" else 0 if established == "Failed to establish" else None) if credible_outcome else None
        result.append({
            "record_id": row["id"],
            "record_type": "issued" if row["recommendation_id"] else "legacy_unverified",
            "recommendation_id": row["recommendation_id"],
            "issued_at_utc": frozen.get("issued_at_utc") if row["recommendation_id"] else None,
            "farm_id": frozen.get("farm_id"),
            "field_id": row["field_id"],
            "boundary_version": frozen.get("boundary_version"),
            "season": assessment.get("season"),
            "recommended_crop": assessment.get("crop_id"),
            "candidate_week": assessment.get("week_start"),
            "observed_crop": row["crop"],
            "planting_status": status,
            "actual_sowing_date": planted,
            "emergence_date_or_start": emerged,
            "emergence_interval_end": end,
            "establishment_result": established,
            "established_successfully": target,
            "observation_date": row["observation_date"],
            "evidence_source": row["evidence_source"],
            "days_to_emergence": days if not interval else None,
            "days_to_emergence_min": days,
            "days_to_emergence_max": end_days if interval else days,
            "stress_notes": row["stress"],
            "revision": row["revision"],
            "saved_at_utc": row["saved_at"],
            "observation_updated_at_utc": row["observation_updated_at"],
        })
    return result


def export_outcomes_csv(database: Path, destination: Path) -> Path:
    """Atomically refresh a GENERATED CSV; refuse to overwrite user-managed data.

    A sidecar tracks the last generated CSV digest. If the CSV is changed by an
    external editor, the app stops instead of silently discarding those edits.
    """
    records = as_export_records(database)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    marker = destination.with_name(destination.name + ".agrisim-generated.json")
    if destination.exists():
        if not marker.exists():
            raise FileExistsError(f"Existing CSV is not managed by AgriSim: {destination}. Move or back it up before enabling automatic export.")
        try:
            metadata = json.loads(marker.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise RuntimeError("Invalid generated CSV sidecar; refusing to overwrite") from exc
        existing_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
        if metadata.get("sha256") != existing_sha:
            raise RuntimeError("The outcomes CSV has changed outside AgriSim. Preserve edits before regenerating it.")
    elif marker.exists():
        raise RuntimeError("Generated CSV is missing, but its sidecar exists; refusing to overwrite metadata")

    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    marker_temp = marker.parent / f".{marker.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in records:
                writer.writerow({key: "" if value is None else value for key, value in row.items()})
        checksum = hashlib.sha256(temporary.read_bytes()).hexdigest()
        marker_temp.write_text(json.dumps({"producer": "AgriSim outcome_store",
                                           "schema_version": 1, "sha256": checksum}), encoding="utf-8")
        os.replace(temporary, destination)
        os.replace(marker_temp, marker)
    finally:
        temporary.unlink(missing_ok=True)
        marker_temp.unlink(missing_ok=True)
    return destination


def sync_from_parquet(database: Path, parquet_dataset: Path) -> int:
    """Repair partial writes or connect snapshots created by the earlier patch."""
    import pandas as pd
    parquet_dataset = Path(parquet_dataset)
    if not parquet_dataset.is_dir() or not any(parquet_dataset.glob("*.parquet")):
        return 0
    try:
        rows = pd.read_parquet(parquet_dataset, columns=["snapshot_json"])
    except ImportError as exc:
        raise RuntimeError("Install pyarrow with 'uv add pyarrow' to relink snapshots") from exc
    count = 0
    for payload in rows["snapshot_json"]:
        _, created = record_issued_snapshot(database, json.loads(payload))
        count += int(created)
    return count
