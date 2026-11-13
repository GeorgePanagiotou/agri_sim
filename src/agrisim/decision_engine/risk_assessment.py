"""Transparent rule-based regional weather risk indicators, NOT calibrated probabilities."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from agrisim.config import REPO as ROOT


def risk_assessment(df:pd.DataFrame):
    rows=df.copy()
    def col(name):return pd.to_numeric(rows[name],errors='coerce') if name in rows else pd.Series(np.nan,index=rows.index)
    rain=col('rain_prior_7d_mm')
    max_day=col('rain_prior_7d_max_mm')
    soil=col('power_wetness_prior_7d')
    dry_cut=col('power_wetness_historical_p20')
    heat=col('temp_prior_7d_c')
    rows['heavy_rain_recent']=np.where(max_day.notna(),max_day>=20,pd.NA)
    rows['dry_surface_relative_to_history']=np.where(soil.notna()&dry_cut.notna(),soil<dry_cut,pd.NA)
    rows['hot_week_indicator']=np.where(heat.notna(),heat>=30,pd.NA)
    slope=col('srtm_slope_deg')
    rows['steep_terrain_indicator']=np.where(slope.notna(),slope>=15,pd.NA)
    # This score counts evidence-backed warning flags; not P(drought) or P(failed crop).
    flag_cols=['heavy_rain_recent','dry_surface_relative_to_history','hot_week_indicator','steep_terrain_indicator']
    rows['risk_factors_observed']=pd.DataFrame({c:rows[c].notna() for c in flag_cols}).sum(axis=1)
    rows['risk_flag_count']=pd.DataFrame({c:rows[c].map(lambda v: bool(v) if pd.notna(v) else False) for c in flag_cols}).sum(axis=1)
    rows['risk_level']=np.select([rows.risk_factors_observed.eq(0),rows.risk_flag_count.ge(2),rows.risk_flag_count.eq(1)],
                                ['unknown','high_flags','review_flags'],default='low_flags')
    rows['risk_method']='heuristic_flags_not_probabilities'
    return rows


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--features',type=Path,default=ROOT/'data/processed/features/sowing_candidate_features.csv')
    p.add_argument('--out',type=Path,default=ROOT/'outputs/risk_alerts.csv')
    a=p.parse_args();df=risk_assessment(pd.read_csv(a.features));a.out.parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(a.out,index=False);print(f'Risk indicators -> {a.out}')
if __name__=='__main__':main()
