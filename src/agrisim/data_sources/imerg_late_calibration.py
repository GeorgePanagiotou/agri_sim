"""Monthly factors that bring IMERG Late Run days onto the IMERG Final scale (data_prep/imerg_late_calibration.py).

Late is not gauge-adjusted; over Evia it runs ~30-35 % wetter than Final on the same days. Every reader that fills
the Final gap with Late multiplies the Late days by the factor of their calendar month. Without the factor file,
Late stays raw and a warning says so.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

FILE = "imerg_late_to_final.csv"


def load_factors(proc: Path) -> pd.Series | None:
    path = Path(proc) / FILE
    if not path.exists():
        warnings.warn(f"{path} missing: IMERG Late days are used uncorrected "
                      "(run data_prep/imerg_late_calibration.py)", stacklevel=2)
        return None
    f = pd.read_csv(path).set_index("month")["factor"]
    if sorted(f.index) != list(range(1, 13)) or not f.between(0.2, 5).all():
        raise ValueError(f"{path}: expected 12 monthly factors between 0.2 and 5")
    return f


def apply(late: pd.DataFrame, factors: pd.Series | None, col: str = "precip_mm") -> pd.DataFrame:
    """Late rows (with a 'date' column) scaled by their month's factor; unchanged when factors is None."""
    if factors is None or late.empty:
        return late
    out = late.copy()
    out[col] = out[col] * pd.to_datetime(out["date"]).dt.month.map(factors).to_numpy()
    return out
