"""Browse the saved Evia decision-engine assessments."""
from pathlib import Path

import pandas as pd
import streamlit as st
from field_boundary import boundary_editor, field_assessment, render_field_hls_acquisition
from field_profiles import inputs, save_widget, select_field
from field_outcomes import render_log
from field_ranking import render_ranking

RESULTS = Path(__file__).resolve().parents[1] / "outputs" / "evia_sowing_with_rotation.csv"


def label(value):
    return "Unavailable" if pd.isna(value) else str(value).replace("_", " ").capitalize()


def render():
    st.title("Evia sowing decisions")
    st.caption("North Evia · Field satellite history and regional sowing conditions.")
    if not RESULTS.is_file():
        st.error("The rebuilt rotation results are missing. Generate the assessment file with the command below.")
        st.code("python -m agrisim.decision_engine.pipeline --sowing-csv outputs/sowing_weeks.csv --risk-csv outputs/risk_daily.csv --output outputs/evia_sowing_with_rotation.csv")
        return
    data = pd.read_csv(RESULTS)
    field = select_field()
    profile = inputs(field)
    boundary = profile.get("boundary")
    boundary_editor(field, boundary)
    seasons = sorted(data.season.unique(), reverse=True)
    season_key = f"season_{field}"
    season = st.sidebar.selectbox("Growing season", seasons, index=seasons.index(profile["season"]) if profile.get("season") in seasons else 0,
                                  key=season_key, on_change=save_widget, args=(field,"season",season_key))
    subset = data[data.season.eq(season)]
    crops = sorted(subset.crop_id.unique())
    crop_key = f"crop_{field}_{season}"
    preferred = profile.get(f"crop:{season}", "winter_wheat")
    crop = st.sidebar.selectbox("Crop", crops, index=crops.index(preferred) if preferred in crops else 0, format_func=label, key=crop_key, on_change=save_widget, args=(field,f"crop:{season}",crop_key))
    weeks = subset[subset.crop_id.eq(crop)].sort_values("week_start")
    known = weeks[weeks.sowing_verdict.ne("unknown")]
    default = known.iloc[-1] if len(known) else weeks.iloc[0]
    dates = weeks.week_start.tolist()
    week = st.sidebar.selectbox("Week starting", dates, index=dates.index(default.week_start))
    r = weeks[weeks.week_start.eq(week)].iloc[0]
    r, coverage, visible = field_assessment(r, field, boundary)
    render_field_hls_acquisition(field, boundary, week, coverage)
    st.subheader(f"{label(crop)} · {week}")
    a,b,c = st.columns(3)
    a.metric("Sowing screen", label(r.sowing_verdict))
    b.metric("Regional risk", label(r.risk_overall_label))
    c.metric("Earlier green-ups", f"{r.greenup_prior_seasons_detected} / {r.greenup_prior_seasons_assessed}")
    st.write(r.recommended_action)
    st.caption("Field inputs: boundary, HLS green-up, Landsat cover, reported crop history and preferences. Regional inputs: IMERG rainfall, SMAP soil moisture and temperature, POWER weather, hazard alerts and the Evia pilot GAEZ suitability cell.")
    sow, vegetation, hazards, rotation, outcome, validation = st.tabs(["Sowing recommendation", "Green-up history", "Risk alerts", "Matching rotations", "Field outcome log", "Decision validation"])
    with sow:
        st.write(r.sowing_explanation)
        st.caption("Weekly screens for the selected crop and growing season")
        st.dataframe(weeks[["week_start","sowing_verdict","risk_overall_label"]].rename(columns={
            "week_start":"Week starting","sowing_verdict":"Sowing screen","risk_overall_label":"Regional risk"}),hide_index=True)
        st.download_button("Download selected assessment", r.to_frame().T.to_csv(index=False), f"evia_{crop}_{week}.csv", "text/csv")
    with vegetation:
        st.subheader("Satellite acquisition and quality coverage")
        a, b, c = st.columns(3)
        a.metric("Available HLS scenes", int(r.vegetation_observations_available))
        b.metric("Usable clear dates", int(r.vegetation_usable_clear_dates))
        c.metric("Not usable after filtering", int(r.vegetation_quality_rejected_acquisitions))
        st.caption("All counts are point-in-time: only acquisitions published before the selected week are included. "
                   "Usable means >=4 valid pixels, >=60% clear coverage, and valid NDVI/EVI2. "
                   "These are dates across ALL available seasons, not current-season dates.")
        if r.vegetation_acquisitions_missing_publication_dates:
            st.warning(f"{int(r.vegetation_acquisitions_missing_publication_dates)} scene(s) "
                       "with unverified publication timestamps were excluded.")
        st.write(f"Current season: {int(r.greenup_current_acquisitions)} available acquisitions, "
                 f"{int(r.greenup_current_clear_dates)} usable clear dates; "
                 f"{int(r.greenup_current_quality_rejected_acquisitions)} quality-rejected.")
        if pd.notna(r.greenup_current_first_clear_date):
            st.caption(f"Current-season clear-date range: {r.greenup_current_first_clear_date} to "
                       f"{r.greenup_current_latest_clear_date}. "
                       f"Largest observed gap: "
                       f"{r.greenup_current_largest_clear_gap_days if pd.notna(r.greenup_current_largest_clear_gap_days) else 'N/A'} days.")
        if r.greenup_current_clear_dates_needed:
            st.info(f"At least {int(r.greenup_current_clear_dates_needed)} more "
                    "usable clear date(s) are required to meet the six-date minimum. "
                    "Even six dates may not sufficiently bracket a green-up transition.")
        if r.greenup_current_status == "insufficient_temporal_coverage":
            st.warning("The available clear dates are too far apart to assess a transition "
                       "under the 40-day maximum transition gap.")
        st.caption("No confirmed spectral transition does not prove that sowing or crop "
                   "emergence did not occur; confirm against field visits.")
        st.write(f"Earlier assessable seasons: {r.greenup_prior_seasons_assessed}. "
                 f"Seasons with detected green-up: {r.greenup_prior_seasons_detected}. "
                 f"Historical seasons with insufficient coverage: "
                 f"{r.greenup_prior_seasons_insufficient_coverage}.")
        if pd.notna(r.greenup_prior_first_high):
            st.write(f"Latest earlier transition ({r.greenup_latest_prior_season}): {r.greenup_prior_last_low} to {r.greenup_prior_first_high}.")
        st.write(f"Current season: {label(r.greenup_current_status)} · {r.greenup_current_clear_dates} clear dates.")
        if pd.notna(r.greenup_current_confirmed_high):
            st.write(f"Transition from {r.greenup_current_last_low} to {r.greenup_current_first_high}, confirmed {r.greenup_current_confirmed_high}.")
        st.write(coverage)
        if not visible.empty:
            st.line_chart(visible.set_index("date_utc")[["ndvi_median","evi2_median"]])
    with hazards:
        st.write(f"Evidence coverage: {label(r.risk_evidence_status)}")
        if pd.isna(r.risk_overall_label):
            st.info("Regional risk level unavailable for this week.")
        for hazard in ("drought","dry_spell","heat","frost","heavy_rain"):
            st.markdown(f"**{label(hazard)} · {label(r['risk_'+hazard+'_label'])}**")
            reason = r["risk_explain_"+hazard]
            if pd.notna(reason):
                st.write(reason)
        st.caption(label(r.risk_reference_temporal_status))
    with rotation:
        names = {"A":"Cereal and fallow","B":"Legume forage","C":"Bee and soil","D":"Low water"}
        for phase in str(r.rotation_options).split("; ") if pd.notna(r.rotation_options) else []:
            strategy, _, detail = phase.partition(" ")
            st.write(f"{strategy} · {names.get(strategy,strategy)} · {detail.replace('_',' ')}")
        if pd.isna(r.rotation_options):
            st.info("No matching rotation phase.")
        st.write(f"Field Landsat cover ({r.rotation_prior_season_end_year}): {label(r.rotation_prior_landsat_class)}")
        value = r.rotation_gaez_index
        st.write("Rainfed regional suitability: " + ("Unavailable" if pd.isna(value) else f"{value:,.0f} / 10,000"))
        ranking = render_ranking(r, names, field, profile)
    with outcome:
        render_log(field, r, profile, ranking, candidate_weeks=weeks)
    with validation:
        st.subheader("Module A–E evaluation")
        st.caption("Engineering and observed-outcome metrics only. Missing field evidence is reported explicitly; no historical regional screen is treated as an issued forecast.")
        report_dir = RESULTS.parents[0] / "decision_completion"
        status_file = report_dir / "completion_status.json"
        if status_file.exists():
            import json
            status = json.loads(status_file.read_text(encoding="utf-8"))
            st.json(status)
            for module in ("a_vegetation_validation", "b_sowing_evaluation", "c_rotation_evidence",
                           "c_suitability_gaps", "d_risk_evaluation", "e_decision_evaluation"):
                path = report_dir / (module + ".csv")
                if path.exists():
                    with st.expander(module.replace("_", " ").title()):
                        st.dataframe(pd.read_csv(path),hide_index=True)
        else:
            st.info("Run the A–E evidence report from PowerShell before viewing module validation here.")
            st.code("uv run python -m agrisim.decision_engine.completion_cli --create-templates")
