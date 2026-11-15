"""Fetch every requested source in parallel, put them on one daily UTC axis, aggregate, pick a value, compare."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .areas import Area
from .providers import build_providers
from .providers.base import Fetched, NoData, ProviderError
from .config import Settings
from .variables import Variable

log = logging.getLogger("climate-api")
_RULE = {"monthly": "MS", "yearly": "YS"}
_FMT = {"daily": "%Y-%m-%d", "monthly": "%Y-%m", "yearly": "%Y"}


@dataclass
class Result:
    meta: dict
    table: pd.DataFrame  # index = time label; columns = value, selected_source, <source names>

    @property
    def ok(self) -> bool:
        return any(s["status"] == "ok" for s in self.meta["sources"].values())


def _fetch(provider, var: Variable, area: Area, start: date, end: date):
    try:
        return provider.fetch(var.sources[provider.name], area, start, end), None
    except NoData as exc:
        return None, {"status": "no_data", "detail": str(exc)}
    except ProviderError as exc:
        return None, {"status": "error", "detail": str(exc)}
    except Exception as exc:  # one broken source must not take the others down
        log.exception("unexpected error in %s", provider.name)
        return None, {"status": "error", "detail": f"unexpected {type(exc).__name__}"}


def _aggregate(daily: pd.DataFrame, var: Variable, aggregate: str) -> pd.DataFrame:
    """Monthly / yearly from daily. A period only counts if its full calendar period has enough valid days,
    so partial periods (edges of the requested range) come back null instead of a misleading short sum."""
    if aggregate == "daily":
        return daily
    offset = pd.offsets.MonthBegin(1) if aggregate == "monthly" else pd.offsets.YearBegin(1)
    out = {}
    for col in daily:
        g = daily[col].resample(_RULE[aggregate])
        value = g.sum(min_count=1) if var.agg == "sum" else g.mean()
        expected = pd.Series(
            [(ts + offset - ts).days for ts in value.index],
            index=value.index,
            dtype="float64",
        )
        required = np.ceil(float(var.min_coverage) * expected.to_numpy(dtype="float64"))
        out[col] = value.where(g.count().to_numpy() >= required)
    return pd.DataFrame(out)


def _compare(table: pd.DataFrame, names: list[str]) -> list[dict]:
    rows = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both = table[[a, b]].dropna()
            rows.append({
                "a": a, "b": b, "n_overlap": len(both),
                "mean_bias_a_minus_b": round(float((both[a] - both[b]).mean()), 3) if len(both) else None,
                "rmse": round(float(np.sqrt(((both[a] - both[b]) ** 2).mean())), 3) if len(both) else None,
                "correlation": round(float(both[a].corr(both[b])), 3) if len(both) > 2 else None})
    return rows


def run(var: Variable, area: Area, start: date, end: date, sources: list[str], aggregate: str,
        settings: Settings) -> Result:
    providers = build_providers(settings)
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        outcomes = dict(zip(sources, pool.map(lambda n: _fetch(providers[n], var, area, start, end), sources)))

    idx = pd.date_range(start, end, freq="D")
    status: dict[str, dict] = {}
    daily = pd.DataFrame(index=idx)
    for name in sources:  # keep the order the caller asked for: it is the priority order
        fetched, problem = outcomes[name]
        p = providers[name]
        if problem:
            status[name] = {"title": p.title, **problem}
            continue
        assert isinstance(fetched, Fetched)
        s = fetched.series.reindex(idx)
        daily[name] = s
        status[name] = {
            "status": "ok", "title": p.title, "origin": fetched.origin, "native_resolution": p.native_resolution,
            "native_variable": var.sources[name].native, "unit_factor": var.sources[name].factor,
            "n_cells": fetched.n_cells, "method": fetched.method,
            "coverage": {"first": _day(s.first_valid_index()), "last": _day(s.last_valid_index()),
                         "valid_days": int(s.notna().sum()), "requested_days": len(idx)},
            "notes": fetched.notes, **fetched.extra}

    ok = [n for n in sources if status[n]["status"] == "ok"]
    table = _aggregate(daily, var, aggregate) if ok else pd.DataFrame(index=idx[:0])
    value = pd.Series(np.nan, index=table.index)
    chosen = pd.Series(None, index=table.index, dtype="object")
    for name in ok:  # first source with a value wins, in priority order
        take = value.isna() & table[name].notna()
        value[take], chosen[take] = table.loc[take, name], name
    table = table.copy()
    table.insert(0, "selected_source", chosen)
    table.insert(0, "value", value)
    time_index = pd.DatetimeIndex(table.index)
    table.index = pd.Index(time_index.strftime(_FMT[aggregate]), name="time")

    meta = {
        "variable": var.name, "description": var.description, "unit": var.unit_for(aggregate),
        "aggregate": aggregate, "time_standard": "UTC", "crs": "EPSG:4326",
        "area": area.as_dict(), "period": {"start": str(start), "end": str(end), "days": len(idx)},
        "selection_rule": "value = first source with data, in the order of `sources_priority`",
        "sources_priority": ok, "sources": status,
        "comparison": _compare(table, ok),
    }
    if aggregate != "daily":
        unit = {"monthly": "month", "yearly": "year"}[aggregate]
        meta["aggregation_rule"] = (f"{var.agg} of daily values; a {unit} needs {int(var.min_coverage * 100)}% "
                                    f"of its calendar days with data, otherwise null (also for partial {unit}s)")
    return Result(meta, table)


def _day(ts) -> str | None:
    return None if ts is None else str(ts.date())


def records(table: pd.DataFrame) -> list[dict]:
    """JSON rows: NaN -> null, 3 decimals."""
    out = []
    for t, row in table.iterrows():
        rec = {"time": t, "value": _num(row["value"]), "selected_source": None if pd.isna(row["selected_source"]) else row["selected_source"],
               "values": {c: _num(row[c]) for c in table.columns if c not in ("value", "selected_source")}}
        out.append(rec)
    return out


def _num(x):
    return None if pd.isna(x) else round(float(x), 3)
