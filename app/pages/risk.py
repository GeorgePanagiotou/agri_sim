"""Explainable historical risk flags, not calibrated event probabilities."""
from pathlib import Path
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[2]
st.title('Climate and soil risk review')
st.caption('Screening indicators use regional historical observations; confirm local field conditions.')
p=ROOT/'outputs/risk_alerts.csv'
if p.exists():
    st.dataframe(pd.read_csv(p),use_container_width=True)
else:st.info('Risk table not generated yet; run the decision engine.')
