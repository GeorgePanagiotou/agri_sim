"""Join sowing, risk and rotation evidence without inventing crop performance.

This is explicit decision evidence fusion, NOT a learned success probability.
"""
import argparse
from pathlib import Path
import pandas as pd
import numpy as np
from agrisim.config import REPO as ROOT


def fuse(sowing:pd.DataFrame,risk:pd.DataFrame,rotations:pd.DataFrame):
    key=['field_id','candidate_week_start']
    if not set(key).issubset(sowing) or not set(key).issubset(risk):
        raise ValueError('Missing field/week key in sowing or risk frame')
    flags=[c for c in ['risk_level','risk_flag_count','risk_factors_observed','risk_method'] if c in risk]
    table=sowing.merge(risk[key+flags],on=key,how='left',validate='one_to_one')
    table['decision_priority']=np.select(
        [table.sowing_screen.eq('insufficient_data') | table.risk_level.fillna('unknown').eq('unknown'),
         table.sowing_screen.ne('candidate_for_field_check'),
         table.risk_level.eq('high_flags'),
         table.risk_level.eq('review_flags')],
        ['evidence_missing','field_check_required','multiple_risk_flags','field_check_advised'],
        default='lower_regional_warning_but_verify_field')
    # Every rotation remains visible; no ranking unless local 0-5 scores were entered.
    keep=[c for c in ['strategy_id','rotation','candidate_crop','evidence_status','relative_priority_score','priority_rank'] if c in rotations]
    merged=table.merge(rotations[keep],how='cross')
    merged['interpretation']='Historical decision-support evidence; not a weather forecast or agronomic directive'
    return merged


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sowing',type=Path,default=ROOT/'outputs/sowing_recommendations.csv')
    p.add_argument('--risk',type=Path,default=ROOT/'outputs/risk_alerts.csv')
    p.add_argument('--rotations',type=Path,default=ROOT/'outputs/rotation_comparisons.csv')
    p.add_argument('--out',type=Path,default=ROOT/'outputs/decision_summary.csv')
    a=p.parse_args()
    df=fuse(pd.read_csv(a.sowing),pd.read_csv(a.risk),pd.read_csv(a.rotations))
    a.out.parent.mkdir(parents=True,exist_ok=True);df.to_csv(a.out,index=False)
    print('Decision evidence fusion ->',a.out)
if __name__=='__main__':main()
