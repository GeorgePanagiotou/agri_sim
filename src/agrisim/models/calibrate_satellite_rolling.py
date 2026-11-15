"""Rolling-origin uncertainty evaluation for AgriSim satellite proxy targets.

Each test season T uses ONLY:
  * training:      seasons <= T - calibration_seasons - 1
  * calibration:   T - calibration_seasons ... T - 1
  * evaluation:    season T

No evaluation-season row can influence its own fitted model, quantile offset,
or probability calibrators. Historical test seasons are permitted in LATER
folds, because those outcomes would have been observable by then (prequential
/ forward-chaining evaluation).

Methods: raw crop XGBoost probabilities vs Platt sigmoid and isotonic;
XGBoost q10/q90 NDVI bands vs season-aware conformalized quantiles (CQR).

Satellite-derived proxies, NOT independently observed field establishment,
crop type, yields, or agronomic recommendations. No claim of distribution-free
season-level guarantee under temporal drift. Does NOT change production models.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .train_satellite_proxies import (
    TABLES, DEFAULT_INPUT, DEFAULT_OUTPUT, fit_model, json_write,
    load_pair, make_features, select_features, trainable_features,
    FUTURE_FIRE_COLUMNS,
)
from .calibrate_satellite_proxies import (
    DATE_META, _auc, _brier, _coverage, _regression, interval_bounds,
    make_quantile_model, numeric_labels, season_aware_cqr_offset,
)


@dataclass(frozen=True)
class SeasonSplit:
    evaluation: int
    train: tuple[int, ...]
    calibration: tuple[int, ...]


def season_splits(seasons, *, start_season: int = 2018, end_season: int | None = 2026,
                  calibration_seasons: int = 3, minimum_training_seasons: int = 6
                  ) -> list[SeasonSplit]:
    """Return deterministic, disjoint, strictly time-ordered rolling splits.

    Restrict historical years to years present in the input table. If a season
    is absent, use the preceding N *available* whole seasons for calibration.
    """
    distinct = sorted({int(year) for year in seasons})
    if calibration_seasons < 3:
        raise ValueError("At least three calibration seasons are required")
    if minimum_training_seasons < 2:
        raise ValueError("Need at least two training seasons")
    if end_season is not None and start_season > end_season:
        raise ValueError("start_season must be <= end_season")
    result = []
    for eval_year in distinct:
        if eval_year < start_season or (end_season is not None and eval_year > end_season):
            continue
        earlier = [year for year in distinct if year < eval_year]
        if len(earlier) < calibration_seasons + minimum_training_seasons:
            raise ValueError(f"Not enough previous seasons for evaluation {eval_year}")
        calibration = tuple(earlier[-calibration_seasons:])
        training = tuple(earlier[:-calibration_seasons])
        assert max(training) < min(calibration) < eval_year
        result.append(SeasonSplit(eval_year, training, calibration))
    if not result:
        raise ValueError("No test seasons available in requested period")
    return result


def season_equal_weights(seasons: np.ndarray) -> np.ndarray:
    """Keep each calibration SEASON equally weighted in the probability fit."""
    seasons = np.asarray(seasons, dtype=int)
    if not seasons.size:
        raise ValueError("No calibration seasons")
    counts = {int(y): int(np.sum(seasons == y)) for y in np.unique(seasons)}
    weights = np.array([1 / counts[int(y)] for y in seasons], dtype=float)
    return weights * len(weights) / weights.sum()


def _logits(p: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def fit_probability_calibrators(raw_cal: np.ndarray, labels: np.ndarray,
                                seasons: np.ndarray):
    """Fit monotone Platt sigmoid and isotonic on out-of-training seasons."""
    raw_cal = np.asarray(raw_cal, dtype=float)
    labels = np.asarray(labels, dtype=int)
    if np.any(~np.isfinite(raw_cal)) or not set(np.unique(labels)) == {0, 1}:
        raise ValueError("Calibration needs finite probabilities and both crop classes")
    weights = season_equal_weights(np.asarray(seasons))
    sigmoid = LogisticRegression(C=1.0, max_iter=500, solver="lbfgs")
    sigmoid.fit(_logits(raw_cal), labels, sample_weight=weights)
    iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
    iso.fit(raw_cal, labels, sample_weight=weights)
    return sigmoid, iso


def probability_predictions(raw: np.ndarray, sigmoid, isotonic) -> dict[str, np.ndarray]:
    raw = np.asarray(raw, dtype=float)
    return {
        "raw": np.clip(raw, 0, 1),
        "sigmoid": np.clip(sigmoid.predict_proba(_logits(raw))[:, 1], 0, 1),
        "isotonic": np.clip(np.asarray(isotonic.predict(raw), dtype=float), 0, 1),
    }


def reliability_table(df: pd.DataFrame, *, bins: int = 10,
                      include_season: bool = False) -> pd.DataFrame:
    """Fixed-width comparable probability bins with actual counts/mean outcomes."""
    if bins < 3:
        raise ValueError("Need >= 3 reliability bins")
    records = []
    grouping = df.groupby("season", sort=True) if include_season else [(None, df)]
    for year, part in grouping:
        labels = pd.to_numeric(part["actual_crop"], errors="coerce").to_numpy(dtype=float)
        for method in ("raw", "sigmoid", "isotonic"):
            p = pd.to_numeric(part[f"crop_probability_{method}"], errors="coerce").to_numpy(dtype=float)
            valid = np.isfinite(p) & np.isfinite(labels)
            if not valid.any():
                continue
            ids = np.minimum((np.clip(p[valid], 0, 1) * bins).astype(int), bins - 1)
            for k in range(bins):
                in_bin = ids == k
                if not in_bin.any():
                    continue
                row = {"method": method, "bin": k,
                       "bin_low": k / bins, "bin_high": (k + 1) / bins,
                       "count": int(in_bin.sum()),
                       "mean_prediction": float(np.mean(p[valid][in_bin])),
                       "observed_frequency": float(np.mean(labels[valid][in_bin]))}
                if include_season:
                    row = {"season": int(year), **row}
                records.append(row)
    return pd.DataFrame(records)


def _xml_chart(path: Path, *, title: str, subtitle: str,
               x_label: str, y_label: str, series: dict[str, list[tuple[float, float]]],
               x_domain=(0.0, 1.0), y_domain=(0.0, 1.0), diagonal: bool = False,
               target_line: float | None = None) -> None:
    """Write a self-contained SVG chart, without matplotlib/app dependencies."""
    width, height = 850, 570
    left, right, top, bottom = 105, 820, 120, 470
    xlo, xhi = x_domain
    ylo, yhi = y_domain
    if xhi <= xlo or yhi <= ylo:
        raise ValueError("Invalid chart domain")
    tx = lambda x: left + (x - xlo) / (xhi - xlo) * (right - left)
    ty = lambda y: bottom - (y - ylo) / (yhi - ylo) * (bottom - top)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#ffffff"/>',
             f'<text x="{left}" y="39" fill="#202b35" font-family="Arial,sans-serif" font-size="23" font-weight="bold">{html.escape(title)}</text>',
             f'<text x="{left}" y="67" fill="#586b79" font-family="Arial,sans-serif" font-size="13">{html.escape(subtitle)}</text>']
    for k in range(6):
        ratio = k / 5
        y = top + ratio * (bottom - top)
        x = left + ratio * (right - left)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{right}" y2="{y:.2f}" stroke="#e7edf1"/>')
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{bottom}" stroke="#e7edf1"/>')
        parts.append(f'<text x="{left-13}" y="{y+4:.2f}" text-anchor="end" fill="#687881" font-family="Arial" font-size="12">{yhi-ratio*(yhi-ylo):.2f}</text>')
        parts.append(f'<text x="{x:.2f}" y="{bottom+24}" text-anchor="middle" fill="#687881" font-family="Arial" font-size="12">{xlo+ratio*(xhi-xlo):.2f}</text>')
    parts.append(f'<text x="{(left+right)/2:.2f}" y="{height-40}" text-anchor="middle" fill="#243744" font-family="Arial" font-size="14">{html.escape(x_label)}</text>')
    parts.append(f'<text x="28" y="{(top+bottom)/2}" text-anchor="middle" transform="rotate(-90 28 {(top+bottom)/2})" fill="#243744" font-family="Arial" font-size="14">{html.escape(y_label)}</text>')
    if diagonal:
        parts.append(f'<line x1="{tx(0):.2f}" y1="{ty(0):.2f}" x2="{tx(1):.2f}" y2="{ty(1):.2f}" stroke="#a5a5a5" stroke-width="2" stroke-dasharray="5,6"/>')
    if target_line is not None:
        parts.append(f'<line x1="{left}" y1="{ty(target_line):.2f}" x2="{right}" y2="{ty(target_line):.2f}" stroke="#6b7280" stroke-width="2" stroke-dasharray="5,5"/>')
    palette = {"raw": "#3559ba", "sigmoid": "#008675", "isotonic": "#d18e16",
               "raw_coverage": "#3559ba", "cqr_coverage": "#008675"}
    for ix, (name, points) in enumerate(series.items()):
        color = palette.get(name, ("#3559ba", "#008675", "#d18e16")[ix % 3])
        pts = [(float(x), float(y)) for x, y in points if np.isfinite(x) and np.isfinite(y)]
        if not pts:
            continue
        dots = " ".join(f"{tx(x):.1f},{ty(y):.1f}" for x, y in pts)
        parts.append(f'<polyline points="{dots}" fill="none" stroke="{color}" stroke-width="2.2"/>')
        for x, y in pts:
            parts.append(f'<circle cx="{tx(x):.2f}" cy="{ty(y):.2f}" r="4.5" fill="{color}" stroke="#ffffff" stroke-width="1.3"/>')
        legend_x = left + ix * 178
        parts.append(f'<circle cx="{legend_x}" cy="{height-16}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{legend_x+10}" y="{height-12}" fill="#344956" font-family="Arial" font-size="12">{html.escape(name.replace("_", " ").title())}</text>')
    parts.append('</svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def write_visualizations(folder: Path, bins: pd.DataFrame,
                         per_season: pd.DataFrame, target: float) -> None:
    series = {}
    for method in ("raw", "sigmoid", "isotonic"):
        one = bins[bins.method == method].sort_values("mean_prediction")
        series[method] = list(zip(one.mean_prediction.to_numpy(), one.observed_frequency.to_numpy()))
    _xml_chart(folder / "crop_reliability_diagram.svg",
               title="Crop presence: rolling-origin reliability",
               subtitle="Season-forward evaluation only; satellite-derived proxy crop labels",
               x_label="Mean predicted probability", y_label="Observed crop frequency",
               series=series, diagonal=True)
    years = per_season["season"].astype(float).to_numpy()
    start, end = float(np.min(years)), float(np.max(years))
    if start == end:
        start -= 0.5
        end += 0.5
    _xml_chart(folder / "ndvi_coverage_by_season.svg",
               title="NDVI interval coverage by evaluation season",
               subtitle=f"Nominal target {target:.0%}; intervals may fail under seasonal shift",
               x_label="Agricultural season", y_label="Observed coverage",
               series={"raw_coverage": list(zip(years, per_season.raw_coverage)),
                       "cqr_coverage": list(zip(years, per_season.cqr_coverage))},
               x_domain=(start, end), y_domain=(0, 1), target_line=target)


def _aggregate_metrics(predictions: pd.DataFrame) -> dict:
    yv = predictions["actual_vigour"].to_numpy(dtype=float)
    yc = predictions["actual_crop"].to_numpy(dtype=float)
    result = {"ndvi": {"point": _regression(yv, predictions["point_vigour"].to_numpy(dtype=float))}}
    for key, lo, hi in (("raw", "raw_lower", "raw_upper"),
                        ("conformal", "conformal_lower", "conformal_upper")):
        coverage, width = _coverage(yv, predictions[lo].to_numpy(dtype=float), predictions[hi].to_numpy(dtype=float))
        result["ndvi"][key] = {"coverage": coverage, "mean_width": width}
    result["crop"] = {}
    for method in ("raw", "sigmoid", "isotonic"):
        p = predictions[f"crop_probability_{method}"].to_numpy(dtype=float)
        result["crop"][method] = {"brier": _brier(yc, p), "roc_auc": _auc(yc, p)}
    return result


def run_rolling_calibration(df: pd.DataFrame, meta: dict, *,
                            date_code: str, output: Path,
                            start_season: int = 2018, end_season: int = 2026,
                            calibration_seasons: int = 3, minimum_training_seasons: int = 6,
                            estimators: int = 350, device: str = "cpu", seed: int = 42,
                            nominal_coverage: float = .80,
                            save_fold_models: bool = False,
                            fixed_features: bool = False) -> dict:
    """Run rolling-origin evaluation; output is ANALYSIS ONLY, not production."""
    if date_code not in DATE_META or meta["as_of"] != DATE_META[date_code]:
        raise ValueError("date_code does not match table JSON as_of")
    if not 0 < nominal_coverage < 1:
        raise ValueError("nominal_coverage must be strictly between 0 and 1")
    if estimators < 2:
        raise ValueError("estimators must be >= 2")
    from .train_satellite_proxies import validate_table
    validate_table(df, meta)
    season = df["season"].astype(int).to_numpy()
    folds = season_splits(season, start_season=start_season, end_season=end_season,
                          calibration_seasons=calibration_seasons,
                          minimum_training_seasons=minimum_training_seasons)
    selected = select_features(meta)
    if fixed_features:
        selected = [name for name in selected if name not in FUTURE_FIRE_COLUMNS]
    full_features = make_features(df, selected)
    yvig = numeric_labels(df, "target_spring_peak_ndvi")
    ycrop = numeric_labels(df, "target_crop")
    output.mkdir(parents=True, exist_ok=True)
    all_predictions = []
    fold_metadata = []
    rows = []

    for fold_number, fold in enumerate(folds, start=1):
        train = np.isin(season, fold.train)
        cal = np.isin(season, fold.calibration)
        test = season == fold.evaluation
        assert not np.any(train & cal) and not np.any(test & train) and not np.any(test & cal)
        features = trainable_features(full_features, train & np.isfinite(yvig) & np.isfinite(ycrop))
        x = full_features[features]
        vf = train & np.isfinite(yvig)
        vc = cal & np.isfinite(yvig)
        vt = test & np.isfinite(yvig)
        cf = train & np.isfinite(ycrop)
        cc = cal & np.isfinite(ycrop)
        ct = test & np.isfinite(ycrop)
        if min(map(np.count_nonzero, (vf, vc, vt, cf, cc, ct))) < 100:
            raise ValueError(f"Insufficient labeled rows in a fold for season {fold.evaluation}")
        if len(np.unique(season[vc])) < 3 or len(np.unique(season[cc])) < 3:
            raise ValueError("At least 3 valid calibration seasons for each task are required")
        print(f"[{date_code} fold {fold_number}/{len(folds)}] train {fold.train[0]}–{fold.train[-1]}, "
              f"cal {fold.calibration[0]}–{fold.calibration[-1]}, test {fold.evaluation}, "
              f"features={len(features)}", flush=True)

        crop = fit_model(x, ycrop, cf, "crop", device, estimators, seed)
        vigour = fit_model(x, yvig, vf, "vigour", device, estimators, seed)
        q10 = make_quantile_model((1 - nominal_coverage) / 2,
                                  estimators=estimators, device=device, seed=seed)
        q90 = make_quantile_model(1 - (1 - nominal_coverage) / 2,
                                  estimators=estimators, device=device, seed=seed)
        q10.fit(x.loc[vf], yvig[vf])
        q90.fit(x.loc[vf], yvig[vf])

        cal_prob = crop.predict_proba(x.loc[cc])[:, 1]
        sigmoid, isotonic = fit_probability_calibrators(cal_prob, ycrop[cc], season[cc])
        qcal_lo, qcal_hi = interval_bounds(q10.predict(x.loc[vc]), q90.predict(x.loc[vc]))
        offset, cal_offsets = season_aware_cqr_offset(
            yvig[vc], qcal_lo, qcal_hi, season[vc], coverage=nominal_coverage)

        # Note: labels from EVALUATION season are accessed ONLY for evaluation.
        probabilities = probability_predictions(crop.predict_proba(x.loc[ct])[:, 1], sigmoid, isotonic)
        qtest_lo, qtest_hi = interval_bounds(q10.predict(x.loc[vt]), q90.predict(x.loc[vt]))
        point = vigour.predict(x.loc[vt])
        out = pd.DataFrame({"season": season[test], "pixel_id": df.loc[test, "pixel_id"].to_numpy(),
                            "actual_crop": ycrop[test], "actual_vigour": yvig[test],
                            "crop_probability_raw": np.nan,
                            "crop_probability_sigmoid": np.nan,
                            "crop_probability_isotonic": np.nan,
                            "point_vigour": np.nan, "raw_lower": np.nan, "raw_upper": np.nan,
                            "conformal_lower": np.nan, "conformal_upper": np.nan})
        valid_c = ct[test]
        valid_v = vt[test]
        for method, predicted in probabilities.items():
            out.loc[valid_c, f"crop_probability_{method}"] = predicted
        out.loc[valid_v, "point_vigour"] = point
        out.loc[valid_v, "raw_lower"] = qtest_lo
        out.loc[valid_v, "raw_upper"] = qtest_hi
        out.loc[valid_v, "conformal_lower"] = qtest_lo - offset
        out.loc[valid_v, "conformal_upper"] = qtest_hi + offset
        # Ordering of the dataframe stays aligned with the evaluation rows.
        all_predictions.append(out)
        scores = _aggregate_metrics(out)
        rows.append({"season": fold.evaluation, "rows": int(len(out)),
                     "train_through": fold.train[-1],
                     "calibration_start": fold.calibration[0],
                     "calibration_through": fold.calibration[-1],
                     "features": len(features), "conformal_offset": offset,
                     "vigour_rmse": scores["ndvi"]["point"]["rmse"],
                     "raw_coverage": scores["ndvi"]["raw"]["coverage"],
                     "cqr_coverage": scores["ndvi"]["conformal"]["coverage"],
                     "raw_interval_width": scores["ndvi"]["raw"]["mean_width"],
                     "cqr_interval_width": scores["ndvi"]["conformal"]["mean_width"],
                     **{f"crop_{name}_{metric}": values[metric]
                        for name, values in scores["crop"].items()
                        for metric in ("brier", "roc_auc")}})
        fold_metadata.append({"test_season": fold.evaluation,
                              "train_seasons": list(fold.train), "calibration_seasons": list(fold.calibration),
                              "features": features,
                              "dropped_all_missing_training_features": sorted(set(selected) - set(features)),
                              "cqr_offset": offset, "calibration_season_quantiles": cal_offsets})
        if save_fold_models:
            fold_dir = output / "fold_models" / str(fold.evaluation)
            fold_dir.mkdir(parents=True, exist_ok=True)
            crop.save_model(str(fold_dir / "crop_xgb.json"))
            vigour.save_model(str(fold_dir / "vigour_xgb.json"))
            q10.save_model(str(fold_dir / "vigour_q10_xgb.json"))
            q90.save_model(str(fold_dir / "vigour_q90_xgb.json"))
            import joblib
            joblib.dump({"sigmoid": sigmoid, "isotonic": isotonic,
                         "features": features, "cqr_offset": offset,
                         "train_seasons": fold.train, "calibration_seasons": fold.calibration},
                        fold_dir / "calibration.joblib")

    predictions = pd.concat(all_predictions, ignore_index=True)
    per_year = pd.DataFrame(rows)
    bins = reliability_table(predictions)
    bins_by_season = reliability_table(predictions, include_season=True)
    total_metrics = _aggregate_metrics(predictions)
    report = {
        "evaluation_type": "rolling_origin_forward_season_prequential",
        "feature_variant": "fixed_no_fire" if fixed_features else "dynamic_fire",
        "excluded_future_fire_features": sorted(FUTURE_FIRE_COLUMNS) if fixed_features else [],
        "model_status": "experiment ONLY; no production model re-calibrated or replaced",
        "date_code": date_code,
        "decision_date": meta["as_of"], "area": meta.get("area"),
        "training_table_rows": int(len(df)),
        "evaluation_rows": int(len(predictions)),
        "calibration_seasons_per_fold": calibration_seasons,
        "nominal_interval_coverage": nominal_coverage,
        "cqr_method": "max of per-calibration-season empirical conformity quantiles; offset clamped >=0",
        "probability_methods": ["raw", "sigmoid", "isotonic"],
        "reliability_bins": 10,
        "parameters": {"start_season": start_season, "end_season": end_season,
                       "estimators": estimators, "device": device, "seed": seed,
                       "minimum_training_seasons": minimum_training_seasons},
        "aggregate_metrics": total_metrics,
        "macro_mean_metrics_by_season": {
            "ndvi_cqr_coverage": float(per_year.cqr_coverage.mean()),
            "ndvi_cqr_mean_width": float(per_year.cqr_interval_width.mean()),
            **{f"crop_{method}_brier": float(per_year[f"crop_{method}_brier"].mean())
               for method in ("raw", "sigmoid", "isotonic")},
        },
        "seasons_below_nominal_cqr": per_year.loc[per_year.cqr_coverage < nominal_coverage, "season"].astype(int).tolist(),
        "per_season_win_counts": {
            "cqr_seasons_at_or_above_nominal": int((per_year.cqr_coverage >= nominal_coverage).sum()),
            "crop_sigmoid_brier_better_than_raw": int((per_year.crop_sigmoid_brier < per_year.crop_raw_brier).sum()),
            "crop_isotonic_brier_better_than_raw": int((per_year.crop_isotonic_brier < per_year.crop_raw_brier).sum()),
            "total_evaluation_seasons": int(len(per_year)),
        },
        "method_performance_notes": "No method selected based on these test results; if changing the method, use new unseen seasons or nested tuning",
        "folds": fold_metadata,
        "limitations": [
            "Satellite-derived crop/NDVI proxy labels, not validated farm outcomes",
            "Later-season data influenced historic pseudo-label thresholds; residual hindsight leakage remains",
            "Pixel observations within seasons are spatially dependent: pooled scores are not independent field trials",
            "Historical modern soil layers may be anachronistic for early seasons",
            "CQR uses season-wise maximum correction; no distribution-free future-season 80% guarantee under climate shift",
            "April NDVI includes March observations of the target spring period (in-season monitoring)",
            "Previously saved production models trained through 2026 are not calibrated by this experiment",
        ],
    }
    predictions.to_csv(output / "rolling_evaluation_predictions.csv.gz", index=False, compression="gzip")
    per_year.to_csv(output / "rolling_by_season.csv", index=False)
    bins.to_csv(output / "reliability_bins.csv", index=False)
    bins_by_season.to_csv(output / "reliability_bins_by_season.csv", index=False)
    json_write(output / "rolling_manifest.json", report)
    write_visualizations(output, bins, per_year, nominal_coverage)
    print(f"[{date_code}] pooled CQR coverage {total_metrics['ndvi']['conformal']['coverage']:.3f}; "
          f"mean width {total_metrics['ndvi']['conformal']['mean_width']:.3f}; "
          f"Brier raw/sigmoid/isotonic: "
          f"{total_metrics['crop']['raw']['brier']:.4f}/"
          f"{total_metrics['crop']['sigmoid']['brier']:.4f}/"
          f"{total_metrics['crop']['isotonic']['brier']:.4f}", flush=True)
    print(f"Report: {output / 'rolling_manifest.json'}", flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", choices=TABLES.keys(), default="0301")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT / "calibration_experiments" / "rolling")
    parser.add_argument("--start-season", type=int, default=2018)
    parser.add_argument("--end-season", type=int, default=2026)
    parser.add_argument("--calibration-seasons", type=int, default=3)
    parser.add_argument("--estimators", type=int, default=350)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--nominal-coverage", type=float, default=.8)
    parser.add_argument("--save-fold-models", action="store_true")
    parser.add_argument("--fixed-features", action="store_true",
                        help="Exclude three wildfire severity/upslope features in every rolling fold")
    args = parser.parse_args(argv)
    table, meta = load_pair(args.input_dir / f"{TABLES[args.date]}.parquet")
    run_rolling_calibration(table, meta, date_code=args.date, output=args.output_dir / args.date,
                            start_season=args.start_season, end_season=args.end_season,
                            calibration_seasons=args.calibration_seasons,
                            estimators=args.estimators, device=args.device,
                            seed=args.seed, nominal_coverage=args.nominal_coverage,
                            save_fold_models=args.save_fold_models,
                            fixed_features=args.fixed_features)


if __name__ == "__main__":
    main()
