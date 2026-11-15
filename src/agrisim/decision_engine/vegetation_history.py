"""Point-in-time HLS green-up evidence for the provisional Evia pilot footprint."""
from __future__ import annotations

import pandas as pd

from agrisim.timeseries.greenup import COLUMNS_REQUIRED, analyze_group, quality_dates

SITE = "evia_pilot"
SOURCE = "NASA_HLSL30_v2"
S30_SOURCE = "NASA_HLSS30_v2"
SUPPORT = "provisional_center_3x3"
DETECTED = "retrospective_spectral_greenup"
INSUFFICIENT = {"insufficient_clear_dates", "insufficient_temporal_coverage"}
MIN_CLEAR_DATES = 6


def _season_position(date):
    """Month and day ordered from the start of the September growing season."""
    return ((date.month - 9) % 12, date.day)


def prepare_observations(frame: pd.DataFrame, field_id=SITE, support=SUPPORT) -> pd.DataFrame:
    required = COLUMNS_REQUIRED | {"spatial_support"}
    if missing := required - set(frame.columns):
        raise ValueError(f"Vegetation observations missing {sorted(missing)}")
    pilot = frame.loc[frame.field_id.eq(field_id) & frame.source.isin((SOURCE,S30_SOURCE))
                      & frame.spatial_support.eq(support)].copy()
    pilot["date_utc"] = pd.to_datetime(pilot.date_utc, utc=True).dt.tz_localize(None)
    releases = pilot.get("available_utc", pd.Series(pd.NaT, index=pilot.index))
    pilot["available_utc"] = pd.to_datetime(releases, utc=True, format="mixed")
    if pilot.date_utc.isna().any() or pilot.date_utc.duplicated().any():
        raise ValueError("Expected one selected HLS pilot observation per acquisition date")
    years = pilot.date_utc.dt.year - (pilot.date_utc.dt.month < 9).astype(int)
    if not pilot.season.eq(years.astype(str) + "-" + (years + 1).astype(str)).all():
        raise ValueError("HLS observation season disagrees with its acquisition date")
    if (pilot.available_utc < pilot.date_utc.dt.tz_localize("UTC")).any():
        raise ValueError("HLS availability precedes acquisition")
    return pilot.sort_values("date_utc").reset_index(drop=True)


def greenup_history(candidates: pd.DataFrame, observations: pd.DataFrame, *, field_id=SITE, support=SUPPORT) -> pd.DataFrame:
    """Refit PELT on visible acquisitions only, including for late-published past seasons."""
    pilot = prepare_observations(observations, field_id, support)
    cached_events = {}
    records = []
    for season, week in candidates[["season", "week_start"]].drop_duplicates().itertuples(index=False):
        # The assessment is made at the START of the week; never use images
        # acquired or published at/after the cutoff. Missing publication times
        # are not silently treated as data that was already available.
        cutoff = pd.Timestamp(week)
        if cutoff.tzinfo is not None:
            cutoff = cutoff.tz_convert("UTC").tz_localize(None)
        cutoff = cutoff.normalize()
        utc_cutoff = cutoff.tz_localize("UTC")
        acquired_before = pilot.date_utc.lt(cutoff)
        visible = pilot.loc[acquired_before & pilot.available_utc.lt(utc_cutoff)]
        unknown_release = int((acquired_before & pilot.available_utc.isna()).sum())
        usable_visible = quality_dates(visible) if not visible.empty else visible
        this_season = visible.loc[visible.season.eq(season)]
        this_clear = quality_dates(this_season) if not this_season.empty else this_season
        current = None
        previous = []
        prior_assessed = 0
        prior_insufficient = 0
        prior_count = 0
        for observed_season, group in visible.groupby("season", sort=True):
            key = tuple(group.index)
            if key not in cached_events:
                cached_events[key] = analyze_group(group, method="pelt")
            event = cached_events[key]
            if observed_season == season:
                current = event
            elif observed_season < season:
                prior_count += 1
                if event["status"] not in INSUFFICIENT:
                    prior_assessed += 1
                else:
                    prior_insufficient += 1
                if event["status"] == DETECTED:
                    previous.append(event)
        last = previous[-1] if previous else {}
        current = current or {}
        timing = "unavailable"
        if last:
            timing = "within"
            if _season_position(week) < _season_position(pd.Timestamp(last["last_low_date"])):
                timing = "before"
            elif _season_position(week) > _season_position(pd.Timestamp(last["first_high_date"])):
                timing = "after"
        status = "observations_available" if not visible.empty else "no_available_observations"
        if visible.empty and not pilot.empty and pilot.available_utc.isna().all():
            status = "missing_publication_dates"
        if not visible.empty and usable_visible.empty:
            quality_status = "no_usable_clear_dates"
        elif len(this_clear) < MIN_CLEAR_DATES:
            quality_status = "insufficient_current_season_clear_dates"
        else:
            quality_status = "minimum_clear_date_count_met"
        current_gap = this_clear.date_utc.diff().dt.days.dropna() if len(this_clear) else pd.Series(dtype="float64")
        records.append({
            "season": season, "week_start": week, "component_a_vegetation_status": status,
            "vegetation_observations_available": len(visible),
            "vegetation_latest_available_utc": visible.available_utc.max(),
            "vegetation_usable_clear_dates": len(usable_visible),
            "vegetation_quality_rejected_acquisitions": len(visible) - len(usable_visible),
            "vegetation_acquisitions_missing_publication_dates": unknown_release,
            "vegetation_quality_status": quality_status,
            "greenup_prior_seasons_with_visible_scenes": prior_count,
            "greenup_prior_seasons_insufficient_coverage": prior_insufficient,
            "greenup_prior_seasons_assessed": prior_assessed,
            "greenup_prior_seasons_detected": len(previous),
            "greenup_latest_prior_season": last.get("season"),
            "greenup_prior_last_low": last.get("last_low_date"),
            "greenup_prior_first_high": last.get("first_high_date"),
            "week_vs_latest_prior_greenup": timing,
            "greenup_current_status": current.get("status", "no_available_observations"),
            "greenup_current_acquisitions": len(this_season),
            "greenup_current_clear_dates": len(this_clear),
            "greenup_current_quality_rejected_acquisitions": len(this_season) - len(this_clear),
            "greenup_current_clear_dates_needed": max(0, MIN_CLEAR_DATES-len(this_clear)),
            "greenup_current_first_clear_date": (str(this_clear.date_utc.min().date()) if len(this_clear) else None),
            "greenup_current_latest_clear_date": (str(this_clear.date_utc.max().date()) if len(this_clear) else None),
            "greenup_current_largest_clear_gap_days": (int(current_gap.max()) if len(current_gap) else None),
            "greenup_current_candidate_transition_gaps": current.get("n_candidate_transition_gaps", 0),
            "greenup_current_last_low": current.get("last_low_date"),
            "greenup_current_first_high": current.get("first_high_date"),
            "greenup_current_confirmed_high": current.get("confirmed_high_date"),
        })
    return pd.DataFrame(records)


