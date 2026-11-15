"""Area explorer: choose a prepared area (configs/areas/*.yaml) or draw a new box, see what data it has, its
climate (via the climate API in service/, or the same code in-process when the API is down), and start the
data pipeline for a new area.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from agrisim.area import AREAS_DIR, REPO, create, load
from agrisim.pipelines import prepare_area as pa

API_URL = os.environ.get("AGRISIM_API_URL", "http://localhost:8000").rstrip("/")
NEW = "+ New area (draw a box)"
COLORS = {"imerg": "#2563EB", "power": "#D97706"}   # blue / orange: distinct for colour-blind readers too
SOURCE_LABEL = {"imerg": "GPM IMERG (0.1°)", "power": "NASA POWER (0.5°)"}


# ---------------------------------------------------------------- climate: API first, in-process fallback
def _service():
    """Load service/app as package 'agrisim_climate_api' (the name 'app' is taken by this Streamlit folder)."""
    if "agrisim_climate_api" in sys.modules:
        return sys.modules["agrisim_climate_api"]
    init = REPO / "service" / "app" / "__init__.py"
    spec = importlib.util.spec_from_file_location("agrisim_climate_api", init,
                                                  submodule_search_locations=[str(init.parent)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agrisim_climate_api"] = mod
    spec.loader.exec_module(mod)
    return mod


@st.cache_data(ttl=3600, show_spinner=False)
def climate(variable: str, area: str, start: str, end: str, aggregate: str = "monthly") -> tuple[dict | None, str]:
    """(response, how) - how = 'API' or 'in-process'. response None = no source had data."""
    params = {"area": area, "start": start, "end": end, "aggregate": aggregate}
    try:
        r = httpx.get(f"{API_URL}/v1/series/{variable}", params=params, timeout=90)
        if r.status_code == 200:
            return r.json(), "API"
        if r.status_code in (404, 502):
            return None, "API"
    except httpx.HTTPError:
        pass
    _service()   # registers the package, then its modules import normally
    harmonize = importlib.import_module("agrisim_climate_api.harmonize")
    areas = importlib.import_module("agrisim_climate_api.areas")
    config = importlib.import_module("agrisim_climate_api.config")
    variables = importlib.import_module("agrisim_climate_api.variables")
    settings = config.get_settings()
    var = variables.VARIABLES[variable]
    a = areas.parse_area(area, None, None, None, settings.repo_root)
    res = harmonize.run(var, a, date.fromisoformat(start), date.fromisoformat(end), list(var.sources), aggregate,
                        settings)
    return ({**res.meta, "data": harmonize.records(res.table)} if res.ok else None), "in-process"


def chart(resp: dict, title: str, unit: str, kind: str = "line") -> go.Figure:
    fig = go.Figure()
    rows = resp["data"]
    times = [r["time"] for r in rows]
    for src in resp["sources_priority"]:
        y = [r["values"].get(src) for r in rows]
        name = SOURCE_LABEL.get(src, src)
        if kind == "bar":
            fig.add_bar(x=times, y=y, name=name, marker_color=COLORS.get(src))
        else:
            fig.add_scatter(x=times, y=y, name=name, mode="lines+markers", line=dict(color=COLORS.get(src), width=2),
                            marker=dict(size=8))
    fig.update_layout(title=title, yaxis_title=unit, height=340, margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", y=-0.2), barmode="group", hovermode="x unified")
    return fig


# ---------------------------------------------------------------- data status from the area pipeline
def status_table(name: str) -> pd.DataFrame:
    area = load(name)
    spec = pa.steps(area, 1997, 2025, 2025)
    proc = area.data_root / "processed"
    rows = []
    for step in pa.STEP_ORDER:
        done = spec[step]["done"].exists()
        if step == "power":   # its "done" file is dated; any POWER file counts here
            done = any(proc.glob("power_daily_*.parquet"))
        log = area.data_root / "logs" / f"{step}.log"
        rows.append({"step": step, "status": "done" if done else "to do",
                     "log updated": pd.Timestamp(log.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M")
                     if log.exists() else ""})
    return pd.DataFrame(rows)


def running_log(name: str) -> str | None:
    logs = sorted((load(name).data_root / "logs").glob("*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return None
    tail = logs[-1].read_text(encoding="utf-8", errors="replace").strip().splitlines()[-8:]
    return f"{logs[-1].name}:\n" + "\n".join(tail)


def start_pipeline(name: str) -> Path:
    area = load(name)
    log = area.data_root / "logs" / "prepare_area_ui.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with open(log, "a", encoding="utf-8") as fh:
        subprocess.Popen([sys.executable, "-m", "agrisim.pipelines.prepare_area", "--name", name], cwd=REPO,
                         stdout=fh, stderr=subprocess.STDOUT, creationflags=flags,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return log


# ---------------------------------------------------------------- map
def box_map(boxes: list[tuple[str, tuple[float, float, float, float], list[int]]], point=None):
    """boxes: (label, (w, e, s, n), rgb)."""
    polys = [{"label": lab, "polygon": [[w, s], [e, s], [e, n], [w, n]], "color": rgb}
             for lab, (w, e, s, n), rgb in boxes]
    layers = [pdk.Layer("PolygonLayer", polys, get_polygon="polygon", get_fill_color="[color[0], color[1], color[2], 40]",
                        get_line_color="color", line_width_min_pixels=2, pickable=True)]
    if point:
        layers.append(pdk.Layer("ScatterplotLayer", [{"label": "pilot point", "p": list(point)}], get_position="p",
                                get_radius=300, get_fill_color=[220, 38, 38], pickable=True))
    w, e, s, n = boxes[-1][1]
    view = pdk.ViewState(longitude=(w + e) / 2, latitude=(s + n) / 2, zoom=8.5 if (e - w) < 0.5 else 7)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, tooltip={"text": "{label}"},
                             map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"))


# ---------------------------------------------------------------- page
def _create(name: str, box: tuple[float, float, float, float], label: str | None):
    """Button callback (runs before the rerun, so it may switch the area picker to the new area)."""
    try:
        path = create(name, box, label=label)
    except (ValueError, FileExistsError) as exc:
        st.session_state["create_error"] = str(exc)
        return
    st.session_state["area_select"] = name
    st.session_state["created"] = str(path.relative_to(REPO))


def new_area_form():
    st.subheader("New area")
    st.caption("Draw a box (WGS84, at most 1° × 1°). The pipeline then downloads Landsat, soil, terrain, IMERG and "
               "POWER for it and builds the risk, sowing and ML tables. A full run takes a few hours.")
    c1, c2 = st.columns(2)
    name = c1.text_input("Name (lowercase, e.g. thessaly_plain)", "")
    label = c2.text_input("Label", "")
    c = st.columns(4)
    w = c[0].number_input("West (lon)", -180.0, 180.0, 22.30, 0.01, format="%.3f")
    e = c[1].number_input("East (lon)", -180.0, 180.0, 22.50, 0.01, format="%.3f")
    s = c[2].number_input("South (lat)", -90.0, 90.0, 39.50, 0.01, format="%.3f")
    n = c[3].number_input("North (lat)", -90.0, 90.0, 39.65, 0.01, format="%.3f")
    if e > w and n > s:
        box_map([(label or name or "new area", (w, e, s, n), [37, 99, 235])])
        st.caption(f"{(e - w) * 111 * 0.78:.0f} km × {(n - s) * 111:.0f} km (approx.)")
    st.button("Create area", type="primary", disabled=not name, on_click=_create,
              args=(name.strip(), (w, e, s, n), label or None))
    if st.session_state.get("create_error"):
        st.error(st.session_state.pop("create_error"))
    st.code(f"python -m agrisim.pipelines.prepare_area --name {name or '<name>'} --bbox {w} {e} {s} {n}",
            language="powershell")


def render():
    st.title("Area explorer")
    st.caption("Evia is the demo area. Other areas are prepared with the same pipeline from NASA data.")
    names = sorted(p.stem for p in AREAS_DIR.glob("*.yaml"))
    options = names + [NEW]
    default = st.session_state.get("area_choice", "evia")
    labels = {}
    for n_ in names:
        try:
            labels[n_] = load(n_).label
        except (OSError, ValueError, KeyError):
            labels[n_] = n_
    choice = st.sidebar.selectbox("Area", options, index=options.index(default) if default in options else 0,
                                  key="area_select", format_func=lambda o: labels.get(o, o))
    if choice == NEW:
        new_area_form()
        return
    area = load(choice)
    w, e, s, n = area.study_area
    if st.session_state.get("created"):
        st.success(f"Created `{st.session_state.pop('created')}`. Start its data preparation below "
                   "(Data status tab); a full run takes a few hours.")
    st.subheader(area.label)
    st.caption(f"Box {w:.3f}–{e:.3f} E, {s:.3f}–{n:.3f} N · {area.crs} · data in "
               f"`{area.data_root.relative_to(REPO)}`" + (f" · {area.notes}" if area.notes else ""))
    boxes = []
    if area.aoi:
        aw, ae, as_, an = area.aoi
        boxes.append(("analysis area", (aw, ae, as_, an), [148, 163, 184]))
    boxes.append(("study area (data downloaded)", (w, e, s, n), [37, 99, 235]))
    box_map(boxes, area.pilot)

    overview, climate_tab, data_tab = st.tabs(["Data status", "Climate", "ML training data"])
    with overview:
        table = status_table(choice)
        done = (table.status == "done").sum()
        st.metric("Pipeline steps done", f"{done} / {len(table)}")
        st.dataframe(table, hide_index=True, width="stretch")
        live = pa.running(area)
        if live:
            st.info(f"Data preparation is running (since {live['started']}, process {live['pid']}). "
                    "Press Refresh to update the step status.")
        if done < len(table):
            if st.button("Start / resume data preparation", type="primary", disabled=bool(live),
                         help="Runs in the background; finished steps are skipped. Needs Earthdata login (~/_netrc)."):
                log = start_pipeline(choice)
                st.success(f"Started. Progress: refresh this page; log `{log.relative_to(REPO)}`.")
            st.code(f"python -m agrisim.pipelines.prepare_area --name {choice}", language="powershell")
        tail = running_log(choice)
        if tail:
            with st.expander("Latest pipeline log"):
                st.code(tail)
        st.button("Refresh")

    with climate_tab:
        years = st.slider("Years shown", 1, 10, 3)
        end = date.today() - timedelta(days=1)
        start = date(end.year - years, end.month, 1)
        with st.spinner("Loading NASA climate series..."):
            rain, how = climate("precipitation", choice, start.isoformat(), end.isoformat())
            temp, _ = climate("temperature_mean", choice, start.isoformat(), end.isoformat())
        st.caption(f"Source: climate API ({API_URL})" if how == "API" else
                   "Climate API not reachable: same code run in-process (start it: `docker compose up`).")
        if rain:
            st.plotly_chart(chart(rain, "Monthly precipitation (complete months only)", "mm", "bar"),
                            width="stretch")
            for src, meta in rain["sources"].items():
                if meta["status"] != "ok":
                    st.caption(f"{SOURCE_LABEL.get(src, src)}: {meta['status']} – {meta.get('detail', '')}")
                for note in meta.get("notes", []):
                    st.caption(f"{SOURCE_LABEL.get(src, src)}: {note}")
            comp = rain.get("comparison") or []
            if comp and comp[0]["n_overlap"]:
                c = comp[0]
                st.caption(f"IMERG vs POWER over {c['n_overlap']} months: mean difference "
                           f"{c['mean_bias_a_minus_b']:+.0f} mm, correlation {c['correlation']:.2f}. "
                           "IMERG (0.1°) is the better rain source; POWER is a ~55 km cell.")
        else:
            st.info("No precipitation for this area yet (run the imerg steps, or check internet for POWER).")
        if temp:
            st.plotly_chart(chart(temp, "Monthly mean air temperature (NASA POWER)", "°C"), width="stretch")

    with data_tab:
        ml = area.data_root / "processed" / "ml" / "training_table_v1.parquet"
        if ml.exists():
            t = pd.read_parquet(ml, columns=["season", "pixel_id", "target_crop", "target_spring_peak_ndvi"])
            a, b, c = st.columns(3)
            a.metric("Field pixels (30 m)", f"{t.pixel_id.nunique():,}")
            b.metric("Seasons", f"{t.season.min()}–{t.season.max()}")
            c.metric("Rows", f"{len(t):,}")
            by = t.groupby("season").agg(crop_share=("target_crop", "mean"),
                                         spring_peak_ndvi=("target_spring_peak_ndvi", "mean")).reset_index()
            fig = go.Figure(go.Scatter(x=by.season, y=by.crop_share * 100, mode="lines+markers",
                                       line=dict(color="#16A34A", width=2), marker=dict(size=8), name="crop share"))
            fig.update_layout(title="Share of rainfed field pixels cropped, by season (Landsat)", yaxis_title="%",
                              height=320, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig, width="stretch")
            st.caption("Targets are satellite stand-ins (Landsat NDVI), not farm records. "
                       "See docs/ml_training_data.md.")
        else:
            st.info("No ML training table yet: it is the last pipeline step.")
