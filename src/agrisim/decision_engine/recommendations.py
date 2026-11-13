"""Explainable merged decision evidence; never produce a fabricated success rate."""
import pandas as pd
from .fusion import fuse

def generate(sowing_features, risk_features, ranked_rotations):
    combined=fuse(sowing_features,risk_features,ranked_rotations)
    combined['requires_farmer_confirmation']=True
    combined['forecast_status']='retrospective_analysis_not_a_future_forecast'
    return combined
