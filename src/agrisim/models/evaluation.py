"""Out-of-group classification/regression diagnostics for real observed outcomes."""
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score,roc_auc_score,mean_absolute_error,mean_squared_error

def evaluate_binary(y_true,probability,threshold=0.5):
    y=np.asarray(y_true);p=np.asarray(probability,dtype=float)
    if set(np.unique(y))-{0,1}:raise ValueError('Targets must be 0/1')
    result={'n':len(y),'positive_count':int((y==1).sum()),'accuracy':float(accuracy_score(y,p>=threshold))}
    result['roc_auc'] = float(roc_auc_score(y,p)) if len(np.unique(y))==2 else np.nan
    return result

def evaluate_regression(y_true,y_pred):
    y=np.asarray(y_true,dtype=float);p=np.asarray(y_pred,dtype=float)
    if not np.isfinite(y).all() or not np.isfinite(p).all():raise ValueError('Nonfinite values in evaluation')
    return {'n':len(y),'mae':float(mean_absolute_error(y,p)),
            'rmse':float(np.sqrt(mean_squared_error(y,p)))}
