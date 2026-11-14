"""Build the ML training table: one row per rainfed field pixel x agricultural season.

Targets are SATELLITE STAND-INS, not farm outcomes (none exist):
    target_spring_peak_ndvi   max Landsat NDVI Mar-May of the season (crop vigour proxy)
    target_class              1 crop, 2 fallow / low cover, 3 summer crop (Landsat yearly NDVI curve)
    target_crop               1 if target_class == 1 else 0
Agricultural season Y = Oct (Y-1) .. Sep Y (as in landsat_field_years.nc).

Features use only data available at the decision date `--as-of` (default 12-01, i.e. 1 Dec of Y-1):
    hist_*      previous seasons' class and spring peak of the same pixel (rotation history)
    ndvi_*      monthly Landsat NDVI of Y-1 for months completed before the decision date (optional: needs the
                local 150 MB cube data/processed/landsat_ndvi_monthly_30m.nc)
    rain_*      IMERG daily rain of the pixel's 0.1 deg cell, sums over windows ending the day before
    reg_*       regional indicators at the decision date (Environmental Risk Engine; POWER temperature)
    sow_*       sowing-window engine (long-record verdicts) for wheat / barley, weeks starting before the date
    soil_*, terrain_*, burn_*   static layers on the 30 m grid; post_fire = season after the Aug 2021 fire
Group columns for cross-validation (never features): season, block_id (spatial blocks), pixel_id.

    python -m agrisim.pipelines.build_training_table
    python -m agrisim.pipelines.build_training_table --as-of 03-01 --out data/processed/ml/training_table_mar.parquet
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from pyproj import Transformer

from agrisim.config import PROC
from agrisim.decision_engine import environmental_risk as er
from agrisim.decision_engine import sowing_window as sw

OUT = PROC / "ml" / "training_table_v1.parquet"
CLASS_NAMES = {1: "crop", 2: "fallow", 3: "summer_crop"}


def decode_ndvi(v: np.ndarray) -> np.ndarray:
    """uint8 encoding of the Landsat NDVI products: ndvi = (v - 1) / 200 - 0.25; 0 = no data."""
    out = (v.astype("float32") - 1) / 200 - 0.25
    out[v == 0] = np.nan
    return out


def decision_date(season: int, as_of: str) -> pd.Timestamp:
    month = int(as_of[:2])
    return pd.Timestamp(f"{season - 1 if month >= 9 else season}-{as_of}")


def field_pixels(proc: Path, which: str) -> pd.DataFrame:
    with rasterio.open(proc / "landsat_field_map_30m.tif") as ds:
        lu, burn = ds.read(1), ds.read(3)
        transform, crs = ds.transform, ds.crs
    mask = (lu == 1) if which == "rainfed" else np.isin(lu, (1, 2))
    rows, cols = np.nonzero(mask)
    x = transform.c + (cols + 0.5) * transform.a
    y = transform.f + (rows + 0.5) * transform.e
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(x, y)
    return pd.DataFrame({"pixel_id": rows * lu.shape[1] + cols, "row": rows, "col": cols,
                         "x_utm34n": x, "y_utm34n": y, "lon": lon, "lat": lat,
                         "land_use_2013_2020": lu[rows, cols], "burn_class_2021": burn[rows, cols]})


def static_layers(px: pd.DataFrame, proc: Path) -> pd.DataFrame:
    out = px.copy()
    for name, prefix in (("soil_30m.tif", "soil_"), ("terrain_30m.tif", "terrain_")):
        with rasterio.open(proc / name) as ds:
            data = ds.read()
            for i, desc in enumerate(ds.descriptions):
                out[prefix + desc] = data[i][px.row, px.col].astype("float32")
    dnbr_path = proc / "landsat_dnbr_2021_30m.tif"
    if dnbr_path.exists():
        with rasterio.open(dnbr_path) as ds:
            dnbr = ds.read(1).astype("float32")
            if ds.nodata is not None:
                dnbr[dnbr == ds.nodata] = np.nan
        out["burn_dnbr_2021"] = dnbr[px.row, px.col]
    else:  # area without a mapped fire
        out["burn_dnbr_2021"] = np.nan
    return out


def imerg_cells(px: pd.DataFrame, proc: Path):
    """Daily rain per 0.1 deg cell (cells x days) and each pixel's nearest cell index."""
    raw = pd.read_parquet(proc / "imerg_daily_2001_2025.parquet")
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    table = raw.pivot_table(index="date", columns=["lat", "lon"], values="precip_mm")
    table = table.reindex(pd.date_range(table.index.min(), table.index.max(), freq="D"))
    centres = np.array(table.columns.tolist())
    d2 = (px.lat.to_numpy()[:, None] - centres[None, :, 0]) ** 2 + (px.lon.to_numpy()[:, None] - centres[None, :, 1]) ** 2
    return table, d2.argmin(axis=1), centres


