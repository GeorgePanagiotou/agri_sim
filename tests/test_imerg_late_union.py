"""IMERG Final + Late Run union: all Late quarters are read, Final wins on overlapping dates."""
import pandas as pd

from agrisim.features.build_environment_multisource import imerg_daily

CELLS = [(38.85, 23.35), (38.85, 23.45), (38.95, 23.35), (38.95, 23.45)]   # inside the Evia study area


def cells(dates, value):
    return pd.DataFrame([(d, lat, lon, value) for d in dates for lat, lon in CELLS],
                        columns=["date", "lat", "lon", "precip_mm"])


def test_late_quarters_read_and_final_wins(tmp_path):
    (tmp_path / "imerg_daily").mkdir()
    (tmp_path / "imerg_late").mkdir()
    cells(pd.date_range("2025-09-01", "2025-09-30"), 1.0).to_parquet(tmp_path / "imerg_daily" / "2025.parquet")
    cells(pd.date_range("2025-09-25", "2025-12-31"), 5.0).to_parquet(tmp_path / "imerg_late" / "2025_Q4.parquet")
    cells(pd.date_range("2026-01-01", "2026-01-10"), 7.0).to_parquet(tmp_path / "imerg_late" / "2026_Q1.parquet")
    out = imerg_daily(tmp_path).set_index("date")
    assert out.index.is_unique
    assert out.loc["2025-09-28", "gpm_product"] == "IMERG_Final_V07" and out.loc["2025-09-28", "gpm_rain_mm"] == 1.0
    assert out.loc["2025-10-01", "gpm_product"] == "IMERG_Late_V07"
    assert out.loc["2026-01-10", "gpm_rain_mm"] == 7.0
    assert len(out) == 30 + 92 + 10
