"""Crop rotation ML is not trained until farm-level measured rotation outcomes exist."""
from .training import train_supervised

def fit_rotation_model(records, *, target='measured_seasonal_outcome',group='farm_id'):
    return train_supervised(records,target=target,task='regression',group=group)
