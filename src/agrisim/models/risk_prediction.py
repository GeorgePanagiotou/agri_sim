"""Optional risk model; only valid when independent historical risk events are recorded."""
from .training import train_supervised

def fit_risk_model(labelled_days, *, target='risk_event_observed',group='farm_id'):
    return train_supervised(labelled_days,target=target,task='classification',group=group)
