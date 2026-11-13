"""Historical candidate-week warnings; not a future forecast."""
from pathlib import Path
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[2]
st.title('Sowing-week screening')
st.caption('Retrospective regional evidence only, not operational recommendations or predicted success rates.')
p=ROOT/'outputs/sowing_recommendations.csv'
if p.exists():
    d=pd.read_csv(p)
    if 'field_id' in d:
        choices=sorted(d.field_id.dropna().astype(str).unique())
        if choices:d=d[d.field_id.astype(str)==st.selectbox('Field',choices)]
    st.dataframe(d,use_container_width=True)
else:st.info('Generate features and run the decision pipeline first.')
