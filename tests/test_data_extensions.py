"""Pure offline checks for the additive data acquisition/fusion modules."""
import numpy as np
import pandas as pd
import pytest

from agrisim.data_sources.download_evia_smap_range import expected_slots, make_daily
from agrisim.features.build_environment_multisource import (
    _regional_area_mean,
    build_environment,
    smap_daily,
)


def test_smap_3hourly_times_and_missing_days():
    slots = expected_slots("2024-02-01", "2024-02-02")
    assert len(slots) == 16
    assert slots[0] == "2024-02-01T01:30:00Z"
    assert slots[-1] == "2024-02-02T22:30:00Z"
    manifest = pd.DataFrame({"time_utc": slots, "concept_id": range(16)})
    records = {
        slot: {
            "time_utc": slot, "granule": f"g{i}",
            "sm_surface_m3m3": 0.27, "soil_temp_layer1_K": 290.0,
        }
        for i, slot in enumerate(slots[:8])
    }
    hourly, daily = make_daily(manifest, records, "2024-02-01", "2024-02-02")
    assert len(hourly) == 16
    assert daily.sm_samples.tolist() == [8, 0]
    assert daily.complete_day.tolist() == [True, False]
    assert np.isnan(daily.sm_surface_m3m3.iloc[1])


def test_regional_precip_is_observed_not_filled():
    raw = pd.DataFrame({
        "date": ["2025-10-01", "2025-10-01"],
        "lat": [38.75, 38.85], "lon": [23.35, 23.45],
        "precip_mm": [0.0, 8.0],
    })
    out = _regional_area_mean(raw, "IMERG_Late_V07")
    assert len(out) == 1
    assert out.gpm_rain_mm.iloc[0] == 4
    assert out.gpm_product.iloc[0] == "IMERG_Late_V07"


def test_no_leakage_and_missing_precip_not_zero():
    days = pd.date_range("2025-10-01", periods=20)
    power = pd.DataFrame({"date": days, "power_temp_c": 18.0})
    gpm = pd.DataFrame({
        "date": days[:7], "gpm_rain_mm": [1., 2., 3., 4., 5., 6., 7.],
        "gpm_valid_cells": 16, "gpm_product": "IMERG_Late_V07",
    })
    smap = pd.DataFrame({
        "date": days[:3], "smap_surface_m3m3": [0.1, 0.2, 0.3],
        "smap_soil_temp_c": [14., 13., 12.], "smap_samples": 8,
        "smap_product": "NASA_SPL4SMGP_v008",
    })
    out = build_environment(power, gpm, smap)
    assert pd.isna(out.loc[6, "rain_prior_7d_mm"])
    assert out.loc[7, "rain_prior_7d_mm"] == 28
    assert pd.isna(out.loc[8, "rain_prior_7d_mm"])
    assert pd.isna(out.loc[10, "gpm_rain_mm"])
    assert bool(out.loc[10, "gpm_missing"])
    assert out.loc[7, "temp_prior_7d_c"] == 18.0
    assert out.loc[7, "geometry_status"] == "unverified_provisional_candidate_3x3"


def test_overlapping_smap_same_values_deduplicated(tmp_path):
    folder = tmp_path / "smap"
    folder.mkdir()
    content = pd.DataFrame({
        "date_utc": ["2024-01-31"],
        "sm_surface_m3m3": [0.25],
        "soil_temp_layer1_C": [14.2],
        "sm_samples": [8],
    })
    content.to_csv(folder / "smap_daily.csv", index=False)
    content.to_csv(folder / "smap_daily_2024-01-31_2024-06-30.csv", index=False)
    out = smap_daily(folder)
    assert len(out) == 1


def test_overlapping_smap_conflicts_fail(tmp_path):
    folder = tmp_path / "smap"
    folder.mkdir()
    data = pd.DataFrame({
        "date_utc": ["2024-01-31"],
        "sm_surface_m3m3": [0.25],
        "soil_temp_layer1_C": [14.2],
        "sm_samples": [8],
    })
    data.to_csv(folder / "smap_daily.csv", index=False)
    data["sm_surface_m3m3"] = 0.3
    data.to_csv(folder / "smap_daily_2024-01-31_2024-06-30.csv", index=False)
    with pytest.raises(ValueError, match="Conflicting SMAP"):
        smap_daily(folder)


