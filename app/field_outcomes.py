"""Evia pilot field outcomes: one issued ID links Parquet evidence to SQLite observations.

Do not interpret historical regional assessments as recommendations issued in the past.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import field_profiles
from agrisim.decision_engine.recommendation_log import (
    build_recommendation_snapshot, append_recommendation,
)
from agrisim.decision_engine.completion_alternatives import current_week_alternatives
from agrisim.decision_engine.completion_provenance import source_manifest
from agrisim.decision_engine.outcome_store import (
    ESTABLISHMENT, PLANTING, EVIDENCE, record_issued_snapshot, save_legacy_review,
    records_for_field, update_observation, export_outcomes_csv, sync_from_parquet,
)

ROOT = Path(__file__).resolve().parents[1]
ISSUED_PATH = ROOT / "data/local/issued_recommendations.parquet"
EXPORT_PATH = ROOT / "data/local/field_outcomes.csv"
ATHENS = ZoneInfo("Europe/Athens")


def _assessment_dict(assessment: pd.Series) -> dict:
    return json.loads(assessment.to_json(date_format="iso"))


def _ranking_list(ranking: pd.DataFrame | None) -> list:
    return json.loads(ranking.to_json(orient="records")) if ranking is not None else []


def _date_input(label: str, raw: str | None, key: str):
    value = date.fromisoformat(raw) if raw else None
    return st.date_input(label, value=value, min_value=date(1980, 1, 1),
                         max_value=datetime.now(ATHENS).date(), key=key)


def render_log(field, assessment, profile, ranking, *, candidate_weeks: pd.DataFrame | None = None):
    """Render issuance, historic reviews, and growing-season outcome follow-up."""
    database = field_profiles.DATABASE
    boundary = profile.get("boundary")
    st.subheader("Recommendation and field outcome records")
    st.caption("Issuing guidance freezes a timestamped recommendation. Field observations are saved later against that exact recommendation ID. Historical reviews are kept separate.")

    now = datetime.now(ATHENS)
    week = pd.Timestamp(assessment["week_start"]).date()
    current_week = week <= now.date() < week + timedelta(days=7)
    can_issue = candidate_weeks is not None and bool(boundary) and current_week
    if not boundary:
        st.info("Save the field boundary before issuing field-specific guidance.")
    elif not current_week:
        st.info("Selected week is not current in Greece. Historical and future candidate screens cannot be issued as if they were today's forecast.")

    if can_issue and st.button("Issue and save field-check recommendation", key=f"issue_outcome_{field}_{week}_{assessment['crop_id']}"):
        snapshot = None
        parquet_written = False
        try:
            snapshot = build_recommendation_snapshot(
                assessment, field_id=str(field), boundary=boundary,
                candidate_weeks=candidate_weeks, farm_id=profile.get("farm_id"),
                ranking=ranking, field_profile=profile,
                alternatives=current_week_alternatives(
                    assessment, ranking, field_id=str(field)),
                model_versions=source_manifest(ROOT),
            )
            append_recommendation(snapshot, ISSUED_PATH)
            parquet_written = True
            record_id, _ = record_issued_snapshot(database, snapshot)
            export_outcomes_csv(database, EXPORT_PATH)
        except (ValueError, RuntimeError, OSError, TypeError, KeyError) as exc:
            if parquet_written:
                st.error(f"Parquet issuance was saved (ID {snapshot['recommendation_id']}), but its SQLite link/export did not complete: {exc}. Use 'Relink issued recommendations' below to repair the link.")
            else:
                st.error(f"Nothing was issued: {exc}")
        else:
            st.session_state[f"outcome_record_{field}"] = record_id
            st.success("Issued and linked: " + snapshot["recommendation_id"])
            st.rerun()

    with st.expander("Historical review and recovery"):
        st.caption("For past candidate weeks, store a review without inventing an issue time or recommendation ID.")
        if st.button("Save selected assessment as unissued review", key=f"review_{field}_{week}_{assessment['crop_id']}"):
            record_id, inserted = save_legacy_review(
                database, int(field), _assessment_dict(assessment), boundary, _ranking_list(ranking),
            )
            st.session_state[f"outcome_record_{field}"] = record_id
            try:
                export_outcomes_csv(database, EXPORT_PATH)
            except (OSError, RuntimeError) as exc:
                st.warning(f"Review saved in SQLite but CSV export was not refreshed: {exc}")
            else:
                st.success("Review stored." if inserted else "This review was already stored.")
                st.rerun()
        if st.button("Relink issued recommendations from Parquet", key=f"relink_{field}"):
            try:
                count = sync_from_parquet(database, ISSUED_PATH)
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                st.error(f"Relinking failed: {exc}")
            else:
                try:
                    export_outcomes_csv(database, EXPORT_PATH)
                except (OSError, RuntimeError) as exc:
                    st.warning(f"Relinked {count} issued record(s) in SQLite but CSV export was not refreshed: {exc}")
                else:
                    st.success(f"Relinked {count} missing issued record(s).")
                    st.rerun()

    rows = records_for_field(database, int(field))
    if not rows:
        st.info("No recommendations or field reviews have been saved for this field.")
        return

    records = {row["id"]: row for row in rows}
    def label_record(record_id):
        item = records[record_id]
        assessment_row = json.loads(item["snapshot"]).get("assessment") or {}
        crop = (assessment_row.get("crop_id") or "unknown").replace("_", " ")
        kind = "Issued" if item["recommendation_id"] else "Legacy / unissued"
        return f"#{record_id} · {kind} · {assessment_row.get('week_start', '?')} · {crop}"

    picker = f"outcome_record_{field}"
    selected = st.selectbox("Saved record", list(records), format_func=label_record, key=picker)
    row = records[selected]
    frozen = json.loads(row["snapshot"])
    previous = frozen.get("assessment") or {}
    st.caption("Saved: " + str(row["saved_at"]) + " UTC")
    if row["recommendation_id"]:
        st.markdown("**Issued recommendation ID:** `" + row["recommendation_id"] + "`")
        st.caption("Issued: " + str(frozen.get("issued_at_utc")) + " UTC")
    else:
        st.warning("This older record has no confirmed issuance ID. Treat it as an unverified assessment, not a dated farmer recommendation.")
    st.write(previous.get("recommended_action") or "No saved action text")
    with st.expander("Frozen recommendation evidence"):
        st.write(previous.get("decision_explanation") or "Not recorded")
        if frozen.get("ranking"):
            st.caption("User preference ranking at save time — not a measured field benefit")
            st.dataframe(frozen["ranking"], hide_index=True)
        if frozen.get("field_history"):
            st.write("Reported previous crops:", frozen["field_history"])

    with st.expander("Saved current-week rotation alternatives"):
        if row["recommendation_id"]:
            st.caption("Conditional preference comparisons only; not measured rotation benefits.")
            alternatives = frozen.get("alternatives")
            st.write(alternatives if alternatives is not None else "See immutable Parquet snapshot for complete alternatives")
        else:
            st.caption("Legacy review does not have issued alternatives")

    st.markdown("**Observed field outcome**")
    st.caption("An unplanted recommendation has no establishment result. Enter what was actually observed; blank dates remain unknown.")
    prefix = f"observed_{selected}_{row['revision']}"
    existing_planting = row["planting_status"] or "Not yet known"
    if existing_planting == "Not yet known" and row["planted"]:
        existing_planting = "Planted"  # legacy SQLite entry with a sowing date

    with st.form(prefix):
        crop = st.text_input("Crop actually planted (if known)", value=row["crop"] or "", key=prefix+"_crop")
        planting_status = st.selectbox("Was the field planted?", PLANTING,
            index=PLANTING.index(existing_planting), key=prefix+"_planting")
        planted = _date_input("Actual planting date (only if planted)", row["planted"], prefix+"_planted")
        emerged = _date_input("First observed emergence date (if known)", row["emerged"], prefix+"_emerged")
        emergence_end = _date_input("Emergence interval end (only if date uncertain)", row["emergence_end"], prefix+"_emergence_end")
        establishment = st.selectbox("Establishment result", ESTABLISHMENT,
            index=ESTABLISHMENT.index(row["establishment"] or ESTABLISHMENT[0]), key=prefix+"_establishment")
        observed = _date_input("Field inspection / outcome assessment date", row["observation_date"], prefix+"_observed")
        source = row["evidence_source"] if row["evidence_source"] in EVIDENCE else EVIDENCE[0]
        evidence_source = st.selectbox("Evidence source", EVIDENCE, index=EVIDENCE.index(source), key=prefix+"_source")
        stress = st.text_area("Observed stress and notes", value=row["stress"] or "", key=prefix+"_stress",
            placeholder="What was observed, or 'none observed' following inspection")
        submitted = st.form_submit_button("Save field observations")
    if submitted:
        try:
            updated = update_observation(
                database, record_id=int(selected), field_id=int(field), revision=int(row["revision"]),
                actual_crop=crop, planting_status=planting_status,
                planted=planted, emerged=emerged, emergence_end=emergence_end,
                establishment=establishment, observation_date=observed,
                evidence_source=evidence_source, stress=stress,
            )
        except (ValueError, OSError) as exc:
            st.error(f"Observations were not saved: {exc}")
        else:
            if updated:
                try:
                    export_outcomes_csv(database, EXPORT_PATH)
                except (OSError, RuntimeError) as exc:
                    st.warning(f"Observations WERE saved to SQLite, but the CSV export was not refreshed: {exc}. Reload the page before editing again.")
                else:
                    st.success("Observations saved against this record. The export was refreshed.")
                    st.rerun()
            else:
                st.warning("This record changed in another session. Reload before editing.")

    if EXPORT_PATH.is_file():
        st.download_button("Download field_outcomes.csv", data=EXPORT_PATH.read_bytes(),
                           file_name="field_outcomes.csv", mime="text/csv", key=f"download_outcomes_{field}")
