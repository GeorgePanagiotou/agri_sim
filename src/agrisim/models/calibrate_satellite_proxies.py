"""Time-ordered uncertainty-calibration experiment for AgriSim satellite proxies.

NO farm-observed outcomes, yield, crop species, or validated agronomic advice.

Strictly disjoint season groups (default):
  fit base XGBoost models: 2002..2013
  fit isotonic/CQR calibrators: 2014..2017
  evaluate once on future seasons: 2018..2026

WARNING: This is an *evaluation experiment*, NOT a drop-in calibration of the
existing production JSON models, which were fitted through 2026.

Fixed split (unchanged):
  uv run --extra ml python -m agrisim.models.calibrate_satellite_proxies --date 0301
Rolling-origin evaluation (new):
  uv run --extra ml python -m agrisim.models.calibrate_satellite_proxies --date 0301 --rolling
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, mean_absolute_error, mean_squared_error, roc_auc_score
from xgboost import XGBRegressor

from .train_satellite_proxies import (
    TABLES,
    DEFAULT_INPUT,
    DEFAULT_OUTPUT,
    fit_model,
    json_write,
    load_pair,
    make_features,
    select_features,
    trainable_features,
)

DATE_META = {"1114": "11-14", "1201": "12-01", "0201": "02-01",
             "0301": "03-01", "0401": "04-01"}


def finite_quantile(values: np.ndarray, proportion: float) -> float:
    """Upper empirical quantile, explicit noninterpolating NumPy convention."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        raise ValueError("Cannot take a quantile of zero valid scores")
    return float(np.quantile(values, proportion, method="higher"))


def season_aware_cqr_offset(
    y: np.ndarray, lower: np.ndarray, upper: np.ndarray,
    seasons: np.ndarray, *, coverage: float = 0.80,
) -> tuple[float, dict[str, float]]:
    """Conservative group-aware CQR offset.

    Each calibration season contributes its own desired-coverage conformity
    quantile; take the conservative maximum across calibration seasons. This
    protects against pooling 20,000 correlated pixels as if independent, but
    does NOT guarantee future-season coverage under temporal shift.
    """
    if not 0 < coverage < 1:
        raise ValueError("coverage must be between 0 and 1")
    y, lower, upper, seasons = map(np.asarray, (y, lower, upper, seasons))
    valid = np.isfinite(y) & np.isfinite(lower) & np.isfinite(upper)
    if not valid.any():
        raise ValueError("No valid calibration regression targets")
    scores = np.maximum(lower[valid] - y[valid], y[valid] - upper[valid])
    season_valid = seasons[valid]
    by_season: dict[str, float] = {}
    for season in np.unique(season_valid):
        mask = season_valid == season
        by_season[str(int(season))] = finite_quantile(scores[mask], coverage)
    if len(by_season) < 3:
        raise ValueError("Need at least 3 distinct calibration seasons")
    # No narrowing raw quantile intervals; conservative correction only.
    return max(0.0, max(by_season.values())), by_season


def numeric_labels(df: pd.DataFrame, name: str) -> np.ndarray:
    return pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)


def make_quantile_model(alpha: float, *, estimators: int = 350, device: str = "cpu",
                        seed: int = 42) -> XGBRegressor:
    return XGBRegressor(
        objective="reg:quantileerror", quantile_alpha=float(alpha),
        n_estimators=estimators, max_depth=4, learning_rate=0.045,
        min_child_weight=25, subsample=0.85, colsample_bytree=0.85,
        reg_lambda=7.0, tree_method="hist", device=device,
        n_jobs=8, random_state=seed,
    )


