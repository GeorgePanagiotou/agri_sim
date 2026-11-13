"""Supervised baseline training on independently observed farm outcomes.

Do NOT train on NDVI-derived pseudo labels and claim crop-establishment accuracy.
Train/test splitting is by whole farms, so repeated dates cannot leak.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import GroupShuffleSplit
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from .evaluation import evaluate_binary, evaluate_regression

IDENTITY_FIELDS={'farm_id','field_id','date','date_utc','candidate_week_start','split','evidence','source_granule','label'}

def train_supervised(data, *, target, task, group='farm_id', holdout_fraction=0.25, seed=42):
    if target not in data or group not in data: raise ValueError('Missing target or farm group')
    if task not in ('classification','regression'):raise ValueError('Unknown task')
    d=data.dropna(subset=[target,group]).copy()
    if d[group].nunique()<4:raise ValueError('At least four distinct farms required for train/holdout')
    # Avoid accidentally training on any measured future outcome, source id or user-entered label.
    chosen=[c for c in d if c not in IDENTITY_FIELDS|{target} and not c.endswith('_outcome')]
    num=[c for c in chosen if pd.api.types.is_numeric_dtype(d[c]) or pd.api.types.is_bool_dtype(d[c])]
    if not num:raise ValueError('Need numeric as-of-date features')
    x=d[num].replace([np.inf,-np.inf],np.nan)
    y=pd.to_numeric(d[target],errors='raise')
    if y.isna().any():raise ValueError('Missing outcomes')
    if task=='classification' and (set(y.unique())-{0,1}):raise ValueError('Classification target must be 0/1')
    splitter=GroupShuffleSplit(n_splits=1,test_size=holdout_fraction,random_state=seed)
    train,test=next(splitter.split(x,y,groups=d[group]))
    if task=='classification' and len(set(y.iloc[train]))<2:
        raise ValueError('Training farms need examples of both outcome classes')
    model = HistGradientBoostingClassifier(random_state=seed,max_iter=100,l2_regularization=1.0) if task=='classification' else HistGradientBoostingRegressor(random_state=seed,max_iter=100,l2_regularization=1.0)
    pipe=Pipeline([('impute',SimpleImputer(strategy='median',add_indicator=True)),('model',model)])
    pipe.fit(x.iloc[train],y.iloc[train])
    pred=pipe.predict_proba(x.iloc[test])[:,1] if task=='classification' else pipe.predict(x.iloc[test])
    metrics=evaluate_binary(y.iloc[test],pred) if task=='classification' else evaluate_regression(y.iloc[test],pred)
    metrics.update(train_farms=int(d.iloc[train][group].nunique()),test_farms=int(d.iloc[test][group].nunique()),
                   target=target,task=task,features=num,evaluation='group_heldout_once_not_final_external_validation')
    return pipe,metrics

def save_model(model,metrics,path):
    import joblib,json
    out=Path(path);out.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump(model,out)
    out.with_suffix('.metrics.json').write_text(json.dumps(metrics,indent=2))
    return out
