import pandas as pd

from agrisim.decision_engine.vegetation_history import apply_greenup


def observations():
    dates = pd.date_range("2023-09-01", periods=8, freq="7D")
    return pd.DataFrame({
        "field_id": "evia_pilot", "source": "NASA_HLSL30_v2", "spatial_support": "provisional_center_3x3",
        "date_utc": dates, "season": "2023-2024", "available_utc": dates + pd.Timedelta(days=1),
        "valid_pixels": 9, "clear_fraction": 1.0,
        "ndvi_median": [.12, .14, .15, .14, .60, .61, .63, .62],
        "evi2_median": [.07, .08, .09, .08, .40, .41, .42, .43],
    })


def decisions():
    return pd.DataFrame({
        "week_start": pd.to_datetime(["2023-11-01", "2023-11-02", "2024-11-01", "2024-11-01"]),
        "season": ["2023-2024"] * 2 + ["2024-2025"] * 2,
        "component_a_vegetation_status": "not_integrated",
        "decision_priority": ["candidate_for_field_check"] * 3 + ["regional_risk_warning"],
        "recommended_action": "Original action.", "decision_explanation": "Regional screen.",
    })


def test_delayed_publication_and_asof_refit():
    obs = observations()
    # The bright acquisitions exist in October but their revision is published in November.
    obs.loc[4:, "available_utc"] = pd.Timestamp("2023-11-01")
    out = apply_greenup(decisions(), obs)
    assert out.greenup_current_clear_dates.tolist() == [4, 8, 0, 0]
    assert out.greenup_current_status.iloc[0] == "insufficient_clear_dates"
    assert out.greenup_current_confirmed_high.iloc[1] == "2023-10-06"
    assert "standing vegetation" in out.recommended_action.iloc[1]
    assert out.greenup_prior_seasons_detected.tolist() == [0, 0, 1, 1]
    assert out.week_vs_latest_prior_greenup.iloc[2] == "after"
    assert "living cover" in out.recommended_action.iloc[2]
    assert out.recommended_action.iloc[3] == "Original action."
    truncated = apply_greenup(decisions().iloc[[0]], obs.iloc[:4])
    pd.testing.assert_frame_equal(out.iloc[[0]], truncated, check_dtype=False)


def test_unknown_vintage_and_other_footprints_cannot_supply_history():
    obs = observations()
    other = obs.assign(field_id="another_site")
    out = apply_greenup(decisions(), pd.concat([obs.assign(available_utc=pd.NaT), other]))
    assert out.component_a_vegetation_status.eq("missing_publication_dates").all()
    assert out.vegetation_observations_available.eq(0).all()
    assert out.recommended_action.eq("Original action.").all()
    legacy = apply_greenup(decisions(), obs.drop(columns="available_utc"))
    assert legacy.greenup_prior_seasons_detected.eq(0).all()
