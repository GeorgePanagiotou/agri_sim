"""AgriSim AI: North Evia retrospective decision-support demo.

Run: uv run --extra app streamlit run app/streamlit_app.py
No fake live forecasts, independently-verified crop labels or yield predictions.
"""
from pathlib import Path
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[1]
st.set_page_config(page_title='AgriSim AI | North Evia',page_icon='🌱',layout='wide')
st.title('🌱 AgriSim AI')
st.caption('NASA Space Apps 2026 | North Evia · satellite evidence, sowing-week screens and crop-rotation comparisons')
st.warning('Research prototype. Regional NASA/ESA estimates are not field measurements; screens are not a sowing directive, forecast, or crop success probability.',icon='⚠️')


def maybe_csv(path):
    return pd.read_csv(path) if path.exists() else None

fields=maybe_csv(ROOT/'data/reference/fields.csv')
if fields is not None and {'lat','lon'}.issubset(fields):
    st.subheader('Study sites')
    st.map(fields.rename(columns={'lat':'latitude','lon':'longitude'})[['latitude','longitude']])

obs=maybe_csv(ROOT/'data/processed/features/vegetation_observations.csv')
if obs is not None and not obs.empty:
    st.subheader('A · Vegetation time-series evidence')
    col1,col2=st.columns([1,3]);site=col1.selectbox('Field / window',sorted(obs.field_id.unique()))
    subset=obs[obs.field_id==site].copy();subset['date_utc']=pd.to_datetime(subset.date_utc)
    tidy=subset.melt(id_vars='date_utc',value_vars=['ndvi_median','evi2_median'],var_name='index',value_name='value')
    col2.line_chart(tidy,pivot='index',x='date_utc',y='value')
    st.caption('Time series from native reflectance, quality-masked. A spectral increase is not proof of planted crop emergence.')
    green=maybe_csv(ROOT/'data/processed/features/greenup_events.csv')
    if green is not None:st.dataframe(green[green.field_id==site],hide_index=True,use_container_width=True)
else:
    st.info('No vegetation time series yet. Download an approved HLS batch, then run `python -m pipeline.vegetation` and `python -m pipeline.phenology`.')

st.divider()
col1,col2=st.columns(2)
with col1:
    st.subheader('B · Sowing-week screening')
    sow=maybe_csv(ROOT/'outputs/sowing_recommendations.csv')
    if sow is None:st.info('Run `python -m pipeline.build` after downloading POWER and GPM.')
    else:
        if 'field_id' in sow:
            opt=st.selectbox('Field for sowing analysis',sorted(sow.field_id.unique()),key='sowingfield')
            sow=sow[sow.field_id==opt]
        keep=[c for c in ('candidate_week_start','sowing_screen','rain_prior_7d_mm','temp_prior_7d_c','power_wetness_prior_7d','sowing_explanation') if c in sow]
        st.dataframe(sow[keep].tail(40),hide_index=True,use_container_width=True)
        st.caption('A retrospective screen using completed prior-day data. Not a future weather forecast.')
with col2:
    st.subheader('D · Regional risk alerts')
    risk=maybe_csv(ROOT/'outputs/risk_alerts.csv')
    if risk is None:st.info('Risk indicators appear after feature generation.')
    else:
        cols=[c for c in ('field_id','candidate_week_start','risk_level','risk_flag_count','risk_factors_observed') if c in risk]
        st.dataframe(risk[cols].tail(40),hide_index=True,use_container_width=True)
        st.caption('Risk levels count rule-based flags, not calibrated probabilities.')

st.divider()
st.subheader('C + E · Rotation comparison and decision fusion')
rotation=maybe_csv(ROOT/'outputs/rotation_comparisons.csv')
if rotation is None:
    st.info('Run `python -m decision_engine.rotation`. Fill the rotation-score template with farmer/agronomist-verified estimates to produce a preference ranking.')
else:
    show=[c for c in ['strategy_id','rotation','candidate_crop','evidence_status','relative_priority_score','priority_rank'] if c in rotation]
    st.dataframe(rotation[show],hide_index=True,use_container_width=True)
    st.caption('Scores reflect stakeholder preferences only, not estimated farm yields or proven environmental benefits.')
summary=maybe_csv(ROOT/'outputs/decision_summary.csv')
if summary is not None:
    st.subheader('E · Combined decision evidence')
    keep=[c for c in ['field_id','candidate_week_start','strategy_id','decision_priority','evidence_status','relative_priority_score'] if c in summary]
    st.dataframe(summary[keep].tail(60),hide_index=True,use_container_width=True)
st.subheader('Data provenance and limitations')
st.markdown('Allowed products: NASA HLS/Landsat, SMAP, GPM IMERG, POWER, MODIS, ECOSTRESS, SRTM; ESA Sentinel-2 and ERA5-Land; FAO GAEZ. Historical source data may be accessed via documented data mirrors. See `sources.json` and `docs/DATA_CONTRACT.md`.')
