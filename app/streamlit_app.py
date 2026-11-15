"""AgriSim AI | Application & Outputs demonstration.

Start: uv run --extra app streamlit run app/streamlit_app.py
Rebuilt Evia assessments and an optional synthetic demonstration.
"""
from __future__ import annotations

import html
import re
from datetime import date

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="AgriSim AI | Application & Outputs",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

from evia_results import render as render_evia
from area_explorer import render as render_areas

_page = st.sidebar.radio("Data source", ["Rebuilt Evia results", "Area explorer"])
if _page == "Area explorer":
    render_areas()
else:
    render_evia()
# The synthetic mock-up below (demo_data.py) is no longer in the menu (2026-11-15): both pages above use real data.
# Its code is kept for reference; it never runs because of this stop.
st.stop()

import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk

from demo_data import (
    FIELDS, SEASONS, CROPS, CROP_RULES,
    make_environment, rank_sowing_windows, rank_rotations,
    report_markdown, risk_level, risk_scores,
)

# Streamlit's native theme settings cannot currently be switched from Python.
# The sidebar toggle applies a high-contrast CSS palette to all app-owned
# cards and messages, and updates Plotly figures. The bundled config.toml defines native light/dark choices too.
PALETTES = {
    "light": {
        "page": "#FAFCFA", "sidebar": "#ECF5EE", "surface": "#FFFFFF",
        "input": "#FFFFFF", "text": "#19372D", "muted": "#5E7368",
        "border": "#D5E5DB", "accent": "#147B58", "accent_soft": "#E8F5EC",
        "chart_bg": "#FFFFFF", "chart_grid": "#E5EEE8", "template": "plotly_white",
        "notice_info_bg": "#E7F2FC", "notice_info_border": "#8DBADB", "notice_info_text": "#163B54",
        "notice_success_bg": "#E4F5E9", "notice_success_border": "#86C89F", "notice_success_text": "#17492D",
        "notice_warning_bg": "#FFF2D8", "notice_warning_border": "#DEAC58", "notice_warning_text": "#573907",
        "notice_error_bg": "#FCE8EA", "notice_error_border": "#D9949D", "notice_error_text": "#651E2C",
        "selection_bg": "#147B58", "selection_text": "#FFFFFF",
    },
    "dark": {
        "page": "#0B1512", "sidebar": "#102219", "surface": "#192F25",
        "input": "#233D30", "text": "#F0F9F3", "muted": "#C0D3C6",
        "border": "#344F40", "accent": "#56D6A4", "accent_soft": "#19382A",
        "chart_bg": "#192F25", "chart_grid": "#42604F", "template": "plotly_dark",
        "notice_info_bg": "#1A3445", "notice_info_border": "#5688B2", "notice_info_text": "#E5F3FF",
        "notice_success_bg": "#183F2F", "notice_success_border": "#38946C", "notice_success_text": "#D8FFE9",
        "notice_warning_bg": "#423218", "notice_warning_border": "#B98A3D", "notice_warning_text": "#FFF0C5",
        "notice_error_bg": "#48262D", "notice_error_border": "#BF6573", "notice_error_text": "#FFE8EB",
        "selection_bg": "#367F66", "selection_text": "#FFFFFF",
    },
}


