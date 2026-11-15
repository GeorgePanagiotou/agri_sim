"""Provider contract. A provider turns (variable, area, period) into ONE daily UTC series in canonical units."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import pandas as pd

from ..areas import Area
from ..variables import SourceVar


class NoData(Exception):
    """The source is fine but has nothing for this area / period."""


class ProviderError(Exception):
    """The source could not be read (network, HTTP error, missing file, bad payload)."""


@dataclass
class Fetched:
    series: pd.Series                 # DatetimeIndex (daily, UTC date), float, canonical unit, NaN = missing
    origin: str                       # live | cache | local
    n_cells: int
    method: str                       # how the area was turned into one number
    notes: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class Provider(Protocol):
    name: str
    title: str
    native_resolution: str
    reference: str

    def fetch(self, var: SourceVar, area: Area, start: date, end: date) -> Fetched: ...
