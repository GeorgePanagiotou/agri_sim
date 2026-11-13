"""Compare farmer-entered crop rotations using transparent qualitative inputs.

No yields or crop performance are invented. Without completed, farmer-reviewed
scores the model returns 'needs_local_inputs' rather than a fabricated ranking.
"""
import argparse
from pathlib import Path
import pandas as pd
from agrisim.config import REPO as ROOT
COLUMNS=('soil_cover_score','water_efficiency_score','feed_score','bee_foraging_score','market_score')


def rank_rotations(rotations:pd.DataFrame,weights:dict|None=None):
    df=rotations.copy()
    required={'strategy_id','rotation','candidate_crop',*COLUMNS}
    missing=required-set(df)
    if missing:raise ValueError(f'Missing rotation columns: {sorted(missing)}')
    weights=weights or dict.fromkeys(COLUMNS,1.0)
    bad=set(weights)-set(COLUMNS)
    if bad:raise ValueError(f'Unrecognized priorities: {bad}')
    if any(float(w)<0 for w in weights.values()) or sum(weights.values())<=0:
        raise ValueError('Priorities must be nonnegative and not all zero')
    for c in COLUMNS:
        df[c]=pd.to_numeric(df[c],errors='coerce')
    complete=df[list(COLUMNS)].notna().all(axis=1)
    for c in COLUMNS:
        if (df[c].notna() & ~df[c].between(0,5)).any():
            raise ValueError(f'{c} must be from 0 to 5')
    df['evidence_status']=complete.map({True:'local_scores_supplied_unverified',False:'needs_local_inputs'})
    weighted=sum(df[c]*weights.get(c,0) for c in COLUMNS)/sum(weights.values())
    df['relative_priority_score']=weighted.where(complete)
    df['priority_rank']=df['relative_priority_score'].rank(ascending=False,method='min').astype('Int64')
    df['ranking_caveat']='Qualitative stakeholder preference comparison; NOT validated yield, water-use or erosion estimates'
    return df.sort_values(['priority_rank','strategy_id'],na_position='last')


def main():
    p=argparse.ArgumentParser();p.add_argument('--rotations',type=Path,default=ROOT/'data/reference/rotations_template.csv')
    p.add_argument('--out',type=Path,default=ROOT/'outputs/rotation_comparisons.csv')
    a=p.parse_args();df=rank_rotations(pd.read_csv(a.rotations));a.out.parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(a.out,index=False);print(f'Rotation comparisons -> {a.out}')
if __name__=='__main__':main()