def apply_app_theme(is_dark: bool) -> None:
    """Apply the session's visual palette without touching other users' settings."""
    c = PALETTES["dark" if is_dark else "light"]
    st.markdown(f"""
    <style>
      /* Main Streamlit surfaces and typography. */
      html, body, .stApp,
      [data-testid="stAppViewContainer"], [data-testid="stMain"],
      [data-testid="stMainBlockContainer"],
      [data-testid="stHeader"] {{
        background-color: {c['page']} !important;
        color: {c['text']} !important;
      }}
      [data-testid="stSidebar"], [data-testid="stSidebarContent"] {{
        background-color: {c['sidebar']} !important;
        color: {c['text']} !important;
      }}
      [data-testid="stMarkdownContainer"] h1,
      [data-testid="stMarkdownContainer"] h2,
      [data-testid="stMarkdownContainer"] h3,
      [data-testid="stMarkdownContainer"] h4,
      [data-testid="stMarkdownContainer"] p,
      [data-testid="stWidgetLabel"] p,
      [data-testid="stCaptionContainer"] p,
      label {{ color: {c['text']} !important; }}
      [data-testid="stCaptionContainer"],
      [data-testid="stCaptionContainer"] p {{ color: {c['muted']} !important; }}
      .block-container {{ max-width: 1500px; padding-top: 1.5rem; padding-bottom: 3rem; }}
      h1, h2, h3 {{ letter-spacing: -.025em; }}
      div[data-testid="stMetric"] {{
        background: {c['surface']} !important;
        border: 1px solid {c['border']} !important;
        padding: 12px 15px;
        border-radius: 11px;
      }}
      [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {{ color: {c['text']} !important; }}
      [data-testid="stMetricLabel"] p {{ color: {c['muted']} !important; }}
      div[data-baseweb="select"] > div,
      div[data-baseweb="input"] > div,
      [data-testid="stDateInput"] input,
      [data-testid="stNumberInput"] input,
      div[data-baseweb="popover"] > div,
      ul[role="listbox"] {{
        background-color: {c['input']} !important;
        color: {c['text']} !important;
        border-color: {c['border']} !important;
      }}
      div[data-baseweb="select"] input,
      div[data-baseweb="select"] span,
      [data-testid="stDateInput"] input {{ color: {c['text']} !important; }}
      [data-testid="stExpander"] {{
        background: {c['surface']} !important;
        border: 1px solid {c['border']} !important;
        border-radius: 9px;
      }}
      [data-testid="stTabs"] [role="tablist"] {{ border-bottom-color: {c['border']} !important; }}
      [data-testid="stTabs"] button[role="tab"] {{ color: {c['muted']} !important; }}
      [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
        color: {c['accent']} !important;
        border-bottom-color: {c['accent']} !important;
      }}
      [data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background-color: {c['accent']} !important; }}
      hr {{ border-color: {c['border']} !important; }}
      .hero {{
        border-radius: 16px;
        background: linear-gradient(105deg, #0d3c35, #176048 62%, #21714c);
        color: #ffffff !important; padding: 25px 28px; margin-bottom: 14px;
      }}
      .hero h1 {{ margin: 0 0 5px 0; color: #ffffff !important; font-size: 2.05rem; }}
      .hero p {{ margin: 0; color: #d8f5e6 !important; }}
      .eyebrow {{ font-size: 0.74rem; letter-spacing: .15em; text-transform: uppercase; opacity: .8; margin-bottom: 6px; }}
      .section-caption {{ color: {c['muted']}; font-size: .9rem; }}
      .agri-summary-card {{
        background: {c['surface']}; border: 1px solid {c['border']};
        border-radius: 12px; padding: 16px 18px; margin-bottom: 9px;
        min-height: 103px;
      }}
      .agri-summary-title {{ font-size: .81rem; color: {c['muted']} !important;
        font-weight: 650; margin-bottom: 9px; letter-spacing: .02em; }}
      .agri-summary-main {{ color: {c['text']} !important;
        font-size: 1.07rem; font-weight: 700; line-height: 1.35; }}
      .agri-summary-extra {{ color: {c['muted']} !important;
        font-size: .81rem; margin-top: 7px; line-height: 1.35; }}
      .agri-tight-heading {{ margin-top: 12px; }}
      /* Selection remains readable in both palettes. */
      ::selection {{ background: {c['selection_bg']} !important; color: {c['selection_text']} !important; }}
      [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] {{ color: {c['text']} !important; }}
      /* Explicit contrast for our own notices, independent of Streamlit's global theme. */
      .agri-notice {{
        padding: 14px 17px; border-radius: 10px; margin: 10px 0 15px;
        border: 1px solid transparent; font-size: .95rem;
        line-height: 1.55; overflow-wrap: anywhere;
      }}
      .agri-notice strong {{ font-weight: 700; color: inherit !important; }}
      .agri-break {{ display: block; margin-bottom: .45rem; }}
      .agri-notice-info {{ background: {c['notice_info_bg']} !important; border-color: {c['notice_info_border']} !important; color: {c['notice_info_text']} !important; }}
      .agri-notice-success {{ background: {c['notice_success_bg']} !important; border-color: {c['notice_success_border']} !important; color: {c['notice_success_text']} !important; }}
      .agri-notice-warning {{ background: {c['notice_warning_bg']} !important; border-color: {c['notice_warning_border']} !important; color: {c['notice_warning_text']} !important; }}
      .agri-notice-error {{ background: {c['notice_error_bg']} !important; border-color: {c['notice_error_border']} !important; color: {c['notice_error_text']} !important; }}
      /* Fallback for Streamlit-generated alert boxes, if one is added later. */
      [data-testid="stAlert"], [data-baseweb="notification"] {{
        background: {c['notice_info_bg']} !important;
        color: {c['notice_info_text']} !important;
        border: 1px solid {c['notice_info_border']} !important;
        border-radius: 10px !important;
      }}
      [data-testid="stAlert"] *, [data-baseweb="notification"] * {{ color: {c['notice_info_text']} !important; }}
      /* Inputs, dropdowns, and buttons have matching foreground + background. */
      [data-testid="stSidebar"] [data-baseweb="select"] > div,
      [data-testid="stSidebar"] [data-baseweb="input"] > div,
      [data-testid="stSidebar"] [data-testid="stDateInput"] input,
      [data-testid="stSidebar"] [data-baseweb="slider"] {{
        background-color: {c['input']} !important;
        color: {c['text']} !important;
        border-color: {c['border']} !important;
      }}
      [data-baseweb="popover"],
      [data-baseweb="popover"] [role="listbox"],
      [data-baseweb="popover"] li {{ background: {c['input']} !important; color: {c['text']} !important; }}
      [data-baseweb="popover"] li:hover, [data-baseweb="popover"] li[aria-selected="true"] {{ background: {c['accent_soft']} !important; color: {c['text']} !important; }}
      [data-testid="stSelectbox"] [data-baseweb="select"] *,
      [data-testid="stDateInput"] input,
      [data-testid="stNumberInput"] input {{ color: {c['text']} !important; }}
      [data-testid="stDownloadButton"] button,
      [data-testid="stBaseButton-secondary"] {{
        background: {c['surface']} !important; color: {c['text']} !important;
        border: 1px solid {c['border']} !important;
      }}
      [data-testid="stDownloadButton"] button *,
      [data-testid="stBaseButton-secondary"] * {{ color: {c['text']} !important; }}
      /* Theme the JSON box and progress labels without affecting chart internals. */
      [data-testid="stJson"], [data-testid="stJson"] > div {{ background: {c['surface']} !important; color: {c['text']} !important; }}
      [data-testid="stProgress"] [data-testid="stMarkdownContainer"] p {{ color: {c['text']} !important; }}

    </style>
    """, unsafe_allow_html=True)


