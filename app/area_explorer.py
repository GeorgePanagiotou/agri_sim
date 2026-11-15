"""Area explorer: choose a prepared area (configs/areas/*.yaml) or draw a new box, see what data it has, its
climate (via the climate API in service/, or the same code in-process when the API is down), and start the
data pipeline for a new area.
"""
from __future__ import annotations

import calendar
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
# Hosted demo (Streamlit Community Cloud runs from /mount/src, or set AGRISIM_HOSTED=1): view prepared areas only;
# no new areas and no data runs (hours of downloads on a small, temporary disk).
HOSTED = os.environ.get("AGRISIM_HOSTED") == "1" or Path.cwd().as_posix().startswith("/mount/src")
HOSTED_NOTE = ("This is the hosted demo: it shows the areas prepared in the repository. To prepare a new area, run "
               "the app on your own computer (see README).")
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
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    login = st.session_state.get("earthdata")
    if login:   # this user's Settings login, only for the run they start (never in os.environ, never on disk)
        env |= {"EARTHDATA_USERNAME": login["user"], "EARTHDATA_PASSWORD": login["password"]}
    with open(log, "a", encoding="utf-8") as fh:
        subprocess.Popen([sys.executable, "-m", "agrisim.pipelines.prepare_area", "--name", name], cwd=REPO,
                         stdout=fh, stderr=subprocess.STDOUT, creationflags=flags, env=env)
    return log


# ---------------------------------------------------------------- settings: NASA Earthdata login
URS = "https://urs.earthdata.nasa.gov"
STEP_TIMES = ("Typical run times on a home connection (Messara, 0.2° × 0.1°): Landsat history 1997–2025 2–4 h · "
              "soil 0.5–1 h · IMERG 0.5 h · IMERG Late calibration 15 min · terrain, POWER, engines, ML tables "
              "and models a few minutes each.")


def _netrc_present() -> bool:
    """Only checks that the file exists; its content is never read here."""
    return any((Path.home() / f).exists() for f in ("_netrc", ".netrc"))


def _check_login(user: str, password: str) -> bool:
    try:
        import ssl

        import truststore
        verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        verify = True
    r = httpx.get(f"{URS}/api/users/tokens", auth=(user, password), timeout=30, verify=verify)
    return r.status_code == 200


def settings_panel():
    with st.sidebar.expander("Settings · NASA Earthdata login", expanded=False):
        login = st.session_state.get("earthdata")
        if login:
            st.success(f"Signed in as {login['user']} (this browser session only).")
            if st.button("Sign out"):
                st.session_state.pop("earthdata", None)
                st.rerun()
        else:
            st.caption("Needed to download IMERG rainfall and NASADEM terrain for a new area. Free account: "
                       f"[{URS}/users/new]({URS}/users/new). Kept in this session only; passed to the data run "
                       "you start, never saved.")
            with st.form("earthdata_login", clear_on_submit=True):
                user = st.text_input("Username")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Sign in") and user and password:
                    try:
                        ok = _check_login(user, password)
                    except httpx.HTTPError:
                        st.error("Could not reach urs.earthdata.nasa.gov.")
                    else:
                        if ok:
                            st.session_state["earthdata"] = {"user": user, "password": password}
                            st.rerun()
                        st.error("Earthdata rejected this username / password.")
        st.caption("Server login file (~/.netrc): " + ("found" if _netrc_present() else "none"))


@st.cache_data(ttl=86400, show_spinner=False)
def area_fit(name: str) -> dict | None:
    from agrisim.features import area_fit as af
    try:
        return af.assess(load(name))
    except Exception:  # noqa: BLE001 - POWER unreachable etc.: fall back to the simple box check
        return None


def climate_zone_warning(area):
    fit = area_fit(area.name)
    if fit:
        msg = f"**Climate {fit['koppen']} – {fit['name']}.** {fit['explanation']}"
        {"calibrated": st.success, "partly": st.warning}.get(fit["fit"], st.error)(msg)
        return
    lon, lat = area.pilot
    if not (30 <= lat <= 46 and -10 <= lon <= 42):
        st.warning("This area is outside the Mediterranean belt the rules were built for. Crop list, sowing "
                   "windows (Oct–Dec), the Oct–Sep season and the field-map thresholds come from Greece"
                   + (" and the Northern Hemisphere" if lat < 0 else "") + ": treat the sowing, risk and "
                   "crop/fallow results here as untested. The climate data and satellite history are fine.")


