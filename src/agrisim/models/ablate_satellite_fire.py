"""Compare rolling dynamic wildfire feature availability vs frozen no-fire features.

Quick, useful 2026 ablation:
  python -m agrisim.models.ablate_satellite_fire --date 0301 --start-season 2026
  python -m agrisim.models.ablate_satellite_fire --date 0401 --start-season 2026

WARNING: Does not select a calibrated production model; evaluation only.
"""
from __future__ import annotations
import argparse
from pathlib import Path

import pandas as pd
from .train_satellite_proxies import DEFAULT_INPUT, DEFAULT_OUTPUT, TABLES, json_write, load_pair
from .calibrate_satellite_rolling import run_rolling_calibration


def run_ablation(df, meta, *, date_code: str, output_dir: Path,
                 start_season: int = 2026, end_season: int = 2026,
                 estimators: int = 350, device: str = 'cpu', seed: int = 42) -> dict:
    result = {}
    for variant, fixed in [('dynamic_fire', False), ('fixed_no_fire', True)]:
        folder = Path(output_dir) / variant
        result[variant] = run_rolling_calibration(
            df, meta, date_code=date_code, output=folder,
            start_season=start_season, end_season=end_season,
            estimators=estimators, device=device, seed=seed, fixed_features=fixed)
    original = pd.read_csv(Path(output_dir) / 'dynamic_fire' / 'rolling_by_season.csv')
    fixed = pd.read_csv(Path(output_dir) / 'fixed_no_fire' / 'rolling_by_season.csv')
    metrics = ['vigour_rmse', 'cqr_coverage', 'cqr_interval_width',
               'crop_raw_brier', 'crop_sigmoid_brier', 'crop_isotonic_brier',
               'crop_raw_roc_auc', 'crop_sigmoid_roc_auc', 'crop_isotonic_roc_auc']
    merge = original[['season', 'features', *metrics]].merge(
        fixed[['season', 'features', *metrics]], on='season', how='inner',
        suffixes=('_dynamic', '_fixed'), validate='one_to_one')
    if merge.empty:
        raise ValueError('No matching seasons in the ablation variants')
    for metric in metrics:
        merge[f'delta_fixed_minus_dynamic_{metric}'] = (
            merge[f'{metric}_fixed'] - merge[f'{metric}_dynamic'])
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    merge.to_csv(Path(output_dir) / 'ablation_by_season.csv', index=False)
    summary = {'date_code': date_code, 'seasons': merge.season.astype(int).tolist(),
               'variants': ['dynamic_fire', 'fixed_no_fire'],
               'delta_definition': 'fixed_no_fire minus dynamic_fire',
               'delta_interpretation': 'RMSE and Brier negative=better; coverage closer to target 0.8; ROC-AUC positive=better',
               'comparison': merge.to_dict(orient='records'),
               'notes': [
                   'Wildfire features enter dynamic rolling training only when post-2021 seasons available',
                   'The comparison is retrospective and not a prospective validation of 2027 models',
                   'Do not compare 2026 ablation against historical manifest from different estimator settings',
               ]}
    json_write(Path(output_dir) / 'ablation_manifest.json', summary)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date', choices=('0301', '0401'), required=True)
    ap.add_argument('--input-dir', type=Path, default=DEFAULT_INPUT)
    ap.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT / 'calibration_experiments' / 'fire_ablation')
    ap.add_argument('--start-season', type=int, default=2026)
    ap.add_argument('--end-season', type=int, default=2026)
    ap.add_argument('--estimators', type=int, default=350)
    ap.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args(argv)
    df, meta = load_pair(args.input_dir / f'{TABLES[args.date]}.parquet')
    output = args.output_dir / args.date
    summary = run_ablation(df, meta, date_code=args.date, output_dir=output,
                           start_season=args.start_season, end_season=args.end_season,
                           estimators=args.estimators, device=args.device, seed=args.seed)
    print(f'Ablation saved: {output / "ablation_by_season.csv"}')
    for row in summary['comparison']:
        print(f"{int(row['season'])}: features dynamic/fixed={int(row['features_dynamic'])}/{int(row['features_fixed'])}, "
              f"RMSE delta={row['delta_fixed_minus_dynamic_vigour_rmse']:.5f}, "
              f"crop raw Brier delta={row['delta_fixed_minus_dynamic_crop_raw_brier']:.5f}")


if __name__ == '__main__':
    main()