def notice(message: str, kind: str = "info") -> None:
    """A theme-aware, high-contrast status box. Escapes arbitrary message text."""
    if kind not in {"info", "warning", "success", "error"}:
        raise ValueError(f"Unknown notice kind: {kind}")
    safe = html.escape(message)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = safe.replace("\n\n", "<span class=\"agri-break\"></span>").replace("\n", " ")
    role = "alert" if kind in {"warning", "error"} else "status"
    st.markdown(f'<div class="agri-notice agri-notice-{kind}" role="{role}">{safe}</div>', unsafe_allow_html=True)


def summary_card(title: str, value: str, details: str = "") -> None:
    """Small, theme-aware overview card. Escapes user-controlled display text."""
    title_safe = html.escape(str(title))
    value_safe = html.escape(str(value))
    extra_safe = html.escape(str(details))
    extra = f'<div class="agri-summary-extra">{extra_safe}</div>' if details else ""
    st.markdown(
        '<div class="agri-summary-card">'
        f'<div class="agri-summary-title">{title_safe}</div>'
        f'<div class="agri-summary-main">{value_safe}</div>{extra}'
        '</div>',
        unsafe_allow_html=True,
    )


def style_chart(fig: go.Figure) -> go.Figure:
    """Match Plotly backgrounds, fonts, and grids to the sidebar toggle."""
    c = PALETTES["dark" if st.session_state.dark_mode else "light"]
    fig.update_layout(
        template=c["template"],
        paper_bgcolor=c["chart_bg"],
        plot_bgcolor=c["chart_bg"],
        font={"color": c["text"]},
        xaxis={"gridcolor": c["chart_grid"], "zerolinecolor": c["border"]},
        yaxis={"gridcolor": c["chart_grid"], "zerolinecolor": c["border"]},
        legend={"bgcolor": "rgba(0,0,0,0)"},
    )
    return fig


