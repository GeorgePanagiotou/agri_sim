"""Farmer-editable qualitative rotation scoring."""
from pathlib import Path
import pandas as pd
import streamlit as st
from agrisim.decision_engine.ranking import rank_rotations, COLUMNS
ROOT=Path(__file__).resolve().parents[2]
st.title('Crop rotation comparison')
st.caption('Priority scores are supplied by the user, NOT measured yield or water savings.')
path=ROOT/'data/reference/rotations_template.csv'
if path.exists():
    data=pd.read_csv(path)
    weights={c:st.slider(c.replace('_score','').replace('_',' ').title(),0.0,5.0,1.0,0.5) for c in COLUMNS}
    edited=st.data_editor(data,num_rows='dynamic',use_container_width=True)
    if st.button('Rank scenarios'):
        try:st.dataframe(rank_rotations(edited,weights),use_container_width=True)
        except ValueError as exc:st.error(str(exc))
else:st.info('Add a rotation template first.')