def apply_greenup(decisions: pd.DataFrame, observations: pd.DataFrame, *, field_id=SITE, support=SUPPORT) -> pd.DataFrame:
    history = greenup_history(decisions, observations, field_id=field_id, support=support)
    out = decisions.drop(columns="component_a_vegetation_status").merge(
        history, on=["season", "week_start"], how="left", validate="many_to_one")
    out["vegetation_field_id"] = field_id
    out["vegetation_source"] = "NASA_HLSL30_and_HLSS30_v2" if observations.get("source", pd.Series(dtype=str)).eq(S30_SOURCE).any() else SOURCE
    out["vegetation_spatial_support"] = support
    out["component_e_fusion_status"] = "partial_A_B_D"
    for i, row in out.iterrows():
        note = []
        if row.greenup_prior_seasons_detected:
            note.append(f"Pilot HLS green-up detected in {row.greenup_prior_seasons_detected} of "
                        f"{row.greenup_prior_seasons_assessed} assessable earlier seasons. Latest transition "
                        f"between {row.greenup_prior_last_low} and {row.greenup_prior_first_high}.")
        elif row.greenup_prior_seasons_assessed:
            note.append(f"No spectral green-up CONFIRMED in {row.greenup_prior_seasons_assessed} assessable earlier seasons; "
                        "absence of detection is not proof of no vegetation.")
        else:
            note.append("No assessable earlier pilot green-up history at this week’s start.")
        if row.greenup_current_status == DETECTED:
            note.append(f"This season's pilot transition was between {row.greenup_current_last_low} "
                        f"and {row.greenup_current_first_high}, confirmed by {row.greenup_current_confirmed_high}.")
        elif row.greenup_current_status == "insufficient_clear_dates":
            note.append(f"Current-season pilot coverage: {row.greenup_current_clear_dates} clear dates; "
                        "six are required to assess green-up.")
        elif row.greenup_current_status == "insufficient_temporal_coverage":
            note.append("At least six clear dates exist, but none bracket a transition within the "
                        "maximum 40-day gap. No green-up conclusion can be drawn.")
        elif row.greenup_current_status == "no_confirmed_greenup":
            note.append("Current-season spectral green-up was not confirmed by the detector; "
                        "this does not establish that no crop emerged.")
        if row.vegetation_observations_available:
            note.append(f"Satellite evidence before this week: "
                        f"{row.vegetation_observations_available} available acquisition(s), "
                        f"{row.vegetation_usable_clear_dates} passing the field-level "
                        "cloud/quality screen across all seasons.")
        if row.vegetation_acquisitions_missing_publication_dates:
            note.append(f"Excluded {row.vegetation_acquisitions_missing_publication_dates} "
                        "acquisition(s) without verified publication timestamps.")
        if row.greenup_prior_seasons_insufficient_coverage:
            note.append(f"{row.greenup_prior_seasons_insufficient_coverage} historical "
                        "season(s) lack sufficient temporal evidence for assessment.")
        if row.decision_priority == "candidate_for_field_check":
            if row.greenup_current_status == DETECTED:
                out.at[i, "recommended_action"] += " Inspect standing vegetation before preparing the seedbed."
            elif row.greenup_prior_seasons_detected:
                if row.week_vs_latest_prior_greenup == "before":
                    out.at[i, "recommended_action"] += " This week precedes the latest historical green-up interval. Record current cover as a baseline during the visit."
                else:
                    out.at[i, "recommended_action"] += " This week falls within or after the latest historical green-up interval. Check for living cover before preparing the seedbed."
        text = " ".join(note)
        if support != SUPPORT:
            text = text.replace("Pilot", "Field").replace("pilot", "field")
        out.at[i, "decision_explanation"] += " " + text
    return out