@st.cache_data(show_spinner=False)
def load_demo_environment(field: str, season: str) -> pd.DataFrame:
    return make_environment(field, season)


@st.cache_data(show_spinner=False)
def load_demo_history(field: str) -> pd.DataFrame:
    return pd.concat([make_environment(field, s) for s in SEASONS], ignore_index=True)


def datestr(d: date) -> str:
    return pd.Timestamp(d).strftime("%d %b %Y")


def line_chart(df: pd.DataFrame, x: str, y: str, title: str = "", color: str = "#138463") -> go.Figure:
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=df[x], y=df[y], mode="lines", line={"color": color, "width": 2.5},
        name=y.replace("_", " ").title(), connectgaps=False,
    ))
    figure.update_layout(title=title, height=315, margin=dict(t=50, r=12, b=20, l=10),
                         hovermode="x unified", xaxis_title=None, yaxis_title=None,
                         template="plotly_white")
    return style_chart(figure)


def map_points(selected_field: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "site": name, "latitude": f["lat"], "longitude": f["lon"],
        "marker_color": "#08a269" if name == selected_field else "#76998b", "marker_size": 115 if name == selected_field else 75,
    } for name, f in FIELDS.items()])


def display_demo_map(selected_field: str, zoom: int = 11) -> None:
    """Map tiles switch with the in-app theme; points remain synthetic."""
    points = map_points(selected_field)
    points["rgba"] = [
        [46, 209, 151, 240] if site == selected_field else [134, 173, 155, 220]
        for site in points["site"]
    ]
    dark = st.session_state.dark_mode
    map_style = (
        "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
        if dark else
        "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
    )
    view = pdk.ViewState(
        latitude=FIELDS[selected_field]["lat"],
        longitude=FIELDS[selected_field]["lon"],
        zoom=zoom,
        pitch=0,
    )
    layer = pdk.Layer(
        "ScatterplotLayer", data=points,
        get_position="[longitude, latitude]",
        get_fill_color="rgba",
        get_radius="marker_size",
        radius_min_pixels=5,
        radius_max_pixels=17,
        pickable=True,
    )
    st.pydeck_chart(
        pdk.Deck(map_style=map_style, initial_view_state=view,
                 layers=[layer], tooltip={"text": "{site} (synthetic demo point)"}),
        width="stretch",
    )


if "dark_mode" not in st.session_state:
    # Respect the native browser/Streamlit preference on first load where available.
    try:
        st.session_state.dark_mode = st.context.theme.type == "dark"
    except (AttributeError, TypeError, KeyError):
        st.session_state.dark_mode = False

with st.sidebar:
    st.markdown("## 🌱 AgriSim AI")
    st.toggle("🌙 Dark mode", key="dark_mode", help="Switch this dashboard's colors and charts")
    st.caption("APPLICATION & OUTPUTS · PROTOTYPE")
    notice("SYNTHETIC DEMO DATA\n\nAll locations, measurements, risk scores and recommendations on this screen are illustrative.", kind="warning")
    site = st.selectbox("Demo study area", list(FIELDS), index=0)
    season = st.selectbox("Growing season", SEASONS, index=1)
    crop = st.selectbox("Crop scenario", CROPS, index=0)
    st.markdown("#### Assessment settings")

    frame = load_demo_environment(site, season)
    default_day = pd.Timestamp(f"{int(season[:4]) + 1}-03-15").date()
    assessment_date = st.date_input(
        "Assessment date",
        value=default_day,
        min_value=frame["date"].min().date(),
        max_value=frame["date"].max().date(),
        format="DD/MM/YYYY",
        key=f"assessment_{season}",
    )
    if assessment_date is None:
        assessment_date = default_day
    previous_crop = st.selectbox("Previously grown crop", CROPS, index=0)
    with st.expander("Rotation scoring weights", expanded=False):
        suitability_w = st.slider("Regional suitability", 0, 10, 5)
        water_w = st.slider("Water efficiency", 0, 10, 3)
        diversity_w = st.slider("Crop-family diversity", 0, 10, 5)
        if suitability_w + water_w + diversity_w == 0:
            notice("At least one weight must be positive; using suitability as a fallback.", kind="info")
            suitability_w = 1
    st.divider()
    st.caption("The demo contains no real-time weather feed or validated trained model. App outputs must be independently evaluated before agricultural use.")

