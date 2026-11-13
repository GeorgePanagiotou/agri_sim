"""Explainable sowing-week screening. NOT a learned probability of establishment."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from agrisim.config import REPO as ROOT


def recommend_sowing(df:pd.DataFrame):
    out=df.copy()
    rain=pd.to_numeric(out['rain_prior_7d_mm'],errors='coerce')
    temp=pd.to_numeric(out['temp_prior_7d_c'],errors='coerce')
    wet=pd.to_numeric(out['power_wetness_prior_7d'],errors='coerce')
    p20=pd.to_numeric(out['power_wetness_historical_p20'],errors='coerce')
    maxrain=pd.to_numeric(out['rain_prior_7d_max_mm'],errors='coerce')
    missing=rain.isna()|temp.isna()|wet.isna()|p20.isna()|maxrain.isna()
    # Screening rules are DEMO HEURISTICS, not agronomic thresholds for a specific crop.
    too_dry=(rain<5)&(wet<p20)
    too_wet=maxrain>=30
    cold=temp<5
    out['sowing_screen']=np.select([missing,too_wet,too_dry,cold],
                                  ['insufficient_data','field_check_after_heavy_rain','field_check_dry_seedbed','field_check_low_temperature'],
                                  default='candidate_for_field_check')
    out['sowing_explanation']=np.select([missing,too_wet,too_dry,cold],
         ['Incomplete regional inputs; do not infer field conditions',
          'Heavy rain in the prior week; inspect drainage and machinery access',
          'Low recent rain and regional wetness; inspect actual seedbed moisture',
          'Low recent regional temperature; verify the crop-specific minimum'],
         default='No regional warning triggered; on-farm verification is still necessary')
    out['sowing_method']='transparent_regional_screen_not_success_probability'
    return out


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--features',type=Path,default=ROOT/'data/processed/features/sowing_candidate_features.csv')
    p.add_argument('--out',type=Path,default=ROOT/'outputs/sowing_recommendations.csv')
    a=p.parse_args()
    df=recommend_sowing(pd.read_csv(a.features))
    a.out.parent.mkdir(parents=True,exist_ok=True);df.to_csv(a.out,index=False)
    print(f'Sowing-week screens -> {a.out}')
if __name__=='__main__':main()
