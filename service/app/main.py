"""Climate harmonization API. Run: uvicorn app.main:app  (docs at /docs)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from . import harmonize
from .areas import NAMED_AREAS, AreaError, parse_area
from .config import get_settings
from .providers import build_providers
from .variables import VARIABLES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="AgriSim climate API",
    version="0.1.0",
    description="One endpoint, several sources: NASA POWER and GPM IMERG (and more) on a common daily UTC axis, "
                "canonical units, WGS84. Use `/v1/series/{variable}`.")


@app.get("/health", tags=["meta"])
def health():
    s = get_settings()
    files = {f: (s.data_dir / f).exists() for f in ("imerg_daily_2001_2025.parquet", "power_daily_1981_2026.parquet")}
    return {"status": "ok", "power_mode": s.power_mode, "local_files": files}


@app.get("/v1/variables", tags=["meta"])
def variables():
    return [{"name": v.name, "unit": v.unit, "total_unit": v.total_unit, "aggregation": v.agg,
             "description": v.description, "sources_in_default_priority": list(v.sources)} for v in VARIABLES.values()]


@app.get("/v1/sources", tags=["meta"])
def sources():
    providers = build_providers(get_settings())
    return [{"name": p.name, "title": p.title, "native_resolution": p.native_resolution, "reference": p.reference,
             "variables": [v.name for v in VARIABLES.values() if p.name in v.sources]} for p in providers.values()]


@app.get("/v1/areas", tags=["meta"])
def areas():
    return {name: {"label": a["label"], **({"bbox": a["bbox"]} if "bbox" in a else {"point": a["point"]})}
            for name, a in NAMED_AREAS.items()}


@app.get("/v1/series/{variable}", tags=["data"])
def series(
    variable: str,
    start: date = Query(..., description="first day, YYYY-MM-DD (UTC)"),
    end: date = Query(..., description="last day, inclusive"),
    area: str | None = Query(None, description="named area, see /v1/areas"),
    lon: float | None = Query(None, description="point longitude (WGS84)"),
    lat: float | None = Query(None, description="point latitude (WGS84)"),
    bbox: str | None = Query(None, description="west,south,east,north (WGS84)"),
    sources: str | None = Query(None, description="comma list; the order is the priority. Default: all, best first"),
    aggregate: Literal["daily", "monthly", "yearly"] = "daily",
    format: Literal["json", "csv"] = "json",
):
    var = VARIABLES.get(variable)
    if var is None:
        raise HTTPException(404, f"unknown variable {variable!r}; known: {', '.join(VARIABLES)}")
    settings = get_settings()
    try:
        a = parse_area(area, lon, lat, bbox)
    except AreaError as exc:
        raise HTTPException(422, str(exc)) from None
    if end < start:
        raise HTTPException(422, "end is before start")
    if (end - start).days + 1 > settings.max_days:
        raise HTTPException(422, f"period too long (max {settings.max_days} days)")
    names = [s.strip() for s in sources.split(",") if s.strip()] if sources else list(var.sources)
    bad = [n for n in names if n not in var.sources]
    if bad or len(set(names)) != len(names) or not names:
        raise HTTPException(422, f"bad sources {bad or names}; {variable} is available from: {', '.join(var.sources)}")

    result = harmonize.run(var, a, start, end, names, aggregate, settings)
    if not result.ok:
        failed = any(s["status"] == "error" for s in result.meta["sources"].values())
        raise HTTPException(502 if failed else 404, {"message": "no source returned data", "sources": result.meta["sources"]})

    if format == "csv":
        csv = result.table.to_csv(float_format="%.3f")
        return Response(csv, media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{variable}_{aggregate}.csv"'})
    return {**result.meta, "data": harmonize.records(result.table)}
