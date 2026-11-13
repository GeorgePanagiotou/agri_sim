"""Supervised sowing-success training entry point, requiring ground-observed outcomes."""
from .training import train_supervised

def fit_outcome_model(labelled_candidates,*,target='established_successfully',group='farm_id'):
    return train_supervised(labelled_candidates,target=target,task='classification',group=group)

def fit_emergence_days(labelled_candidates,*,target='days_to_emergence',group='farm_id'):
    return train_supervised(labelled_candidates,target=target,task='regression',group=group)