def rain_features(table: pd.DataFrame, d: pd.Timestamp) -> dict[str, np.ndarray]:
    """Per-cell rain sums over windows ending d-1 (NaN if any day missing)."""
    def total(start, end):
        part = table.loc[start:end]
        full = len(part) == (end - start).days + 1 and part.notna().all().all()
        return part.sum().to_numpy() if full else np.full(table.shape[1], np.nan)
    end = d - pd.Timedelta(days=1)
    season_start = pd.Timestamp(f"{d.year if d.month >= 9 else d.year - 1}-09-01")
    feats = {f"rain_prior_{n}d_mm": total(d - pd.Timedelta(days=n), end) for n in (30, 60, 90)}
    feats["rain_since_sep1_mm"] = total(season_start, end) if end >= season_start else np.zeros(table.shape[1])
    summer = season_start.year
    feats["rain_prev_summer_jja_mm"] = total(pd.Timestamp(f"{summer}-06-01"), pd.Timestamp(f"{summer}-08-31"))
    return feats


class ModisFeatures:
    """Optional field-varying weather from MODIS (LST 1 km, ET 500 m), nearest cell per pixel.

    An 8-day composite counts only when it has ended before the decision date. Rates (degC, mm/day) avoid
    completeness problems of sums. Skipped (no columns) when the files are not in data/processed.
    """

    def __init__(self, px: pd.DataFrame, proc: Path):
        self.grids = {}
        for name, path, vars_ in (("lst", proc / "modis_lst_8day_1km.nc", ("lst_day", "lst_night")),
                                  ("et", proc / "modis_et_8day_500m.nc", ("et", "pet", "days"))):
            if not path.exists():
                continue
            with xr.open_dataset(path) as ds:
                lat_i = np.abs(ds.lat.values[:, None] - px.lat.to_numpy()[None, :]).argmin(axis=0)
                lon_i = np.abs(ds.lon.values[:, None] - px.lon.to_numpy()[None, :]).argmin(axis=0)
                time = pd.DatetimeIndex(ds.time.values)
                data = {v: ds[v].values.astype("float32") for v in vars_}
            self.grids[name] = (time, data, lat_i, lon_i)

    def _mean(self, name, var, start, end, per_day=False):
        time, data, li, lo = self.grids[name]
        sel = (time >= start) & (time + pd.Timedelta(days=8) <= end)
        if not sel.any():
            return np.full(len(li), np.nan)
        block = data[var][sel]
        if per_day:
            days = data["days"][sel]
            block = block / (days.reshape(-1, *([1] * (block.ndim - 1))) if days.ndim == 1 else days)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN cells -> NaN
            return np.nanmean(block, axis=0)[li, lo]

    def features(self, d: pd.Timestamp) -> dict[str, np.ndarray]:
        if not self.grids:
            return {}
        season_start = pd.Timestamp(f"{d.year if d.month >= 9 else d.year - 1}-09-01")
        s0, s1 = pd.Timestamp(f"{season_start.year}-06-01"), pd.Timestamp(f"{season_start.year}-09-01")
        out = {}
        if "lst" in self.grids:
            out["modis_lst_day_prev_summer_c"] = self._mean("lst", "lst_day", s0, s1)
            out["modis_lst_day_since_sep1_c"] = self._mean("lst", "lst_day", season_start, d)
            out["modis_lst_night_since_sep1_c"] = self._mean("lst", "lst_night", season_start, d)
        if "et" in self.grids:
            out["modis_et_prev_summer_mm_day"] = self._mean("et", "et", s0, s1, per_day=True)
            et = self._mean("et", "et", season_start, d, per_day=True)
            pet = self._mean("et", "pet", season_start, d, per_day=True)
            out["modis_et_since_sep1_mm_day"] = et
            with np.errstate(all="ignore"):
                out["modis_et_pet_ratio_since_sep1"] = np.where(pet > 0, et / pet, np.nan)
        return out