def interval_bounds(lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Guard independently fitted quantiles against crossings."""
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    return np.minimum(lo, hi), np.maximum(lo, hi)


def _brier(y: np.ndarray, p: np.ndarray) -> float | None:
    mask = np.isfinite(y) & np.isfinite(p)
    if not mask.any():
        return None
    return float(brier_score_loss(y[mask].astype(int), p[mask]))


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    mask = np.isfinite(y) & np.isfinite(p)
    if len(set(y[mask].astype(int))) < 2:
        return None
    return float(roc_auc_score(y[mask].astype(int), p[mask]))


def _regression(y: np.ndarray, p: np.ndarray) -> dict:
    m = np.isfinite(y) & np.isfinite(p)
    if not m.any():
        return {"rmse": None, "mae": None}
    return {"rmse": float(np.sqrt(mean_squared_error(y[m], p[m]))),
            "mae": float(mean_absolute_error(y[m], p[m]))}


def _coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> tuple[float | None, float | None]:
    m = np.isfinite(y) & np.isfinite(lo) & np.isfinite(hi)
    if not m.any():
        return None, None
    return (float(np.mean((lo[m] <= y[m]) & (y[m] <= hi[m]))),
            float(np.mean(hi[m] - lo[m])))


def evaluate_split(df: pd.DataFrame, meta: dict, *,
                   date_code: str = "0301", output: Path,
                   train_through: int = 2013, calibration_through: int = 2017,
                   estimators: int = 350, device: str = "cpu", seed: int = 42,
                   nominal_coverage: float = 0.80) -> dict:
    """Fit fresh base models, calibrate on untouched seasons, evaluate later."""
    if date_code not in DATE_META or meta["as_of"] != DATE_META[date_code]:
        raise ValueError("Decision-date code does not match JSON metadata")
    if train_through >= calibration_through:
        raise ValueError("Calibration seasons must be later than training seasons")
    if not 0 < nominal_coverage < 1:
        raise ValueError("nominal_coverage must be between 0 and 1")

    season = pd.to_numeric(df["season"], errors="raise").to_numpy(dtype=int)
    fit_rows = season <= train_through
    cal_rows = (season > train_through) & (season <= calibration_through)
    eval_rows = season > calibration_through
    if not (fit_rows.sum() and cal_rows.sum() and eval_rows.sum()):
        raise ValueError("One of train / calibration / evaluation splits is empty")

    # Reuse the exact training-script metadata feature policy and historical
    # masking of 2021 wildfire information; exclude all-missing training cols.
    selected = select_features(meta)
    full = make_features(df, selected)
    features = trainable_features(full, fit_rows)
    x = full[features]
    target_vigour = numeric_labels(df, "target_spring_peak_ndvi")
    target_crop = numeric_labels(df, "target_crop")

    vfit = fit_rows & np.isfinite(target_vigour)
    vcal = cal_rows & np.isfinite(target_vigour)
    veval = eval_rows & np.isfinite(target_vigour)
    cfit = fit_rows & np.isfinite(target_crop)
    ccal = cal_rows & np.isfinite(target_crop)
    ceval = eval_rows & np.isfinite(target_crop)
    if min(vfit.sum(), vcal.sum(), veval.sum(), cfit.sum(), ccal.sum(), ceval.sum()) < 20:
        raise ValueError("Insufficient labeled records in one or more splits")

    print(f"[{date_code}] train seasons <= {train_through}, calibrate {train_through+1}..{calibration_through}, evaluate {calibration_through+1}+", flush=True)
    print(f"  fit/cal/test rows: {fit_rows.sum()} / {cal_rows.sum()} / {eval_rows.sum()}; features: {len(features)}", flush=True)

    # These are fresh models, not the JSON production models trained through 2026.
    crop = fit_model(x, target_crop, cfit, "crop", device, estimators, seed)
    point = fit_model(x, target_vigour, vfit, "vigour", device, estimators, seed)
    qlower = make_quantile_model((1 - nominal_coverage) / 2, estimators=estimators,
                                 device=device, seed=seed)
    qupper = make_quantile_model(1 - (1 - nominal_coverage) / 2, estimators=estimators,
                                 device=device, seed=seed)
    qlower.fit(x.loc[vfit], target_vigour[vfit])
    qupper.fit(x.loc[vfit], target_vigour[vfit])

    # The calibration set was NOT used to fit any of the base models.
    raw_cal_crop = crop.predict_proba(x.loc[ccal])[:, 1]
    calibrator = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
    calibrator.fit(raw_cal_crop, target_crop[ccal].astype(int))

    cal_lo, cal_hi = interval_bounds(qlower.predict(x.loc[vcal]),
                                     qupper.predict(x.loc[vcal]))
    correction, per_cal_season = season_aware_cqr_offset(
        target_vigour[vcal], cal_lo, cal_hi, season[vcal],
        coverage=nominal_coverage,
    )

    # Untouched future-season evaluation. No tuning or model fitting below.
    raw_test_crop = crop.predict_proba(x.loc[ceval])[:, 1]
    calibrated_test_crop = np.asarray(calibrator.predict(raw_test_crop), dtype=float)
    point_pred = point.predict(x.loc[veval])
    test_lo, test_hi = interval_bounds(qlower.predict(x.loc[veval]),
                                       qupper.predict(x.loc[veval]))
    pred_lo, pred_hi = test_lo - correction, test_hi + correction

    prediction = df.loc[eval_rows, ["season", "pixel_id"]].copy()
    prediction["actual_vigour"] = target_vigour[eval_rows]
    prediction["point_vigour"] = np.nan
    prediction["raw_q10"] = np.nan
    prediction["raw_q90"] = np.nan
    prediction["calibrated_lower"] = np.nan
    prediction["calibrated_upper"] = np.nan
    prediction["actual_crop"] = target_crop[eval_rows]
    prediction["crop_probability_raw"] = np.nan
    prediction["crop_probability_calibrated"] = np.nan
    prediction.loc[veval[eval_rows], "point_vigour"] = point_pred
    prediction.loc[veval[eval_rows], "raw_q10"] = test_lo
    prediction.loc[veval[eval_rows], "raw_q90"] = test_hi
    prediction.loc[veval[eval_rows], "calibrated_lower"] = pred_lo
    prediction.loc[veval[eval_rows], "calibrated_upper"] = pred_hi
    prediction.loc[ceval[eval_rows], "crop_probability_raw"] = raw_test_crop
    prediction.loc[ceval[eval_rows], "crop_probability_calibrated"] = calibrated_test_crop

    reports = []
    for year, one in prediction.groupby("season", sort=True):
        yy = one["actual_vigour"].to_numpy(dtype=float)
        raw_cov, raw_width = _coverage(yy, one["raw_q10"].to_numpy(), one["raw_q90"].to_numpy())
        cqr_cov, cqr_width = _coverage(yy, one["calibrated_lower"].to_numpy(),
                                       one["calibrated_upper"].to_numpy())
        yc = one["actual_crop"].to_numpy(dtype=float)
        rp = one["crop_probability_raw"].to_numpy(dtype=float)
        cp = one["crop_probability_calibrated"].to_numpy(dtype=float)
        reports.append({
            "season": int(year), "rows": int(len(one)),
            "vigour_rmse": _regression(yy, one["point_vigour"].to_numpy())["rmse"],
            "raw_coverage": raw_cov, "cqr_coverage": cqr_cov,
            "raw_interval_width": raw_width, "cqr_interval_width": cqr_width,
            "crop_raw_brier": _brier(yc, rp), "crop_calibrated_brier": _brier(yc, cp),
            "crop_raw_auc": _auc(yc, rp), "crop_calibrated_auc": _auc(yc, cp),
        })
    per_season = pd.DataFrame(reports)
    all_v = prediction["actual_vigour"].to_numpy(dtype=float)
    raw_coverage, raw_width = _coverage(all_v, prediction["raw_q10"].to_numpy(),
                                        prediction["raw_q90"].to_numpy())
    cqr_coverage, cqr_width = _coverage(all_v, prediction["calibrated_lower"].to_numpy(),
                                        prediction["calibrated_upper"].to_numpy())
    all_crop = prediction["actual_crop"].to_numpy(dtype=float)
    report = {
        "evaluation_type": "strictly_forward_train_calibrate_evaluate",
        "model_status": "experimental; not a calibrated replacement for production models",
        "date_code": date_code, "decision_date": meta["as_of"], "area": meta.get("area"),
        "train_seasons": sorted(map(int, np.unique(season[fit_rows]))),
        "calibration_seasons": sorted(map(int, np.unique(season[cal_rows]))),
        "evaluation_seasons": sorted(map(int, np.unique(season[eval_rows]))),
        "features": features, "dropped_all_missing_features": sorted(set(selected)-set(features)),
        "nominal_interval_coverage": nominal_coverage,
        "conformal_method": "maximum_of_per_calibration_season_empirical_coverage_quantiles",
        "conformal_offset_ndvi": correction,
        "calibration_season_offsets": per_cal_season,
        "results": {
            "vigour": {"point": _regression(all_v, prediction["point_vigour"].to_numpy()),
                        "raw_interval_coverage": raw_coverage, "raw_mean_width": raw_width,
                        "cqr_interval_coverage": cqr_coverage, "cqr_mean_width": cqr_width},
            "crop": {"raw_brier": _brier(all_crop, prediction["crop_probability_raw"].to_numpy()),
                     "calibrated_brier": _brier(all_crop, prediction["crop_probability_calibrated"].to_numpy()),
                     "raw_roc_auc": _auc(all_crop, prediction["crop_probability_raw"].to_numpy()),
                     "calibrated_roc_auc": _auc(all_crop, prediction["crop_probability_calibrated"].to_numpy())},
        },
        "limitations": [
            "Satellite-derived proxy targets; no independent farm labels or crop yield validation",
            "Future seasons and 2026 seasonal shifts may violate exchangeability; 80% is a target, not a guarantee",
            "Nearby pixels are correlated; group-based offset is conservative but not distribution-free for nonstationary seasons",
            "Historic class thresholds were defined with later-season data; residual label hindsight remains",
            "Static soil layers might not represent conditions in early historical seasons",
            "These models were fitted only through the training cutoff; existing production models must NOT be calibrated with these saved artifacts",
        ],
    }

    output.mkdir(parents=True, exist_ok=True)
    crop.save_model(str(output / "crop_base_calibration_split.json"))
    point.save_model(str(output / "vigour_point_calibration_split.json"))
    qlower.save_model(str(output / "vigour_q10_calibration_split.json"))
    qupper.save_model(str(output / "vigour_q90_calibration_split.json"))
    joblib.dump(calibrator, output / "crop_isotonic_calibrator.joblib")
    per_season.to_csv(output / "calibration_by_season.csv", index=False)
    prediction.to_csv(output / "evaluation_predictions.csv.gz", compression="gzip", index=False)
    json_write(output / "calibration_manifest.json", report)
    print(f"[{date_code}] test raw/CQR coverage: {raw_coverage:.3f} / {cqr_coverage:.3f}; "
          f"crop raw/isotonic Brier: {report['results']['crop']['raw_brier']:.4f} / "
          f"{report['results']['crop']['calibrated_brier']:.4f}", flush=True)
    print(f"Report: {output / 'calibration_manifest.json'}", flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", choices=TABLES.keys(), default="0301")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT / "calibration_experiments")
    parser.add_argument("--train-through", type=int, default=2013)
    parser.add_argument("--calibration-through", type=int, default=2017)
    parser.add_argument("--estimators", type=int, default=350)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rolling", action="store_true", help="Time-ordered rolling-origin season evaluation")
    parser.add_argument("--start-season", type=int, default=2018)
    parser.add_argument("--end-season", type=int, default=2026)
    parser.add_argument("--calibration-seasons", type=int, default=3)
    parser.add_argument("--save-fold-models", action="store_true")
    args = parser.parse_args(argv)
    table, meta = load_pair(args.input_dir / f"{TABLES[args.date]}.parquet")
    if args.rolling:
        from .calibrate_satellite_rolling import run_rolling_calibration
        run_rolling_calibration(table, meta, date_code=args.date,
                                output=args.output_dir / "rolling" / args.date,
                                start_season=args.start_season, end_season=args.end_season,
                                calibration_seasons=args.calibration_seasons,
                                estimators=args.estimators, device=args.device, seed=args.seed,
                                save_fold_models=args.save_fold_models)
    else:
        evaluate_split(table, meta, date_code=args.date, output=args.output_dir / args.date,
                       train_through=args.train_through, calibration_through=args.calibration_through,
                       estimators=args.estimators, device=args.device, seed=args.seed)


if __name__ == "__main__":
    main()
