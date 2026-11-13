"""Interactive field locations with honest parcel provenance."""
from pathlib import Path
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[2]
st.title('AgriSim — Field map')
fields=ROOT/'data/reference/fields.csv'
if not fields.is_file():
    st.info('Add confirmed fields to data/reference/fields.csv')
else:
    frame=pd.read_csv(fields)
    if {'lat','lon'}.issubset(frame):
        st.map(frame[['lat','lon']].dropna())
        st.caption('Points are locations, not verified parcel outlines. Provide GeoJSON for true boundaries.')
    st.dataframe(frame,use_container_width=True)