def test_hls_and_s2_kept_as_separate_indices(tmp_path):
    from agrisim.features.build_environment_multisource import add_vegetation

    hls = pd.DataFrame({
        "date_utc": ["2025-01-09"], "ndvi_median": [0.27],
        "evi2_median": [0.17], "clear_fraction": [1.0],
    })
    s2 = pd.DataFrame({
        "date_utc": ["2025-01-09", "2025-01-10"],
        "ndvi_median": [0.23, 0.4], "evi2_median": [0.15, 0.2],
        "clear_fraction": [1.0, 0.3],
    })
    hls.to_csv(tmp_path / "vegetation_observations.csv", index=False)
    s2.to_csv(tmp_path / "sentinel2_aligned_evia_pilot_2024_2025.csv", index=False)
    env = pd.DataFrame({"date": pd.date_range("2025-01-09", periods=2)})
    out = add_vegetation(env, tmp_path, min_clear=0.8)
    assert out.hls_ndvi.iloc[0] == pytest.approx(0.27)
    assert out.s2_ndvi.iloc[0] == pytest.approx(0.23)
    assert pd.isna(out.s2_ndvi.iloc[1])
    assert pd.isna(out.hls_ndvi.iloc[1])


def test_smap_checkpoint_upsert_keeps_old_days(tmp_path, monkeypatch):
    from agrisim.data_sources import download_evia_smap_range as x
    monkeypatch.setattr(x.base, "CACHE", tmp_path)
    old = pd.DataFrame({
        "time_utc": ["2024-02-01T01:30:00Z"],
        "concept_id": ["old"],
        "sm_surface_m3m3": [0.2],
    })
    old.to_csv(tmp_path / "points_2024-02.csv", index=False)
    records = {
        "2024-02-01T04:30:00Z": {
            "time_utc": "2024-02-01T04:30:00Z",
            "concept_id": "new", "sm_surface_m3m3": 0.3,
        }
    }
    x.upsert_months(records, {"2024-02"})
    out = pd.read_csv(tmp_path / "points_2024-02.csv")
    assert len(out) == 2
    assert set(out.concept_id) == {"old", "new"}


def test_incomplete_smap_daily_is_not_used_as_complete(tmp_path):
    folder = tmp_path / "smap"
    folder.mkdir()
    frame = pd.DataFrame({
        "date_utc": ["2025-02-01", "2025-02-02"],
        "sm_surface_m3m3": [0.25, 0.26],
        "soil_temp_layer1_C": [12., 13.],
        "sm_samples": [8, 6],
        "temp_samples": [8, 8],
        "complete_day": [True, False],
    })
    frame.to_csv(folder / "smap_daily_2025-02-01_2025-02-02.csv", index=False)
    out = smap_daily(folder).reset_index(drop=True)
    assert out.smap_complete_day.tolist() == [True, False]
    assert out.smap_surface_m3m3.iloc[0] == pytest.approx(0.25)
    assert pd.isna(out.smap_surface_m3m3.iloc[1])


def test_fao_url_is_scoped_to_official_suitability_rasters():
    from agrisim.data_sources.download_gaez_official import validate_url
    url = (
        "https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/"
        "res05/CRUTS32/Hist/8110L/suLr_whe.tif"
    )
    assert validate_url(url, "suitability-index") == "suLr_whe.tif"
    with pytest.raises(ValueError):
        validate_url("https://example.org/siHr0_whe.tif", "suitability-index")
    with pytest.raises(ValueError):
        validate_url("https://s3.eu-west-1.amazonaws.com/other-bucket/siHr0_whe.tif", "suitability-index")
    with pytest.raises(ValueError):
        validate_url(url.replace("suLr_whe.tif", "ycLr_whe.tif"), "suitability-index")


def test_imerg_late_frame_source_retained(monkeypatch):
    import sys, types
    if "earthaccess" not in sys.modules:
        monkeypatch.setitem(sys.modules, "earthaccess", types.ModuleType("earthaccess"))
    from agrisim.data_sources.download_imerg_late_2025 import consolidate
    rows = [pd.DataFrame({
        "date": ["2025-10-01"], "lat": [38.75], "lon": [23.35], "precip_mm": [0.0],
    })]
    data = consolidate(rows)
    assert data.iloc[0]["source"] == "IMERG_Late_V07"
    assert data.iloc[0]["precip_mm"] == 0.0
