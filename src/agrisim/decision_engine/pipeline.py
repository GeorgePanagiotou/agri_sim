"""Regional Evia sowing decisions with as-of HLS green-up evidence.

Use either fresh NASA-source feature loaders or EXISTING generated CSV outputs.
No model training, fabricated parcel observations, or UI logic is performed.

    uv run python -m agrisim.decision_engine.pipeline \
      --season 2026-2027 --crop winter_wheat --as-of 2026-11-15

    uv run python -m agrisim.decision_engine.pipeline \
      --sowing-csv outputs/sowing_weeks.csv --risk-csv outputs/risk_daily.csv \
      --season 2025-2026 --crop winter_wheat
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from agrisim.config import AREA_NAME, OUTPUTS
from agrisim.decision_engine import environmental_risk as er, sowing_window as sw
from agrisim.decision_engine.rotation import apply_rotation
from agrisim.decision_engine.fusion import fuse, summarize_fusion
from agrisim.timeseries.vegetation_indices import DEFAULT_OUT as HLS_OBSERVATIONS


def _observations(path: Path | None) -> pd.DataFrame | None:
    if path is None or (path == HLS_OBSERVATIONS and not path.exists()):
        return None
    return pd.read_csv(path)


def from_environment(data: pd.DataFrame, *, area_id: str = AREA_NAME,
                     as_of: str | None = None, season: str | None = None,
                     crop_id: str | None = None,
                     windows: pd.DataFrame | None = None,
                     sowing_rules: dict | None = None,
                     risk_rules: dict | None = None,
                     vegetation_csv: Path | None = HLS_OBSERVATIONS) -> pd.DataFrame:
    """Recalculate B/D from the SAME daily source, then fuse on identical dates.

    An as-of cutoff discards later observations BEFORE both engines compute
    their features; calendar reference baselines remain retrospective for
    2001-2020 and are explicitly flagged in fusion results.
    """
    if not isinstance(data.index, pd.DatetimeIndex) or data.index.has_duplicates:
        raise ValueError("Environmental input must have unique, daily DatetimeIndex")
    if not data.index.is_monotonic_increasing:
        raise ValueError("Environmental dates must be sorted")
    if as_of is not None:
        end = pd.Timestamp(as_of).normalize()
        data = data.loc[data.index <= end]
    if data.empty:
        raise ValueError("No environment observations on or before the requested cutoff")
    # Currently the regional risk and candidate windows are Evia-specific.
    # A different geographical area's upstream source loader is not yet validated.
    if area_id != "evia":
        raise NotImplementedError("B/D engines currently use Evia-specific regional data/rules; cannot relabel another area")
    current_risk_rules = risk_rules if risk_rules is not None else er.load_rules()
    current_windows = windows if windows is not None else sw.load_windows()
    current_sowing_rules = sowing_rules if sowing_rules is not None else sw.load_rules()
    sowing, _, _, _ = sw.run(data, rules=current_sowing_rules, windows=current_windows)
    if sowing.empty:
        raise ValueError("No candidate windows within the available observation record")
    risk = er.assess(data, current_risk_rules,
                     start=str(sowing.week_start.min().date()),
                     end=str(sowing.week_start.max().date()))
    return apply_rotation(fuse(sowing, risk, area_id=area_id, season=season, crop_id=crop_id, as_of=as_of,
                vegetation=_observations(vegetation_csv)))


def from_csv(sowing_csv: Path, risk_csv: Path, *, area_id: str = AREA_NAME,
             season: str | None = None, crop_id: str | None = None,
             as_of: str | None = None, vegetation_csv: Path | None = HLS_OBSERVATIONS) -> pd.DataFrame:
    """Fuse previously generated outputs without reinterpreting missing hazard rows."""
    if area_id != "evia":
        raise NotImplementedError("Uploaded outputs and engine are Evia regional products; other areas require verified sources")
    return apply_rotation(fuse(pd.read_csv(sowing_csv), pd.read_csv(risk_csv),
                area_id=area_id, season=season, crop_id=crop_id, as_of=as_of,
                vegetation=_observations(vegetation_csv)))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sowing-csv", type=Path, help="Optional existing outputs/sowing_weeks.csv")
    ap.add_argument("--risk-csv", type=Path, help="Optional existing outputs/risk_daily.csv")
    ap.add_argument("--vegetation-csv", type=Path, default=HLS_OBSERVATIONS,
                    help="Dated pilot HLS observations with catalog availability timestamps")
    ap.add_argument("--crop", help="Optional exact crop_id (e.g. winter_wheat)")
    ap.add_argument("--season", help="Optional growing season (e.g. 2026-2027)")
    ap.add_argument("--as-of", help="Do not include candidate weeks after YYYY-MM-DD")
    ap.add_argument("--output", type=Path, default=OUTPUTS / "decision_engine_bd.csv")
    ap.add_argument("--power", type=Path, help="Optional historical POWER parquet for fresh source loading")
    args = ap.parse_args(argv)
    if bool(args.sowing_csv) != bool(args.risk_csv):
        ap.error("Provide both --sowing-csv and --risk-csv, or neither")
    if (args.sowing_csv or args.risk_csv) and args.power:
        ap.error("--power applies only to fresh source loading")
    if args.sowing_csv:
        result = from_csv(args.sowing_csv, args.risk_csv,
                          season=args.season, crop_id=args.crop, as_of=args.as_of, vegetation_csv=args.vegetation_csv)
    else:
        data = er.load_inputs(power_path=args.power)
        result = from_environment(data, season=args.season, crop_id=args.crop, as_of=args.as_of,
                                  vegetation_csv=args.vegetation_csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    summary = summarize_fusion(result)
    args.output.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Evia decision engine: {len(result)} candidate weeks -> {args.output}")
    print("Priorities:", summary["decision_priority_counts"])
    print("Missing risk rows:", summary["missing_risk_rows"])
    print("Pilot vegetation evidence:", summary["vegetation_status_counts"])


if __name__ == "__main__":
    main()
