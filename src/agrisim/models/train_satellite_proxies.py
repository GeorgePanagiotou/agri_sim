"""Reproducible XGBoost models for AgriSim SATELLITE PROXY targets.

These labels are derived from satellite NDVI: NOT field-verified crop presence,
sowing, emergence, or yield. For real farm outcomes see models/training.py.

Input: committed Parquet tables and their adjacent JSON feature dictionaries.
Forward testing uses complete seasons, never a random pixel split.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, brier_score_loss, f1_score,
                             mean_absolute_error, mean_squared_error, roc_auc_score)
from xgboost import XGBClassifier, XGBRegressor

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / 'data' / 'processed' / 'ml'
DEFAULT_OUTPUT = ROOT / 'artifacts' / 'satellite_proxy_models'
TABLES = {'1114': 'training_table_1114', '1201': 'training_table_v1',
          '0201': 'training_table_0201', '0301': 'training_table_0301',
          '0401': 'training_table_0401'}
TARGETS = {'vigour': 'target_spring_peak_ndvi',
           'crop': 'target_crop', 'class': 'target_class'}
PREFIXES = ('hist_', 'ndvi_prior_', 'soil_', 'terrain_', 'burn_')
ALLOW_EXACT = {'post_fire'}
FORBIDDEN = ('rain_', 'reg_', 'sow_', 'modis_', 'target_')
FORBIDDEN_EXACT = {'season', 'block_id', 'pixel_id', 'row', 'col', 'x_utm',
                   'y_utm', 'lat', 'lon', 'decision_date', 'land_use_2013_2020',
                   'rain_includes_imerg_late', 'reg_rain_source_is_imerg'}
# Burn scar data were only knowable AFTER the 2021 Evia fire. Using them for
# 2002-2021 would make historically impossible information available to models.
FUTURE_FIRE_COLUMNS = {'burn_class_2021', 'burn_dnbr_2021',
                       'terrain_upslope_burned_share'}


def json_write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False, default=str), encoding='utf-8')


def load_pair(table_path: Path) -> tuple[pd.DataFrame, dict]:
    meta_path = table_path.with_suffix('.json')
    if not table_path.exists() or not meta_path.exists():
        raise FileNotFoundError(f'Missing table or companion JSON: {table_path} / {meta_path}')
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    table = pd.read_parquet(table_path)
    validate_table(table, meta)
    return table, meta


def validate_table(df: pd.DataFrame, meta: dict) -> None:
    fields = ['features', 'group_columns', 'id_columns', 'targets', 'as_of', 'rows']
    missing_keys = [k for k in fields if k not in meta]
    if missing_keys:
        raise ValueError(f'Missing metadata keys: {missing_keys}')
    expected = set(meta['features']) | set(meta['group_columns']) | set(meta['id_columns']) | set(meta['targets'])
    missing_cols = expected - set(df.columns)
    if missing_cols:
        raise ValueError(f'Columns declared in JSON absent from table: {sorted(missing_cols)}')
    if int(meta['rows']) != len(df):
        raise ValueError(f'Metadata row count {meta["rows"]} != actual {len(df)}')
    if df.duplicated(['season', 'pixel_id']).any():
        raise ValueError('Repeated (season, pixel_id): table is not uniquely keyed')
    if df['season'].isna().any():
        raise ValueError('Null season')
    if {'target_class', 'target_crop'} <= set(df.columns):
        known = df['target_class'].notna() & df['target_crop'].notna()
        predicted_binary = (df.loc[known, 'target_class'] == 1).astype(int)
        observed_binary = df.loc[known, 'target_crop'].astype(int)
        if not np.array_equal(predicted_binary.to_numpy(), observed_binary.to_numpy()):
            raise ValueError('target_crop is inconsistent with target_class == 1')
    if 'decision_date' in df:
        mm, dd = map(int, meta['as_of'].split('-'))
        season = df['season'].astype(int)
        dyear = season - (1 if mm >= 9 else 0)
        dates = pd.to_datetime(df['decision_date'], errors='coerce')
        expected_dates = pd.to_datetime(dyear.astype(str) + f'-{mm:02d}-{dd:02d}')
        if dates.isna().any() or not (dates.to_numpy() == expected_dates.to_numpy()).all():
            raise ValueError('decision_date does not match season / metadata as_of')


def select_features(meta: dict) -> list[str]:
    """Select exclusively from the supplied companion JSON, with explicit exclusions."""
    selected = [c for c in meta['features'] if c in ALLOW_EXACT or c.startswith(PREFIXES)]
    bad = [c for c in selected if c in FORBIDDEN_EXACT or c.startswith(FORBIDDEN)]
    if bad:
        raise ValueError(f'Forbidden feature found: {bad}')
    if not any(c.startswith('hist_') for c in selected):
        raise ValueError('No history features found; check companion JSON')
    if len(selected) != len(set(selected)):
        raise ValueError('Duplicate feature names in metadata')
    return selected


def make_features(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.loc[:, cols].apply(pd.to_numeric, errors='raise').replace([np.inf, -np.inf], np.nan).astype('float32')
    # Everything in the history before the Aug 2021 fire must be unaffected by
    # its eventually observed burn severity or burned-upslope extent.
    old = df['season'].astype(int) < 2022
    for c in FUTURE_FIRE_COLUMNS.intersection(cols):
        out.loc[old, c] = np.nan
    return out


def trainable_features(x: pd.DataFrame, train_mask: np.ndarray) -> list[str]:
    kept = [c for c in x if x.loc[train_mask, c].notna().any()]
    if not kept:
        raise ValueError('All candidate features are null in the training seasons')
    return kept


def model_for(task: str, device: str, n_estimators: int, seed: int):
    shared = dict(n_estimators=n_estimators, max_depth=4, learning_rate=0.045,
                  min_child_weight=25, subsample=0.85, colsample_bytree=0.85,
                  reg_lambda=7.0, tree_method='hist', device=device,
                  n_jobs=8, random_state=seed)
    if task == 'vigour':
        return XGBRegressor(objective='reg:squarederror', **shared)
    if task == 'crop':
        return XGBClassifier(objective='binary:logistic', eval_metric='logloss', **shared)
    if task == 'class':
        return XGBClassifier(objective='multi:softprob', num_class=3,
                             eval_metric='mlogloss', **shared)
    raise ValueError(task)


def to_labels(df: pd.DataFrame, task: str) -> np.ndarray:
    y = pd.to_numeric(df[TARGETS[task]], errors='coerce').to_numpy(dtype=float)
    if task == 'crop' and not set(np.unique(y[np.isfinite(y)])) <= {0, 1}:
        raise ValueError('Invalid binary crop target')
    if task == 'class':
        if not set(np.unique(y[np.isfinite(y)])) <= {1, 2, 3}:
            raise ValueError('Unexpected target_class values (expect 1, 2, 3)')
        y = y - 1  # XGBoost multiclass needs 0,1,2; output is remapped to 1,2,3
    return y


def fit_model(x: pd.DataFrame, y: np.ndarray, mask: np.ndarray,
              task: str, device: str, n_estimators: int, seed: int):
    eligible = mask & np.isfinite(y)
    if eligible.sum() < 100:
        raise ValueError(f'Only {eligible.sum()} labeled rows to train {task}')
    if task != 'vigour' and len(np.unique(y[eligible])) < (3 if task == 'class' else 2):
        raise ValueError('Not all target classes present in training subset')
    model = model_for(task, device, n_estimators, seed)
    sample_weight = None
    if task == 'class':
        values, counts = np.unique(y[eligible], return_counts=True)
        weights = {int(k): min(8.0, eligible.sum() / (len(values) * c)) for k, c in zip(values, counts)}
        sample_weight = np.array([weights[int(v)] for v in y[eligible]])
    model.fit(x.loc[eligible], y[eligible].astype(int) if task != 'vigour' else y[eligible],
              sample_weight=sample_weight)
    return model


def predict_model(model, x: pd.DataFrame, task: str):
    if task == 'crop':
        return model.predict_proba(x)[:, 1]
    if task == 'class':
        return model.predict(x).astype(int) + 1
    return model.predict(x)


def score(y: np.ndarray, p: np.ndarray, task: str) -> dict:
    valid = np.isfinite(y) & np.isfinite(p)
    if valid.sum() < 2:
        return {'rows': int(valid.sum())}
    yt, yp = y[valid], p[valid]
    if task == 'vigour':
        return {'rows': int(valid.sum()),
                'rmse': float(np.sqrt(mean_squared_error(yt, yp))),
                'mae': float(mean_absolute_error(yt, yp))}
    if task == 'crop':
        yb = yt.astype(int)
        scores = {'rows': int(valid.sum()),
                  'brier': float(brier_score_loss(yb, yp)),
                  'accuracy_at_0_5': float(accuracy_score(yb, yp >= .5)),
                  'f1_at_0_5': float(f1_score(yb, yp >= .5, zero_division=0))}
        scores['roc_auc'] = (float(roc_auc_score(yb, yp)) if len(np.unique(yb)) == 2 else None)
        return scores
    # target_class 1..3, and predictions 1..3
    return {'rows': int(valid.sum()),
            'accuracy': float(accuracy_score(yt.astype(int), yp.astype(int))),
            'macro_f1': float(f1_score(yt.astype(int), yp.astype(int),
                                       labels=[1, 2, 3], average='macro', zero_division=0))}


def baseline_column(task: str) -> str:
    return {'vigour': 'hist_peak_mean_5y', 'crop': 'hist_crop_share_5y',
            'class': 'hist_class_lag1'}[task]


def evaluate_predictions(df: pd.DataFrame, y: np.ndarray, p: np.ndarray,
                         task: str, eval_mask: np.ndarray) -> tuple[dict, pd.DataFrame]:
    # Predictions may include holdout rows whose pseudo-target is missing.
    # Align to the full row index before subsetting labeled evaluation rows.
    full_p = np.full(len(df), np.nan, dtype=float)
    full_p[eval_mask] = p
    eligible = eval_mask & np.isfinite(y) & np.isfinite(full_p)
    predicted = full_p[eligible]
    target = y[eligible] + (1 if task == 'class' else 0)
    base = pd.to_numeric(df.loc[eligible, baseline_column(task)], errors='coerce').to_numpy(dtype=float)
    result = {'model': score(target, predicted, task),
              'historical_baseline': score(target, base, task)}
    common = np.isfinite(base) & np.isfinite(predicted)
    result['model_on_baseline_rows'] = score(target[common], predicted[common], task)
    output = pd.DataFrame({'season': df.loc[eligible, 'season'].to_numpy(),
                           'pixel_id': df.loc[eligible, 'pixel_id'].to_numpy(),
                           'actual': target, 'predicted': predicted, 'baseline': base})
    by_season = []
    for season, chunk in output.groupby('season', sort=True):
        yy = chunk.actual.to_numpy()
        model_score = score(yy, chunk.predicted.to_numpy(), task)
        base_score = score(yy, chunk.baseline.to_numpy(), task)
        by_season.append({'season': int(season),
                          **{f'model_{k}': v for k, v in model_score.items()},
                          **{f'baseline_{k}': v for k, v in base_score.items()}})
    return result, pd.DataFrame(by_season)


def train_one(df: pd.DataFrame, meta: dict, date_code: str, output: Path,
              test_from: int = 2018, tasks: tuple[str, ...] = ('vigour', 'crop', 'class'),
              device: str = 'cpu', n_estimators: int = 350, seed: int = 42,
              live_df: pd.DataFrame | None = None, live_meta: dict | None = None,
              loso: bool = False) -> dict:
    validate_table(df, meta)
    if date_code not in TABLES:
        raise ValueError(f'Unknown decision-date code: {date_code}')
    expected_date = {'1114': '11-14', '1201': '12-01',
                     '0201': '02-01', '0301': '03-01', '0401': '04-01'}[date_code]
    if meta['as_of'] != expected_date:
        raise ValueError(f'Expected as_of={expected_date}, got {meta["as_of"]}')
    selected = select_features(meta)
    train_mask = (df['season'].astype(int) < test_from).to_numpy()
    test_mask = ~train_mask
    if not train_mask.any() or not test_mask.any():
        raise ValueError(f'Need training before {test_from} and testing from {test_from} onward')
    x_full = make_features(df, selected)
    kept = trainable_features(x_full, train_mask)
    x = x_full[kept]
    report = {'decision_date': expected_date, 'area': meta.get('area'),
              'training_seasons': sorted(map(int, df.loc[train_mask, 'season'].unique())),
              'holdout_seasons': sorted(map(int, df.loc[test_mask, 'season'].unique())),
              'training_rows': int(train_mask.sum()), 'holdout_rows': int(test_mask.sum()),
              'feature_policy': 'hist_ ndvi_prior_ soil_ terrain_ burn_ post_fire only',
              'features': kept, 'dropped_all_missing_features': sorted(set(selected) - set(kept)),
              'evaluation': 'forward season holdout, NOT farm-outcome validation',
              'limitations': ['targets are Landsat NDVI-derived proxies, not farm-record outcomes',
                              'historical crop pseudo-label thresholds were fitted with later years; some hindsight leakage remains',
                              'static modern soil layers may be historically anachronistic',
                              'uncalibrated crop probabilities: do NOT display as verified confidence',
              'target_crop=0 includes both fallow (class 2) and summer crop (class 3)'],
              'data_audit': {
                  'rows_by_season': {str(int(k)): int(v) for k, v in df.groupby('season').size().items()},
                  'feature_nonmissing_share': {c: round(float(x_full[c].notna().mean()), 4) for c in selected},
                  'crop_proxy_class_distribution': {str(int(k)): int(v) for k, v in
                                                     df['target_class'].dropna().value_counts().sort_index().items()},
              },
              'tasks': {}}
    out = output / date_code
    out.mkdir(parents=True, exist_ok=True)
    live_x = None
    if live_df is not None:
        if live_meta is None or meta['as_of'] != live_meta['as_of']:
            raise ValueError('Live table decision date does not match training table')
        if list(meta['features']) != list(live_meta['features']):
            raise ValueError('Training and live metadata feature lists differ')
        validate_table(live_df, live_meta)
        live_x = make_features(live_df, kept)
    for task in tasks:
        y = to_labels(df, task)
        print(f'[{date_code}/{task}] forward train {train_mask.sum()} rows, test {test_mask.sum()}', flush=True)
        model = fit_model(x, y, train_mask, task, device, n_estimators, seed)
        p = predict_model(model, x.loc[test_mask], task)
        scores, seasons = evaluate_predictions(df, y, p, task, test_mask)
        scores['trained_on_seasons_through'] = test_from - 1
        scores['evaluated_from_season'] = test_from
        # Retrain a PRODUCTION model after evaluation. Do not score this fitted model
        # on the holdout and describe that as holdout performance.
        full_eligible = np.isfinite(y)
        final_features = trainable_features(x_full, full_eligible)
        final_x = x_full[final_features]
        production = fit_model(final_x, y, np.ones(len(df), dtype=bool), task,
                               device, n_estimators, seed)
        production_path = out / f'{task}_xgb.json'
        production.save_model(str(production_path))
        scores['production_model_trained_through'] = int(df.loc[full_eligible, 'season'].max())
        scores['production_features'] = final_features
        seasons.to_csv(out / f'{task}_forward_by_season.csv', index=False)
        json_write(out / f'{task}_forward_metrics.json', scores)
        if live_x is not None:
            # Final model can learn features unavailable in older forward train
            # (e.g. post-fire). Apply its actual feature list in exactly that order.
            live_pred = predict_model(production, make_features(live_df, final_features), task)
            live_out = live_df[['season', 'pixel_id', 'lon', 'lat', 'decision_date']].copy()
            if task == 'vigour':
                live_out['pred_spring_peak_ndvi'] = live_pred
            elif task == 'crop':
                live_out['pred_crop_probability_uncalibrated'] = live_pred
            else:
                live_out['pred_satellite_class'] = live_pred
            live_out.to_csv(out / f'{task}_live_2027.csv.gz', index=False, compression='gzip')
        if loso:
            # Diagnostic only, future seasons are included when testing earlier ones.
            folds = []
            for season in sorted(df.season.unique()):
                season_mask = (df.season.to_numpy() == season) & np.isfinite(y)
                other_mask = (df.season.to_numpy() != season) & np.isfinite(y)
                if season_mask.sum() < 2 or other_mask.sum() < 100:
                    continue
                fold_features = trainable_features(x_full, other_mask)
                try:
                    fit = fit_model(x_full[fold_features], y, other_mask,
                                    task, device, n_estimators, seed)
                except ValueError as exc:
                    warnings.warn(f'LOSO season {season}: {exc}')
                    continue
                fold_p = predict_model(fit, x_full.loc[season_mask, fold_features], task)
                truth = y[season_mask] + (1 if task == 'class' else 0)
                folds.append({'season': int(season), **score(truth, fold_p, task)})
            pd.DataFrame(folds).to_csv(out / f'{task}_loso_by_season.csv', index=False)
        report['tasks'][task] = scores
    json_write(out / 'run_manifest.json', report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date', choices=TABLES.keys(), default='0301',
                   help='1114=Nov14, 1201=Dec1, 0201=Feb1, 0301=Mar1, 0401=Apr1')
    p.add_argument('--all-dates', action='store_true')
    p.add_argument('--input-dir', type=Path, default=DEFAULT_INPUT)
    p.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    p.add_argument('--test-from', type=int, default=2018)
    p.add_argument('--tasks', nargs='+', choices=TARGETS.keys(), default=list(TARGETS))
    p.add_argument('--estimators', type=int, default=350)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    p.add_argument('--live-2027', action='store_true', help='Only with --date 1114')
    p.add_argument('--loso', action='store_true',
                   help='Optional expensive leave-one-season-out diagnostic')
    args = p.parse_args(argv)
    if args.all_dates and args.live_2027:
        p.error('--live-2027 requires --date 1114, not --all-dates')
    if args.live_2027 and args.date != '1114':
        p.error('2027-11-14 prediction table must use the 1114 model')
    dates = list(TABLES) if args.all_dates else [args.date]
    live_data = live_meta = None
    if args.live_2027:
        live_data, live_meta = load_pair(args.input_dir / 'predict_2027_1114.parquet')
        if live_data[[c for c in TARGETS.values() if c in live_data]].notna().any().any():
            raise ValueError('Live prediction table unexpectedly has observed targets')
    for date_code in dates:
        table, meta = load_pair(args.input_dir / f'{TABLES[date_code]}.parquet')
        report = train_one(table, meta, date_code, args.output_dir,
                           test_from=args.test_from, tasks=tuple(args.tasks),
                           n_estimators=args.estimators, seed=args.seed,
                           device=args.device, live_df=live_data, live_meta=live_meta,
                           loso=args.loso)
        print(f'Completed {date_code}. Summary: {args.output_dir / date_code / "run_manifest.json"}', flush=True)
        for task, detail in report['tasks'].items():
            print(f'  {task}: forward model={detail["model"]}  baseline={detail["historical_baseline"]}', flush=True)


if __name__ == '__main__':
    main()