apply_app_theme(st.session_state.dark_mode)

weights = {"Suitability": suitability_w, "Water efficiency": water_w, "Diversity": diversity_w}
assessed = frame.loc[frame["date"].dt.date == assessment_date].iloc[0]
sowing = rank_sowing_windows(frame, crop)
rotations = rank_rotations(previous_crop, weights)
risk = risk_scores(assessed)
max_risk = max(item["score"] for item in risk.values())
ndvi_valid = frame["ndvi"].notna().sum()

# Global context stays short; the full branding banner belongs only to the Overview.
st.caption("🌱 **AgriSim AI**  /  Application & outputs  ·  SYNTHETIC demonstration")

overview, map_tab, sow_tab, rotation_tab, risk_tab, insights_tab = st.tabs([
    "🏠 Outputs overview", "🗺️ Interactive map", "📅 Sowing recommendation",
    "🌾 Crop rotation plan", "⚠️ Risk & alerts", "📈 Insights & reports",
])

with overview:
    st.markdown("""
    <div class="hero">
        <div class="eyebrow">AgriSim AI / Decision support interface</div>
        <h1>Field intelligence, from Earth observations to decisions</h1>
        <p>Explore a location, compare crop scenarios and review decision-support demonstrations.</p>
    </div>
    """, unsafe_allow_html=True)
    st.caption("🧪 All displayed observations, locations and recommendations are synthetic; no real farm parcel is identified.")
    st.subheader("At a glance")
    st.caption(f"{site} · {season} · {datestr(assessment_date)} · {crop} example")

    # Overview KPIs focus on environmental context, not detailed tab results.
    a, b, c, d = st.columns(4)
    a.metric("Soil moisture · demo", f"{assessed['soil_moisture_m3m3']:.3f} m³/m³")
    b.metric("Rainfall · prior 7d", "N/A" if pd.isna(assessed["rain_prior_7d_mm"]) else f"{assessed['rain_prior_7d_mm']:.1f} mm")
    c.metric("Days in selected season", str(len(frame)))
    d.metric("Clear NDVI observations · demo", str(int(ndvi_valid)))

    st.markdown("#### Selected study area")
    summary_card(
        f"📍 {site}",
        FIELDS[site]["note"],
        f"Approximate demo point: {FIELDS[site]['lat']:.5f}°, {FIELDS[site]['lon']:.5f}° · No field boundary",
    )

    sow_col, rotation_col = st.columns(2, gap="medium")
    with sow_col:
        if sowing.empty:
            summary_card("📅 Example sowing window", "Not available", "See the Sowing recommendation tab")
        else:
            best = sowing.iloc[0]
            summary_card("📅 Example sowing window",
                         f"{datestr(best['window_start'])} – {datestr(best['window_end'])}",
                         f"Illustrative score {best['demo_score']:.0f}/100 · Details in Sowing recommendation")
    with rotation_col:
        top_rotation = rotations.iloc[0]
        summary_card("🌾 Highest-ranked example rotation", top_rotation["rotation"],
                     f"Demo ranking {top_rotation['demo_score']:.0f}/100 · Details in Crop rotation plan")

    top_risk = max(risk, key=lambda name: risk[name]["score"])
    top_score = risk[top_risk]["score"]
    summary_card("⚠️ Highest example risk",
                 f"{top_risk} · {risk_level(top_score)} ({top_score:.0f}/100)",
                 "Synthetic indicator, not a calibrated probability · Details in Risk & alerts")
    st.caption("For detailed maps, candidate-window comparisons and historical charts, use the dedicated tabs above.")