def regional_features(data: pd.DataFrame, ind: pd.DataFrame, lev: pd.DataFrame, d: pd.Timestamp) -> dict:
    season_start = pd.Timestamp(f"{d.year if d.month >= 9 else d.year - 1}-09-01")
    window = data.loc[season_start:d - pd.Timedelta(days=1)]
    summer = data.loc[f"{season_start.year}-06-01":f"{season_start.year}-08-31"]
    row = ind.loc[d] if d in ind.index else pd.Series(dtype=float)
    lrow = lev.loc[d] if d in lev.index else pd.Series(dtype=float)
    return {
        "reg_rain_90d_percentile": row.get("rain_long_pct", np.nan),
        "reg_rain_source_is_imerg": float(row.get("rain_source", "") == "IMERG"),
        "reg_dry_spell_days": row.get("dry_spell_days", np.nan),
        "reg_drought_level": lrow.get("drought", np.nan),
        "reg_heavy_rain_level": lrow.get("heavy_rain", np.nan),
        "reg_temp_mean_since_sep1_c": window["power_temp_c"].mean() if len(window) else np.nan,
        "reg_gdd0_since_sep1": window["power_temp_c"].clip(lower=0).sum() if len(window) else np.nan,
        "reg_frost_days_since_sep1": float((window["power_temp_min_c"] < 0).sum()) if len(window) else np.nan,
        "reg_hot_days_prev_summer_ge35c": float((summer["power_temp_max_c"] >= 35).sum()) if len(summer) else np.nan,
    }


def sowing_features(judged: pd.DataFrame, season: int, d: pd.Timestamp) -> dict:
    out = {}
    for crop in ("winter_wheat", "barley"):
        w = judged[(judged.crop_id == crop) & (judged.season == f"{season - 1}-{season}")
                   & (pd.to_datetime(judged.week_start) < d)]
        ok = w[w.verdict_long_record == "check_worthy"]
        first = (pd.to_datetime(ok.week_start).min() - pd.to_datetime(w.window_start).min()).days if len(ok) else np.nan
        out[f"sow_{crop}_weeks_assessed"] = float(len(w))
        out[f"sow_{crop}_weeks_check_worthy"] = float(len(ok))
        out[f"sow_{crop}_days_to_first_check_worthy"] = first
    return out


