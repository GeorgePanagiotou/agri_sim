"""Train a SELF-CONTAINED staging bundle for the 2027 agricultural season.

Data split: train historical satellite proxy models through 2023 and calibrate
with 2024-2026. No 2027 outcome data may be used. No farm-verified labels.

This does NOT attach calibration artifacts to models previously fit through 2026.
It uses exactly the manifest-selected, fixed no-wildfire-severity feature set.

Commands:
  python -m agrisim.models.satellite_bundle_2027 --date 0301
  python -m agrisim.models.satellite_bundle_2027 --date 0401
  python -m agrisim.models.satellite_bundle_2027 --date 0301 --predict-table path/to/predict_2027_0301.parquet
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost
from xgboost import XGBClassifier, XGBRegressor

from .train_satellite_proxies import (
    DEFAULT_INPUT, DEFAULT_OUTPUT, FUTURE_FIRE_COLUMNS, TABLES,
    fit_model, json_write, load_pair, make_features, select_features,
    trainable_features, validate_table,
)
from .calibrate_satellite_proxies import (
    DATE_META, _auc, _brier, _coverage, interval_bounds,
    make_quantile_model, numeric_labels, season_aware_cqr_offset,
)
from .calibrate_satellite_rolling import (
    fit_probability_calibrators, probability_predictions,
)

SUPPORTED_DATES = ("0301", "0401")
# Pre-declared hypotheses based on 2018-2026 rolling historical comparisons;
# this is method selection informed by retrospective results, not prospective proof.
CROP_METHODS = {"0301": "sigmoid", "0401": "raw"}


def fixed_feature_names(meta: dict, df: pd.DataFrame, train_mask: np.ndarray) -> list[str]:
    """Same field-level feature list for every year, no retrospective fire severity."""
    selected = [c for c in select_features(meta) if c not in FUTURE_FIRE_COLUMNS]
    x = make_features(df, selected)
    return trainable_features(x, train_mask)


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(2**20), b''):
            digest.update(block)
    return digest.hexdigest()


def create_2027_bundle(df: pd.DataFrame, meta: dict, *, date_code: str,
                       output_dir: Path, train_through: int = 2023,
                       calibration_through: int = 2026,
                       estimators: int = 350, device: str = "cpu", seed: int = 42,
                       coverage: float = 0.8, table_path: Path | None = None) -> dict:
    """Fit separate base and calibration groups; write all deployable inputs.

    Inference requires matching 2027 decision-date feature table, which may not
    exist until 1 March/April 2027; no outputs are fabricated ahead of that.
    """
    if date_code not in SUPPORTED_DATES or meta['as_of'] != DATE_META[date_code]:
        raise ValueError('Unsupported or mismatched March/April decision date')
    if not 0 < coverage < 1 or estimators < 2:
        raise ValueError('Invalid coverage or estimators')
    if train_through >= calibration_through or calibration_through != 2026:
        raise ValueError('2027 bundle requires calibration ending in 2026')
    validate_table(df, meta)
    season = df['season'].astype(int).to_numpy()
    if np.any(season > 2026):
        raise ValueError('2027 outcome data cannot enter the model or calibration')
    fit = season <= train_through
    cal = (season > train_through) & (season <= calibration_through)
    years = np.unique(season[cal])
    if len(years) < 3:
        raise ValueError('Need at least three independent calibration seasons')
    if not np.any(fit) or not np.all(np.diff(years) > 0):
        raise ValueError('Missing training/calibration seasons')
    features = fixed_feature_names(meta, df, fit)
    x = make_features(df, features)
    crop_y = numeric_labels(df, 'target_crop')
    vig_y = numeric_labels(df, 'target_spring_peak_ndvi')
    cf = fit & np.isfinite(crop_y)
    cc = cal & np.isfinite(crop_y)
    vf = fit & np.isfinite(vig_y)
    vc = cal & np.isfinite(vig_y)
    if min(np.count_nonzero(m) for m in (cf, cc, vf, vc)) < 100:
        raise ValueError('Insufficient labeled training or calibration data')
    if len(np.unique(crop_y[cc])) != 2:
        raise ValueError('Calibrator must observe both crop classes')
    if len(np.unique(season[vc])) < 3 or len(np.unique(season[cc])) < 3:
        raise ValueError('Insufficient nonmissing calibration seasons')

    crop = fit_model(x, crop_y, cf, 'crop', device, estimators, seed)
    point = fit_model(x, vig_y, vf, 'vigour', device, estimators, seed)
    lower_q = make_quantile_model((1 - coverage) / 2, estimators=estimators, device=device, seed=seed)
    upper_q = make_quantile_model(1 - (1 - coverage) / 2, estimators=estimators, device=device, seed=seed)
    lower_q.fit(x.loc[vf], vig_y[vf]); upper_q.fit(x.loc[vf], vig_y[vf])

    # Base models have never seen 2024-2026; use only those seasons to calibrate.
    p_cal = crop.predict_proba(x.loc[cc])[:, 1]
    sigmoid, isotonic = fit_probability_calibrators(p_cal, crop_y[cc], season[cc])
    probabilities = probability_predictions(p_cal, sigmoid, isotonic)
    crop_diagnostics = {m: {'brier': _brier(crop_y[cc], p), 'auc': _auc(crop_y[cc], p)}
                        for m, p in probabilities.items()}
    raw_lo, raw_hi = interval_bounds(lower_q.predict(x.loc[vc]), upper_q.predict(x.loc[vc]))
    offset, season_quantiles = season_aware_cqr_offset(vig_y[vc], raw_lo, raw_hi, season[vc], coverage=coverage)
    calib_coverage, calib_width = _coverage(vig_y[vc], raw_lo - offset, raw_hi + offset)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, model in [('crop_xgb.json', crop), ('vigour_xgb.json', point),
                        ('vigour_q10_xgb.json', lower_q), ('vigour_q90_xgb.json', upper_q)]:
        model.save_model(str(output_dir / name))
    joblib.dump(sigmoid, output_dir / 'crop_sigmoid_calibrator.joblib')
    # Isotonic is not selected but stored for offline reproducibility only.
    joblib.dump(isotonic, output_dir / 'crop_isotonic_reference.joblib')
    manifest = {
        'bundle_type': '2027_satellite_proxy_staging', 'prediction_season': 2027,
        'decision_date': meta['as_of'], 'date_code': date_code, 'area': meta.get('area'),
        'fit_seasons': sorted(map(int, np.unique(season[fit]))),
        'calibration_seasons': sorted(map(int, years)),
        'features': features, 'feature_policy': 'fixed_no_fire_2021_severity',
        'excluded_fire_features': sorted(FUTURE_FIRE_COLUMNS),
        'crop_probability_method': CROP_METHODS[date_code],
        'calibration_method_selection': 'retrospective 2018-2026 rolling evaluation; not prospectively validated',
        'nominal_interval_coverage': coverage,
        'conformal_offset_ndvi': offset,
        'conformal_season_quantiles': season_quantiles,
        'calibration_set_diagnostics_NOT_independent_test': {
            'crop': crop_diagnostics,
            'vigour_conformal_coverage': calib_coverage,
            'vigour_conformal_mean_width': calib_width,
        },
        'model_versions': {'xgboost': xgboost.__version__, 'sklearn': sklearn.__version__},
        'training_table_sha256': sha256(table_path) if table_path is not None else None,
        'metadata_sha256': sha256(table_path.with_suffix('.json')) if table_path is not None else None,
        'models': {'vigour': 'vigour_xgb.json', 'crop': 'crop_xgb.json',
                   'vigour_q10': 'vigour_q10_xgb.json', 'vigour_q90': 'vigour_q90_xgb.json'},
        'limitations': [
            'Satellite-derived proxy labels; NOT verified farmer-reported crop outcomes or yields',
            'April uses March NDVI from within the spring peak target window (in-season monitoring)',
            'Calibration scores are on the calibration seasons, not independent test results',
            'Historical pseudo-label definitions have residual hindsight leakage',
            'Historical rolling comparisons informed method choice; new unseen seasons required to verify',
            '80% marginal interval coverage is a target, not a future-season guarantee',
            'This self-contained model is DIFFERENT from existing models trained through 2026',
            'No 2027 predictions exist until a matching dated 2027 table is generated',
        ],
    }
    json_write(output_dir / 'bundle_manifest.json', manifest)
    print(f'Bundle {date_code}: train through {train_through}, calibrate {sorted(map(int, years))}; '
          f'fixed features={len(features)}, offset={offset:.4f}; {output_dir}', flush=True)
    return manifest


def infer_bundle(df: pd.DataFrame, meta: dict, *, bundle_dir: Path) -> pd.DataFrame:
    """Refuse wrong-season or wrong-date inputs rather than make fake live predictions."""
    manifest = json.loads((Path(bundle_dir) / 'bundle_manifest.json').read_text())
    if manifest['bundle_type'] != '2027_satellite_proxy_staging':
        raise ValueError('Unsupported bundle format')
    if meta.get('as_of') != manifest['decision_date'] or meta.get('area') != manifest['area']:
        raise ValueError('Prediction table as_of or area differs from trained bundle')
    validate_table(df, meta)
    if not (df['season'].astype(int) == 2027).all():
        raise ValueError('Only 2027 rows are accepted')
    if df['target_crop'].notna().any() or df['target_spring_peak_ndvi'].notna().any():
        raise ValueError('Live prediction targets must be empty')
    features = manifest['features']
    if any(f not in meta['features'] for f in features):
        raise ValueError('Matching JSON metadata is missing trained features')
    x = make_features(df, features)
    def model(cls, filename):
        m = cls()
        m.load_model(str(Path(bundle_dir) / filename))
        return m
    crop = model(XGBClassifier, 'crop_xgb.json')
    vig = model(XGBRegressor, 'vigour_xgb.json')
    lo = model(XGBRegressor, 'vigour_q10_xgb.json')
    hi = model(XGBRegressor, 'vigour_q90_xgb.json')
    p = np.asarray(crop.predict_proba(x)[:, 1], dtype=float)
    if manifest['crop_probability_method'] == 'sigmoid':
        calibrator = joblib.load(Path(bundle_dir) / 'crop_sigmoid_calibrator.joblib')
        p = calibrator.predict_proba(np.log(np.clip(p, 1e-6, 1-1e-6) / (1 - np.clip(p, 1e-6, 1-1e-6))).reshape(-1, 1))[:, 1]
    elif manifest['crop_probability_method'] != 'raw':
        raise ValueError('Unsupported crop probability method')
    bound_lo, bound_hi = interval_bounds(lo.predict(x), hi.predict(x))
    correction = float(manifest['conformal_offset_ndvi'])
    result = df[[c for c in ('season', 'pixel_id', 'lon', 'lat', 'decision_date') if c in df]].copy()
    result['pred_spring_peak_ndvi'] = vig.predict(x)
    result['ndvi_interval_lower_80_target'] = bound_lo - correction
    result['ndvi_interval_upper_80_target'] = bound_hi + correction
    result['crop_proxy_probability_experimental'] = np.clip(p, 0, 1)
    result['prediction_status'] = 'experimental_satellite_proxy_not_farm_validated'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', choices=SUPPORTED_DATES, required=True)
    parser.add_argument('--input-dir', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT / 'deployment_staging' / '2027')
    parser.add_argument('--predict-table', type=Path)
    parser.add_argument('--skip-train', action='store_true', help='Load an existing bundle and predict only')
    parser.add_argument('--estimators', type=int, default=350)
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args(argv)
    folder = args.output_dir / args.date
    if not args.skip_train:
        path = args.input_dir / f'{TABLES[args.date]}.parquet'
        df, meta = load_pair(path)
        create_2027_bundle(df, meta, date_code=args.date, output_dir=folder,
                           estimators=args.estimators, device=args.device,
                           seed=args.seed, table_path=path)
    if args.predict_table:
        table, meta = load_pair(args.predict_table)
        predictions = infer_bundle(table, meta, bundle_dir=folder)
        output = folder / 'predict_2027.csv.gz'
        predictions.to_csv(output, index=False, compression='gzip')
        print(f'2027 satellite proxy predictions: {output} ({len(predictions)} pixels)')
    elif args.skip_train:
        parser.error('--skip-train requires --predict-table')


if __name__ == '__main__':
    main()
