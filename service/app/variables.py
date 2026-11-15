"""Canonical variables. One entry says how each source's native variable maps to the common one.

Every source value is converted to the canonical unit here, so nothing downstream knows about native units.
The order of `sources` is the default priority when several sources have a value for the same day.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceVar:
    native: str          # column / parameter name in that source
    factor: float = 1.0  # canonical = native * factor


@dataclass(frozen=True)
class Variable:
    name: str
    unit: str            # unit of the daily value
    agg: str             # how days combine into a month / year: "sum" or "mean"
    description: str
    sources: dict[str, SourceVar]
    total_unit: str | None = None  # unit of a monthly / yearly sum (mm/day -> mm)

    @property
    def min_coverage(self) -> float:
        """Share of days of a month/year that must have data. A sum with missing days is biased low, so it needs all."""
        return 1.0 if self.agg == "sum" else 0.9

    def unit_for(self, aggregate: str) -> str:
        return self.total_unit if (self.agg == "sum" and aggregate != "daily" and self.total_unit) else self.unit


_LIST = [
    Variable("precipitation", "mm/day", "sum", "Daily precipitation (UTC day)",
             {"imerg": SourceVar("precip_mm"), "power": SourceVar("PRECTOTCORR")}, total_unit="mm"),
    Variable("temperature_mean", "°C", "mean", "Daily mean 2 m air temperature", {"power": SourceVar("T2M")}),
    Variable("temperature_max", "°C", "mean", "Daily maximum 2 m air temperature", {"power": SourceVar("T2M_MAX")}),
    Variable("temperature_min", "°C", "mean", "Daily minimum 2 m air temperature", {"power": SourceVar("T2M_MIN")}),
    Variable("relative_humidity", "%", "mean", "Daily mean 2 m relative humidity", {"power": SourceVar("RH2M")}),
    Variable("wind_speed", "m/s", "mean", "Daily mean 2 m wind speed", {"power": SourceVar("WS2M")}),
    # POWER gives kWh/m2/day; 1 kWh = 3.6 MJ
    Variable("solar_radiation", "MJ/m²/day", "mean", "Daily all-sky shortwave radiation at the surface",
             {"power": SourceVar("ALLSKY_SFC_SW_DWN", 3.6)}),
]
VARIABLES: dict[str, Variable] = {v.name: v for v in _LIST}
