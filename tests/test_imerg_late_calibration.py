"""IMERG Late -> Final monthly factors (offline)."""
import warnings

import pandas as pd
import pytest

from agrisim.data_sources import imerg_late_calibration as cal


def write(tmp_path, factors):
    pd.DataFrame({"month": range(1, 13), "factor": factors}).to_csv(tmp_path / cal.FILE, index=False)


def test_late_days_scale_by_their_month(tmp_path):
    write(tmp_path, [0.5] * 6 + [1.0] * 6)
    late = pd.DataFrame({"date": pd.to_datetime(["2026-01-15", "2026-07-15"]), "precip_mm": [10.0, 10.0]})
    out = cal.apply(late, cal.load_factors(tmp_path))
    assert out.precip_mm.tolist() == [5.0, 10.0]
    assert late.precip_mm.tolist() == [10.0, 10.0]          # input not modified


def test_missing_file_warns_and_keeps_raw(tmp_path):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        f = cal.load_factors(tmp_path)
    assert f is None and any("uncorrected" in str(x.message) for x in w)
    late = pd.DataFrame({"date": pd.to_datetime(["2026-01-15"]), "precip_mm": [10.0]})
    assert cal.apply(late, f).precip_mm.tolist() == [10.0]


def test_implausible_factors_are_rejected(tmp_path):
    write(tmp_path, [0.75] * 11 + [9.0])
    with pytest.raises(ValueError):
        cal.load_factors(tmp_path)
