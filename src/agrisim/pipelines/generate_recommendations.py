"""End-to-end *retrospective* decision engine. Does not issue future-weather forecasts."""
import argparse
from pathlib import Path
import pandas as pd
from agrisim.config import REPO
from agrisim.timeseries.vegetation_indices import build as vegetation
from agrisim.timeseries.greenup import run as phenology
from agrisim.features.build_features import run as build_features
from agrisim.decision_engine.risk_assessment import risk_assessment
from agrisim.decision_engine.sowing_rules import recommend_sowing
from agrisim.decision_engine.ranking import rank_rotations
from agrisim.decision_engine.fusion import fuse

def run(*,fields=REPO/'data/reference/fields.csv',hls_batch=None,sentinel_dir=None,
        parcels=None,skip_vegetation=False,method='heuristic'):
    if not skip_vegetation:
        if not hls_batch and not sentinel_dir: raise ValueError('Supply imagery or --skip-vegetation')
        vegetation(hls_batch,sentinel_dir,parcels=parcels)
        phenology(method=method)
    candidates=build_features(fields)
    out=REPO/'outputs';out.mkdir(parents=True,exist_ok=True)
    risk=risk_assessment(candidates)
    sowing=recommend_sowing(candidates)
    ranking=rank_rotations(pd.read_csv(REPO/'data/reference/rotations_template.csv'))
    risk.to_csv(out/'risk_alerts.csv',index=False)
    sowing.to_csv(out/'sowing_recommendations.csv',index=False)
    ranking.to_csv(out/'rotation_comparisons.csv',index=False)
    fused=fuse(sowing,risk,ranking)
    fused.to_csv(out/'decision_summary.csv',index=False)
    return fused

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fields',type=Path,default=REPO/'data/reference/fields.csv')
    ap.add_argument('--hls-batch',type=Path);ap.add_argument('--sentinel-dir',type=Path)
    ap.add_argument('--parcels',type=Path);ap.add_argument('--skip-vegetation',action='store_true')
    ap.add_argument('--method',choices=['heuristic','pelt'],default='heuristic')
    a=ap.parse_args()
    frame=run(fields=a.fields,hls_batch=a.hls_batch,sentinel_dir=a.sentinel_dir,
              parcels=a.parcels,skip_vegetation=a.skip_vegetation,method=a.method)
    print('Wrote decisions:',len(frame),'rows')
if __name__=='__main__':main()