def fit_tab(area):
    fit = area_fit(area.name)
    if not fit:
        st.info("Climate normals unavailable (NASA POWER not reachable).")
        return
    n = fit["normals"]
    months = list(calendar.month_abbr[1:])
    a, b = st.columns(2)
    rain = go.Figure(go.Bar(x=months, y=n["precip_mm"], marker_color=COLORS["imerg"], name="precipitation"))
    rain.update_layout(title="Monthly precipitation normal", yaxis_title="mm", height=280,
                       margin=dict(l=10, r=10, t=45, b=10))
    temp = go.Figure(go.Scatter(x=months, y=n["temp_c"], mode="lines+markers", name="temperature",
                                line=dict(color=COLORS["power"], width=2), marker=dict(size=8)))
    temp.update_layout(title="Monthly mean temperature normal", yaxis_title="°C", height=280,
                       margin=dict(l=10, r=10, t=45, b=10))
    a.plotly_chart(rain, width="stretch")
    b.plotly_chart(temp, width="stretch")
    st.caption(f"{n['source']}; {n['period']}. Köppen–Geiger rules of Beck et al. (2018). "
               f"{fit['winter_rain_share']:.0%} of the rain falls in the cool half-year.")
    g = fit["gaez"]
    if g:
        crops = sorted(g, key=lambda c: g[c]["pilot"] or -1)
        bars = go.Figure(go.Bar(y=crops, x=[(g[c]["pilot"] or 0) / 100 for c in crops], orientation="h",
                                marker_color="#16A34A", text=[f"{(g[c]['pilot'] or 0) / 100:.0f}" for c in crops],
                                textposition="outside",
                                hovertext=[f"best cell in the box: {(g[c]['box_max'] or 0) / 100:.0f}" for c in crops]))
        bars.update_layout(title="Crop suitability at the pilot point (FAO GAEZ v4, rainfed, low input)",
                           xaxis=dict(title="suitability index (0–100)", range=[0, 110]), height=300,
                           margin=dict(l=10, r=10, t=45, b=10))
        st.plotly_chart(bars, width="stretch")
        st.caption("GAEZ v4 (FAO & IIASA, CC BY 4.0), 1981–2010 climate, 5-arc-minute cells (~9 km): a regional "
                   "screen of which crops the climate and soil allow, not a field recommendation.")


def sowing_risk_tab(area):
    sow_f, risk_f = area.outputs / "sowing_weeks.csv", area.outputs / "risk_daily.csv"
    if not (sow_f.exists() and risk_f.exists()):
        st.info("No sowing / risk results yet: they are the risk and sowing pipeline steps.")
        return
    risk = pd.read_csv(risk_f)
    last = risk.dropna(subset=["overall_label"]).iloc[-1] if "overall_label" in risk else risk.iloc[-1]
    st.markdown(f"**Regional risk on {last['date']}** (past-only indicators, IMERG + POWER)")
    labels = [c for c in risk.columns if c.endswith("_label") and c != "overall_label"]
    cols = st.columns(len(labels) + 1)
    cols[0].metric("Overall", str(last.get("overall_label", "")).replace("_", " "))
    for col, c in zip(cols[1:], labels):
        col.metric(c.removesuffix("_label").replace("_", " ").capitalize(), str(last[c]).replace("_", " "))
    sow = pd.read_csv(sow_f)
    season = sorted(sow.season.unique())[-1]
    s = sow[sow.season.eq(season)]
    st.markdown(f"**Sowing screen, season {season}** – weekly verdicts per crop (regional; the farmer decides)")
    grid = s.pivot_table(index="week_start", columns="crop_id", values="verdict", aggfunc="first")
    st.dataframe(grid.fillna("").replace({"check_worthy": "✓ check-worthy", "too_dry": "too dry",
                                          "too_wet": "too wet", "too_cold": "too cold"}), width="stretch")
    st.caption("check-worthy = worth walking the field; too dry / too wet / too cold = the rule that blocked it; "
               "unknown = an input is missing (e.g. weeks still ahead).")