with map_tab:
    st.subheader("Interactive map & local conditions")
    st.caption("Synthetic study points only. The map does not show surveyed parcel boundaries or live environmental conditions.")
    c1, c2 = st.columns([1.7, 1], gap="large")
    with c1:
        display_demo_map(site, zoom=12)
    with c2:
        st.markdown(f"#### {site}")
        st.caption(FIELDS[site]["note"])
        st.caption(f"Location: {FIELDS[site]['lat']:.5f}° N, {FIELDS[site]['lon']:.5f}° E")
        st.markdown(f"**Conditions on {datestr(assessment_date)}**")
        st.metric("Air temperature · demo", f"{assessed['air_temp_c']:.1f} °C")
        st.metric("Soil temperature · demo", f"{assessed['soil_temp_c']:.1f} °C")
        st.metric("Surface soil moisture · demo", f"{assessed['soil_moisture_m3m3']:.3f} m³/m³")

    # A short, location-specific trace is useful on a map; full historical
    # comparisons belong exclusively in Insights & reports.
    with st.expander("Inspect recent conditions at this demo point", expanded=False):
        metric_labels = {
            "Soil moisture": ("soil_moisture_m3m3", "#168c6a"),
            "Air temperature": ("air_temp_c", "#dda33b"),
            "Daily precipitation": ("rain_mm", "#458bd7"),
        }
        metric_name = st.selectbox("Local variable", list(metric_labels), key="map_metric")
        metric, color = metric_labels[metric_name]
        cutoff = pd.Timestamp(assessment_date)
        local = frame.loc[frame["date"].between(cutoff - pd.Timedelta(days=29), cutoff)].copy()
        st.plotly_chart(line_chart(local, "date", metric, f"30-day demo context · {metric_name}", color),
                        width="stretch", theme=None)
        st.caption("Short-term local context only; see Insights & reports for full-season analysis.")
    with st.expander("Selected-day feature values", expanded=False):
        st.json({key: (None if pd.isna(value) else float(value)) for key, value in {
            "air_temp_c": assessed["air_temp_c"],
            "soil_temp_c": assessed["soil_temp_c"],
            "soil_moisture_m3m3": assessed["soil_moisture_m3m3"],
            "rain_prior_7d_mm": assessed["rain_prior_7d_mm"],
        }.items()})

with sow_tab:
    st.subheader("Sowing recommendation")
    st.caption("Retrospective candidate windows for a synthetic season. These are not forecasts or agricultural advice.")
    if sowing.empty:
        notice("No candidate weeks are available for this example crop and season.", kind="info")
    else:
        best = sowing.iloc[0]
        k1, k2, k3 = st.columns(3)
        k1.metric("Illustrative start", datestr(best["window_start"]))
        k2.metric("Illustrative end", datestr(best["window_end"]))
        k3.metric("Demo suitability score", f"{best['demo_score']:.1f}/100")
        notice("This score is **not** a calibrated probability of sowing success. Dates and agronomic ranges are illustrative.", kind="warning")

        st.markdown("#### Compare candidate windows")
        timeline = sowing.head(9).copy()
        timeline["period"] = timeline["window_start"].map(datestr)
        fig = px.timeline(
            timeline,
            x_start="window_start", x_end="window_end", y="period",
            color="demo_score", color_continuous_scale=["#8bcfb3", "#11805c"],
            hover_data={"demo_score": True, "soil_temp_c": True, "rain_prior_7d_mm": True},
            labels={"period": "Example start", "demo_score": "Demo score"},
        )
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=20),
                          xaxis_title="Illustrative sowing dates", yaxis_title=None,
                          coloraxis_colorbar=dict(title="Score"))
        st.plotly_chart(style_chart(fig), width="stretch", theme=None)
        with st.expander("View ranked window measurements", expanded=False):
            st.dataframe(sowing.head(12).rename(columns={
                "window_start": "Start", "window_end": "End", "demo_score": "Demo score / 100",
                "demo_confidence_proxy": "Mock consistency / 100",
                "soil_temp_c": "Soil °C", "soil_moisture_m3m3": "Soil moisture", "rain_prior_7d_mm": "Prior rain (mm)"
            }), hide_index=True, width="stretch")
        with st.expander("Why is the first candidate ranked highest?", expanded=False):
            st.markdown(f"""
            The example scoring rule uses conditions **before** the candidate start date:

            - Mean soil temperature over 7 prior days: **{best['soil_temp_c']} °C** (demo range {CROP_RULES[crop]['temp'][0]}–{CROP_RULES[crop]['temp'][1]} °C)
            - Mean soil moisture over 7 prior days: **{best['soil_moisture_m3m3']:.3f} m³/m³** (demo range {CROP_RULES[crop]['moist'][0]}–{CROP_RULES[crop]['moist'][1]} m³/m³)
            - Rainfall during 7 prior days: **{best['rain_prior_7d_mm']:.1f} mm**

            The mock consistency proxy ({best['demo_confidence_proxy']:.0f}/100) is **not model confidence**.
            The rules do not predict upcoming weather or crop outcomes.
            """)