def build(first_season: int = 2002, last_season: int = 2025, as_of: str = "12-01", fields: str = "rainfed",
          block_px: int = 50, proc: Path = PROC) -> pd.DataFrame:
    px = static_layers(field_pixels(proc, fields), proc)
    px["block_id"] = (px.row // block_px) * 1000 + (px.col // block_px)
    fy = xr.open_dataset(proc / "landsat_field_years.nc")
    years = list(fy.year.values)
    cls_all = fy.year_class.values[:, px.row, px.col]
    peak_all = decode_ndvi(fy.spring_peak.values[:, px.row, px.col])
    fy.close()
    cube_path = proc / "landsat_ndvi_monthly_30m.nc"
    cube = xr.open_dataset(cube_path) if cube_path.exists() else None
    table, cell_idx, _ = imerg_cells(px, proc)
    modis = ModisFeatures(px, proc)

    risk_rules = er.load_rules()
    data = er.load_inputs()
    ind = er.indicators(data, risk_rules)
    lev = er.levels(ind, risk_rules)
    judged, *_ = sw.run(data)

    frames = []
    for season in range(first_season, last_season + 1):
        d = decision_date(season, as_of)
        i = years.index(season)
        cls = cls_all[i].astype(float)
        cls[~np.isin(cls, (1, 2, 3))] = np.nan
        f = pd.DataFrame({"season": season, "decision_date": d.date().isoformat(),
                          "target_class": cls, "target_spring_peak_ndvi": peak_all[i]})
        f["target_crop"] = (f.target_class == 1).astype(float).where(f.target_class.notna())
        for lag in (1, 2, 3):
            prev = cls_all[i - lag].astype(float)
            prev[~np.isin(prev, (1, 2, 3))] = np.nan
            f[f"hist_class_lag{lag}"] = prev
        f["hist_peak_lag1"] = peak_all[i - 1]
        f["hist_peak_lag2"] = peak_all[i - 2]
        past = cls_all[i - 5:i].astype(float)
        past[~np.isin(past, (1, 2, 3))] = np.nan
        f["hist_crop_share_5y"] = np.nanmean(np.where(np.isnan(past), np.nan, past == 1), axis=0)
        f["hist_peak_mean_5y"] = np.nanmean(peak_all[i - 5:i], axis=0)
        since = np.full(len(px), 10.0)
        for lag in range(10, 0, -1):
            since = np.where(cls_all[i - lag] == 2, lag, since)
        f["hist_years_since_fallow"] = since
        if cube is not None:
            months = [m for m in pd.date_range(f"{d.year if d.month >= 9 else d.year - 1}-09-01", d, freq="MS")
                      if m + pd.offsets.MonthEnd(0) < d]
            for m in months:
                sel = cube.ndvi.sel(time=f"{m:%Y-%m}")
                f[f"ndvi_prior_{m:%b}".lower()] = (decode_ndvi(sel.values[0][px.row, px.col])
                                                   if sel.sizes["time"] else np.nan)
        for k, v in rain_features(table, d).items():
            f[k] = v[cell_idx]
        for k, v in modis.features(d).items():
            f[k] = v
        for k, v in {**regional_features(data, ind, lev, d), **sowing_features(judged, season, d)}.items():
            f[k] = v
        f["post_fire"] = float(season >= 2022)
        frames.append(pd.concat([px.reset_index(drop=True), f], axis=1))
    if cube is not None:
        cube.close()
    out = pd.concat(frames, ignore_index=True)
    return out[out.target_class.notna()].reset_index(drop=True)


def dictionary(table: pd.DataFrame, as_of: str) -> dict:
    groups = ["season", "block_id", "pixel_id"]
    ids = ["row", "col", "x_utm34n", "y_utm34n", "lon", "lat", "decision_date", "land_use_2013_2020"]
    targets = [c for c in table if c.startswith("target_")]
    features = [c for c in table if c not in groups + ids + targets]
    return {
        "version": "training_table_v1_2026-11-14", "rows": len(table), "as_of": as_of,
        "unit": "rainfed field pixel (30 m) x agricultural season (Oct Y-1 .. Sep Y)",
        "targets": {t: "satellite stand-in, NOT a farm outcome" for t in targets},
        "class_names": CLASS_NAMES, "features": features, "group_columns": groups, "id_columns": ids,
        "cv_advice": "GroupKFold by season (temporal) and by block_id (spatial); neighbouring pixels are near-copies",
        "leakage_rules": "features use data before decision_date only; hist_* uses earlier seasons; never use "
                         "target_* or same-season NDVI after the decision date as features",
        "regional_note": "rain_* vary by 0.1 deg cell; reg_* and sow_* are one value per season for the whole area",
        "missing": "NaN = not available (no zero filling); XGBoost handles NaN natively",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--first-season", type=int, default=2002)
    p.add_argument("--last-season", type=int, default=2025)
    p.add_argument("--as-of", default="12-01", help="Decision date MM-DD (Sep-Dec = year before the season)")
    p.add_argument("--fields", choices=["rainfed", "all"], default="rainfed")
    p.add_argument("--block-px", type=int, default=50, help="Spatial CV block size in 30 m pixels")
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args(argv)
    table = build(a.first_season, a.last_season, a.as_of, a.fields, a.block_px)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(a.out, index=False)
    meta = dictionary(table, a.as_of)
    a.out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"{len(table)} rows x {table.shape[1]} columns -> {a.out}")
    print(f"{len(meta['features'])} features; seasons {table.season.min()}-{table.season.max()}; "
          f"{table.pixel_id.nunique()} pixels; {table.block_id.nunique()} spatial blocks")
    print(table.groupby("season").agg(rows=("pixel_id", "size"), crop_share=("target_crop", "mean"),
                                      peak=("target_spring_peak_ndvi", "mean")).round(3).to_string())


if __name__ == "__main__":
    main()
