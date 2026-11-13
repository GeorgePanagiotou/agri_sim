"""Small reusable Streamlit plot helpers."""
import pandas as pd

def vegetation_plot(st, observations, *, field_id=None):
    d=observations.copy()
    if field_id is not None:d=d[d.field_id==field_id]
    if d.empty:
        st.info('No vegetation observations for this selection.');return
    d['date_utc']=pd.to_datetime(d.date_utc)
    cols=[c for c in ['ndvi_median','evi2_median','savi_median'] if c in d]
    if cols:st.line_chart(d.set_index('date_utc')[cols])