with rotation_tab:
    st.subheader("Crop rotation plan")
    st.caption(f"Previous example crop: **{previous_crop}**. This is a synthetic weighted ranking, not a prediction of yield or soil improvement.")
    top = rotations.head(8).copy()
    chart = px.bar(top.iloc[::-1], x="demo_score", y="rotation", orientation="h",
                   color_discrete_sequence=["#2c9671"],
                   labels={"demo_score": "Illustrative weighted score", "rotation": "Three-crop sequence"})
    chart.update_layout(title="Compare example crop rotations", height=360, margin=dict(l=20, r=10, t=50, b=20))
    st.plotly_chart(style_chart(chart), width="stretch", theme=None)

    chosen_rotation = st.selectbox("Inspect a proposed sequence", top["rotation"].tolist(), key="inspect_rotation")
    selected_rotation = top.loc[top["rotation"] == chosen_rotation].iloc[0]
    st.markdown(f"**Selected rotation:** {chosen_rotation} · illustrative score {selected_rotation['demo_score']:.1f}/100")
    c1, c2, c3 = st.columns(3)
    c1.metric("Potential yield-fit proxy", f"{selected_rotation['yield_fit_proxy']:.0f}/100")
    c2.metric("Water-efficiency proxy", f"{selected_rotation['water_efficiency']:.0f}/100")
    c3.metric("Soil-health proxy", f"{selected_rotation['soil_health_proxy']:.0f}/100")
    st.caption("Constructed scenario indices only, not predicted yields, water savings or measured soil-health improvements.")
    st.markdown(f"**Why this sequence?** {selected_rotation['family_switches']} crop-family transitions relative to the previous crop; "
                f"legume included: {'yes' if selected_rotation['includes_legume'] else 'no'}. "
                "Ranking depends on the sidebar scoring weights.")
    with st.expander("View detailed ranking table", expanded=False):
        st.dataframe(top[["rotation", "demo_score", "suitability", "water_efficiency", "family_switches", "includes_legume"]],
                     hide_index=True, width="stretch")
    notice("Actual rotation advice requires field-level crop history, soil constraints, pest/disease knowledge and agronomic validation.", kind="info")

with risk_tab:
    st.subheader("Risk & alerts")
    st.caption(f"Illustrative environmental risk indicators for {datestr(assessment_date)}. Scores are not calibrated event probabilities.")
    cols = st.columns(4)
    for col, (name, detail) in zip(cols, risk.items()):
        # Each risk is displayed once: severity, score and explanation in one card.
        with col:
            summary_card(f"{name} · {risk_level(detail['score'])}",
                         f"{detail['score']:.0f}/100", detail["driver"])

    st.markdown("#### Explore the evidence for one risk")
    selected_risk = st.selectbox("Risk indicator", list(risk), key="risk_focus")
    risk_series = {
        "Drought": ("rain_prior_14d_mm", "Prior 14-day rainfall", "#d49e31"),
        "Low moisture": ("soil_moisture_m3m3", "Surface soil moisture", "#168e6b"),
        "Heat": ("air_temp_c", "Air temperature", "#d87645"),
        "Excess water": ("rain_prior_7d_mm", "Prior 7-day rainfall", "#458bd7"),
    }
    column, label, color = risk_series[selected_risk]
    st.plotly_chart(line_chart(frame, "date", column, f"{label} · synthetic seasonal history", color),
                    width="stretch", theme=None)
    notice(f"**{selected_risk} — {risk_level(risk[selected_risk]['score'])}:** {risk[selected_risk]['driver']}.", kind="info")
    st.caption("Missing rainfall is not zero rainfall. This prototype has no predictive risk model.")