def ml_dir(area) -> Path:
    if area.name == "evia" and (REPO / "artifacts" / "satellite_proxy_models" / "1114").exists():
        return REPO / "artifacts" / "satellite_proxy_models"   # Stylianos's committed Evia models
    return area.data_root / "processed" / "ml" / "models"


def ml_tab(area):
    base = ml_dir(area)
    if not (base / "1114" / "run_manifest.json").exists():
        st.info("No models for this area yet: they are the last pipeline step (ml_models).")
        return
    import json
    rows = []
    for d, label in (("1114", "14 Nov (now)"), ("0301", "1 Mar")):
        for task, key, better in (("vigour", "rmse", "lower"), ("crop", "roc_auc", "higher")):
            f = base / d / f"{task}_forward_metrics.json"
            if f.exists():
                m = json.loads(f.read_text(encoding="utf-8"))
                rows.append({"decision date": label, "target": "spring vigour (RMSE)" if task == "vigour"
                             else "crop vs fallow (AUC)", "model": round(m["model_on_baseline_rows"][key], 3),
                             "5-year baseline": round(m["historical_baseline"][key], 3), "better is": better})
    st.markdown("**Forward test on unseen seasons (trained before 2018, tested 2018+)**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("On 14 Nov the model is no better than each field's own 5-year history; skill comes from winter "
               "satellite greenness (1 Feb – 1 Apr). Targets are Landsat NDVI stand-ins, not farm records.")
    live = base / "1114" / "crop_live_2027.csv.gz"
    if live.exists():
        p = pd.read_csv(live)
        col = "pred_crop_probability_uncalibrated"
        p["rgb"] = [[int(255 * (1 - v)), int(160 * v + 60), 60, 200] for v in p[col].clip(0, 1)]
        p["tip"] = (p[col] * 100).round().astype(int).astype(str) + " % likely cropped"
        st.markdown("**Season 2027 outlook: probability each 30 m field pixel is cropped (uncalibrated)**")
        st.pydeck_chart(pdk.Deck(
            layers=[pdk.Layer("ScatterplotLayer", p, get_position=["lon", "lat"], get_fill_color="rgb",
                              get_radius=20, pickable=True)],
            initial_view_state=pdk.ViewState(longitude=float(p.lon.mean()), latitude=float(p.lat.mean()), zoom=10),
            tooltip={"text": "{tip}"}, map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"))
        st.caption(f"{len(p):,} rainfed field pixels · mean {p[col].mean():.0%} · green = likely cropped, "
                   "red = likely fallow. Uncalibrated: read as a ranking, not a probability.")


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
    if HOSTED:
        st.info(HOSTED_NOTE)
        st.code("python -m agrisim.pipelines.prepare_area --name <name> --bbox W E S N", language="powershell")
        return
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
    settings_panel()
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
    climate_zone_warning(area)

    overview, fit_tab_, climate_tab, sow_tab, data_tab, ml_tab_ = st.tabs(
        ["Data status", "Climate & crop fit", "Recent climate", "Sowing & risk", "ML training data",
         "Field outlook (ML)"])
    with fit_tab_:
        fit_tab(area)
    with sow_tab:
        sowing_risk_tab(area)
    with ml_tab_:
        ml_tab(area)
    with overview:
        table = status_table(choice)
        done = (table.status == "done").sum()
        st.metric("Pipeline steps done", f"{done} / {len(table)}")
        st.dataframe(table, hide_index=True, width="stretch")
        live = pa.running(area)
        if live:
            st.info(f"Data preparation is running (since {live['started']}, process {live['pid']}). "
                    "Press Refresh to update the step status.")
        if done < len(table) and HOSTED:
            st.info(HOSTED_NOTE + " Steps marked 'to do' here use large files that stay out of git (e.g. the "
                                  "130 MB Landsat cube); their results are committed.")
        elif done < len(table):
            st.warning("Preparing an area downloads ~30 years of satellite data and takes a few hours "
                       "(it runs in the background; finished steps are kept, so it can stop and resume). "
                       + STEP_TIMES)
            if not (st.session_state.get("earthdata") or _netrc_present()):
                st.warning("IMERG and NASADEM need a NASA Earthdata login: sign in under Settings in the sidebar "
                           "first, or those steps will stop.")
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
