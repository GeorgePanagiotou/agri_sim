"""Offline tests; no NASA/ESA/FAO requests or user data required."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from agrisim.features.build_multisource_environment import (
    CROPS,
    build_daily,
    gaez_suitability,
    grow_seasons,
    power_input,
)


def fixtures():
    days = pd.date_range("2024-09-01", "2025-06-30")
    power = pd.DataFrame({"date": days, "power_temp_c": 20.0, "power_rain_mm": 2.0})
    gpm = pd.DataFrame({"date": days[:-2], "gpm_rain_mm": 1.0,
                        "gpm_valid_cells": 16, "gpm_product": "IMERG_Final_V07"})
    smap = pd.DataFrame({"date": days, "smap_surface_m3m3": 0.3,
                         "smap_soil_temp_c": 18.0, "smap_complete_day": True})
    terrain = pd.DataFrame([{"field_id": "evia_pilot", "elevation_m_median": 59.28,
                             "slope_deg_median": 3.32, "aspect_deg_circular_mean": 309.1}])
    gaez = pd.DataFrame([{"crop": crop, "suitability_index": v}
                         for crop, v in zip(CROPS, [8070., 6440., 5943., 6899., 5999.])])
    return power, gpm, smap, terrain, gaez


def test_season_date_counts():
    periods = grow_seasons()
    assert len(periods) == 6
    assert [int((b-a).days+1) for _,a,b in periods] == [303, 303, 303, 304, 303, 303]
    assert sum((b-a).days+1 for _,a,b in periods) == 1819


def test_daily_missing_dates_not_filled_and_asof_rolls():
    power, gpm, smap, terrain, gaez = fixtures()
    out, qa = build_daily(power, gpm, smap, terrain, gaez,
                          first_year=2024, last_year=2024)
    assert len(out) == 303
    assert out.date.is_unique
    assert out.loc[7, "imerg_rain_prior_7d_mm"] == 7
    assert pd.isna(out.loc[6, "imerg_rain_prior_7d_mm"])
    # Missing day 2025-06-29 means June 30 daily rainfall is not silently zero.
    assert pd.isna(out.iloc[-1]["gpm_rain_mm"])
    assert bool(out.iloc[-1]["imerg_missing"])
    assert out.iloc[-1]["gaez_wheat_index"] == 8070
    assert out.iloc[-1]["srtm_elevation_m_median"] == pytest.approx(59.28)
    assert qa.iloc[0]["calendar_days"] == 303
    assert qa.iloc[0]["imerg_days"] == 301


def test_prior_roll_excludes_same_day_large_rainfall():
    power, gpm, smap, terrain, gaez = fixtures()
    gpm.loc[gpm.date == pd.Timestamp("2024-09-08"), "gpm_rain_mm"] = 1000
    out, _ = build_daily(power, gpm, smap, terrain, gaez,
                         first_year=2024, last_year=2024)
    assert out.loc[out.date.eq(pd.Timestamp("2024-09-08")),
                   "imerg_rain_prior_7d_mm"].item() == 7
    assert out.loc[out.date.eq(pd.Timestamp("2024-09-09")),
                   "imerg_rain_prior_7d_mm"].item() == 1006


def test_2026_rain_missing_while_smap_present():
    power, gpm, smap, terrain, gaez = fixtures()
    # Mirror reported coverage pattern: SMAP through June, IMERG not acquired in 2026.
    power = pd.DataFrame({"date": pd.date_range("2025-09-01", "2026-06-30"),
                          "power_temp_c": 19.0})
    smap = pd.DataFrame({"date": power.date, "smap_surface_m3m3": 0.3})
    gpm = pd.DataFrame({"date": pd.date_range("2025-09-01", "2025-12-31"),
                        "gpm_rain_mm": 2.0,
                        "gpm_product": ["IMERG_Final_V07"] * 30 + ["IMERG_Late_V07"] * 92})
    out, qa = build_daily(power, gpm, smap, terrain, gaez,
                          first_year=2025, last_year=2025)
    jan = out.loc[out.date.eq(pd.Timestamp("2026-01-01"))].iloc[0]
    assert pd.isna(jan.gpm_rain_mm)
    assert bool(jan.imerg_missing)
    assert jan.smap_surface_m3m3 == pytest.approx(.3)
    assert qa.iloc[0]["imerg_final_days"] == 30
    assert qa.iloc[0]["imerg_late_days"] == 92
    assert qa.iloc[0]["imerg_days"] == 122
    assert qa.iloc[0]["smap_days"] == 303


def test_reject_duplicate_dates():
    power, gpm, smap, terrain, gaez = fixtures()
    power = pd.concat([power, power.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="POWER has duplicate"):
        build_daily(power, gpm, smap, terrain, gaez,
                    first_year=2024, last_year=2024)


def test_reject_invalid_static_or_clear_threshold():
    power, gpm, smap, terrain, gaez = fixtures()
    with pytest.raises(ValueError, match="min_clear"):
        build_daily(power, gpm, smap, terrain, gaez,
                    min_clear=1.1, first_year=2024, last_year=2024)
    with pytest.raises(ValueError, match="five expected"):
        build_daily(power, gpm, smap, terrain, gaez.iloc[:4],
                    first_year=2024, last_year=2024)


def test_power_file_auto_selection(tmp_path):
    a = tmp_path / "power_daily_19910101_20251231.parquet"
    b = tmp_path / "power_daily_19910101_20261031.parquet"
    c = tmp_path / "power_daily_20230101_20251231.parquet"
    for f in (a,b,c): f.touch()
    assert power_input(tmp_path, None) == b
    assert power_input(tmp_path, a) == a


def test_gaez_rasters_match_5_expected_crops(tmp_path):
    for i, (crop, code) in enumerate(CROPS.items()):
        path = tmp_path / f"{crop}_rainfed_historical_low_input_suLr_{code}.tif"
        with rasterio.open(
            path, "w", driver="GTiff", width=4, height=4, count=1,
            dtype="int16", crs="EPSG:4326",
            transform=from_origin(23.30, 38.90, 0.08333333333, 0.08333333333),
            nodata=-9999,
        ) as ds:
            ds.write(np.full((1,4,4), 8000 + i, dtype="int16"))
    out = gaez_suitability(tmp_path, lon=23.43232, lat=38.75920)
    assert len(out) == 5
    assert out.loc[out.crop.eq("dry_pea"), "suitability_index"].item() == 8004
    assert out.source.eq("FAO_GAEZ_v4_suLr").all()
    with pytest.raises(FileNotFoundError, match="Expected exactly one"):
        (tmp_path / "chickpea_rainfed_historical_low_input_suLr_chk.tif").unlink()
        gaez_suitability(tmp_path)


def test_satellite_source_indices_not_merged(tmp_path):
    power, gpm, smap, terrain, gaez = fixtures()
    pd.DataFrame({
        "date_utc": ["2024-09-05"], "ndvi_median": [0.50],
        "evi2_median": [0.3], "clear_fraction": [1.0],
    }).to_csv(tmp_path / "vegetation_observations.csv", index=False)
    pd.DataFrame({
        "date_utc": ["2024-09-05", "2024-09-06"],
        "ndvi_median": [0.40, 0.8], "evi2_median": [0.28, 0.6],
        "clear_fraction": [1.0, 0.50],
    }).to_csv(tmp_path / "sentinel2_aligned_evia_pilot_2024_2025.csv", index=False)
    out, qa = build_daily(power, gpm, smap, terrain, gaez,
                          vegetation_dir=tmp_path, min_clear=0.8,
                          first_year=2024, last_year=2024)
    d = out.loc[out.date.eq(pd.Timestamp("2024-09-05"))].iloc[0]
    assert d.hls_ndvi == pytest.approx(0.50)
    assert d.s2_ndvi == pytest.approx(0.40)
    assert d.hls_minus_s2_ndvi == pytest.approx(0.10)
    assert bool(d.hls_s2_same_day)
    assert pd.isna(out.loc[out.date.eq(pd.Timestamp("2024-09-06")), "s2_ndvi"].iloc[0])
    assert qa.iloc[0]["same_day_sensor_pairs"] == 1


def test_rolling_features_do_not_jump_over_missing_summer(tmp_path):
    # Six-season table is dense in the full calendar before filtering.
    power, gpm, smap, terrain, gaez = fixtures()
    dates = pd.date_range("2024-09-01", "2026-06-30")
    power = pd.DataFrame({"date": dates, "power_temp_c": 20.0})
    gpm = pd.DataFrame({"date": dates, "gpm_rain_mm": 2.0})
    smap = pd.DataFrame({"date": dates[dates.month.isin([9,10,11,12,1,2,3,4,5,6])],
                         "smap_surface_m3m3": 0.3})
    out, _ = build_daily(power, gpm, smap, terrain, gaez,
                         first_year=2024, last_year=2025)
    assert len(out) == 606
    assert out.loc[out.season.eq("2025-2026"), "season_day"].iloc[0] == 0
    # Sept 1 should see the last seven calendar days of Aug, even though off-season
    assert out.loc[out.date.eq(pd.Timestamp("2025-09-01")), "imerg_rain_prior_7d_mm"].item() == 14
    # Aug had no SMAP; do not jump from June to count it as recent moisture
    assert pd.isna(out.loc[out.date.eq(pd.Timestamp("2025-09-01")), "smap_surface_prior_7d_m3m3"].item())