with insights_tab:
    st.subheader("Insights & reports")
    st.caption("Historical comparisons, synthetic indicators and exportable evidence; this is the home for detailed season-level analytics.")
    history = load_demo_history(site)
    good = history.dropna(subset=["ndvi"]).copy()
    st.markdown("#### Vegetation across growing seasons")
    comparison = px.line(good, x="season_day", y="ndvi", color="season", markers=True,
                         title="Synthetic NDVI · season-to-season comparison",
                         labels={"season_day": "Day in growing season", "ndvi": "NDVI"})
    comparison.update_layout(height=375, margin=dict(l=12, r=12, t=55, b=20),
                             legend=dict(orientation="h", y=-0.27))
    st.plotly_chart(style_chart(comparison), width="stretch", theme=None)

    # This view compares season-level summaries rather than repeating the
    # local daily trend already shown in the Map or Risk tabs.
    seasonal = history.groupby("season", as_index=False).agg(
        rainfall_mm=("rain_mm", "sum"),
        mean_air_temp_c=("air_temp_c", "mean"),
        ndvi_observations=("ndvi", "count"),
    )
    left, right = st.columns(2)
    with left:
        rainfall_chart = px.bar(seasonal, x="season", y="rainfall_mm",
                                title="Seasonal precipitation comparison",
                                labels={"rainfall_mm": "Synthetic rainfall (mm)", "season": "Growing season"},
                                color_discrete_sequence=["#d69f32"])
        rainfall_chart.update_layout(height=305, margin=dict(l=8, r=8, t=55, b=20))
        st.plotly_chart(style_chart(rainfall_chart), width="stretch", theme=None)
    with right:
        temp_chart = px.line(seasonal, x="season", y="mean_air_temp_c", markers=True,
                             title="Mean air temperature by season",
                             labels={"mean_air_temp_c": "Synthetic temperature (°C)", "season": "Growing season"})
        temp_chart.update_layout(height=305, margin=dict(l=8, r=8, t=55, b=20))
        st.plotly_chart(style_chart(temp_chart), width="stretch", theme=None)

    with st.expander("Illustrative explanatory weights · not model feature importance", expanded=False):
        driver_frame = pd.DataFrame([
            {"driver": name, "illustrative_weight": weight}
            for name, weight in [
                ("Surface soil moisture", 0.31), ("Recent precipitation", 0.28),
                ("Soil temperature", 0.21), ("Regional crop suitability", 0.12),
                ("Crop-family diversity", 0.08),
            ]
        ])
        driver_chart = px.bar(driver_frame, x="illustrative_weight", y="driver", orientation="h",
                              title="Hand-set weights — not SHAP or learned importance",
                              color_discrete_sequence=["#138466"])
        driver_chart.update_layout(height=270, margin=dict(l=10, r=10, t=50, b=20),
                                   yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(style_chart(driver_chart), width="stretch", theme=None)

    st.markdown("#### Export evidence")
    if sowing.empty:
        notice("No candidate sowing window is available; the demonstration report cannot be generated.", kind="info")
    else:
        report = report_markdown(site, season, crop, assessment_date, frame, sowing.iloc[0], risk, rotations)
        export1, export2 = st.columns(2)
        with export1:
            st.download_button("⬇ Download selected season CSV", data=frame.to_csv(index=False).encode("utf-8"),
                               file_name=f"agrisim_demo_{FIELDS[site]['id']}_{season}.csv",
                               mime="text/csv", width="stretch")
        with export2:
            st.download_button("⬇ Download Markdown assessment", data=report.encode("utf-8"),
                               file_name=f"agrisim_demo_report_{FIELDS[site]['id']}.md",
                               mime="text/markdown", width="stretch")
        with st.expander("Preview generated report", expanded=False):
            st.markdown(report)

st.divider()
st.caption("AgriSim AI · Application & Outputs proof of concept · All content is SYNTHETIC. The real AgriSim processing system, field boundaries and trained decision models are not connected to this demo.")
