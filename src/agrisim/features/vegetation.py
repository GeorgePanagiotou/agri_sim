"""Merge quality-screened vegetation metrics and green-up events by field/season."""
import pandas as pd
from agrisim.timeseries.phenology_metrics import seasonal_metrics

def build_vegetation_features(observations, events=None):
    features = seasonal_metrics(observations)
    if events is not None and len(events):
        keys = [c for c in ('field_id','season','source') if c in events and c in features]
        if len(keys) < 2: raise ValueError('Cannot align green-up event by field and season')
        keep=events.drop_duplicates(keys)
        return features.merge(keep,on=keys,how='left',validate='one_to_one')
    return features
