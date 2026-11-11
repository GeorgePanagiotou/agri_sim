"""Turn the AppEEARS downloads (data_prep/appeears.py) into compact, quality-masked files in data/processed/.

    ..\\.venv\\Scripts\\python.exe data_prep\\appeears_process.py [mod13q1|mod16|mod11|ecostress|smap|all] [--keep-raw]

Per product: a masked cube (NetCDF, int16 + scale_factor, zlib) and an area-mean time series (parquet). Quality rules:
- MOD13Q1 NDVI/EVI (250 m, 16-day): keep pixel_reliability 0 (good) or 1 (marginal); 2 snow and 3 cloud dropped.
- MOD16A2GF ET/PET (500 m, 8-day, gap-filled): raw > 32700 are non-vegetated fill classes (water, urban, barren) ->
  NaN. Units mm per composite (kg/m2/8day; the last composite of each year covers 5-6 days, see `days`).
- MOD11A2 LST day/night (1 km, 8-day): keep QC bits 0-1 = 00 (good), or = 01 (other quality) with LST error bits 6-7
  <= 01 (<= 2 K). Kelvin -> deg C.
- ECOSTRESS L3T JET ETdaily (70 m, per overpass, May-Sep 2022-2025): already cloud-masked (NaN). The GeoTIFF tag says
  W/m2 but ETdaily is mm/day (product user guide; values 0.5-6). Scenes from neighbouring tiles are resampled
  (nearest) onto the common grid. Output: per-scene stats + per-year May-Sep median composite.
- SMAP SPL3SMP_E (9 km, daily AM/PM): keep retrieval_qual_flag bit 0 = 0 ("recommended quality").
  SPL4SMGP (9 km, 3-hourly model+assimilation): no flag; daily means.

Every granule used is logged in data/processed/appeears_granules.csv. Raw .nc/.tif are then deleted (small-downloads
rule; re-download with `appeears.py download <task>`); README, request and lookup files are kept.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from config import PROC, RAW, STUDY_AREA

DIR = RAW / "appeears"
GRANULES = PROC / "appeears_granules.csv"
KEEP_RAW = "--keep-raw" in sys.argv
I16 = {"dtype": "int16", "_FillValue": -32768, "zlib": True, "complevel": 5}


def open_nc(task):
    f = next((DIR / task).glob("*.nc"))
    with xr.open_dataset(f, decode_cf=False, decode_times=False) as src:  # load + release (Windows file lock)
        ds = src.load()
    # AppEEARS writes "seconds since 2000-01-01" with calendar "julian"; the values are plain elapsed seconds
    # (first MOD13Q1 step = 2000-02-18 = DOY 049, as it should be).
    t = pd.Timestamp("2000-01-01") + pd.to_timedelta(ds["time"].values.astype("int64"), unit="s")
    return f, ds.assign_coords(time=t.normalize())


def raw(ds, v):
    a = ds[v]
    return a.where(a != a.attrs["_FillValue"]).astype("float64") * a.attrs.get("scale_factor", 1.0)


def log_granules(task):
    lst = next((DIR / task).glob("*granule-list.txt"), None)
    if lst is None:
        return
    names = [Path(u.strip()).name for u in lst.read_text().splitlines() if u.strip()]
    new = pd.DataFrame({"task": task, "granule": names})
    old = pd.read_csv(GRANULES) if GRANULES.exists() else pd.DataFrame(columns=["task", "granule"])
    pd.concat([old[old.task != task], new]).to_csv(GRANULES, index=False)
    print(f"  logged {len(names)} granules")


def write(ds, name, scales, attrs):
    ds.attrs = {"source": "NASA LP DAAC / NSIDC via AppEEARS", "area": f"study area {STUDY_AREA}", **attrs}
    out = PROC / name
    ds.to_netcdf(out, encoding={v: dict(I16, scale_factor=s) for v, s in scales.items()})
    print(f"  {out.name}: {out.stat().st_size / 1e6:.1f} MB, {dict(ds.sizes)}")


def series(df, name):
    out = PROC / name
    df.reset_index().to_parquet(out, index=False)
    print(f"  {out.name}: {len(df)} rows, {df.index.min().date()} -> {df.index.max().date()}")


def stats(da, prefix):
    dims = [d for d in da.dims if d != "time"]
    n = np.prod([da.sizes[d] for d in dims])
    return {f"{prefix}_mean": da.mean(dims).values, f"{prefix}_p10": da.quantile(0.1, dims).values,
            f"{prefix}_p90": da.quantile(0.9, dims).values, f"{prefix}_valid": (da.count(dims) / n).values}


def cleanup(task, patterns=("*.nc", "*.tif")):
    if KEEP_RAW:
        return
    gone = [f for p in patterns for f in (DIR / task).glob(p)]
    for f in gone:
        f.unlink()
    print(f"  deleted {len(gone)} raw file(s) in {task}")


# ------------------------------------------------------------------------------------------------ MODIS
def mod13q1():
    task = "agrisim_mod13q1"
    print(task)
    f, ds = open_nc(task)
    ok = ds["_250m_16_days_pixel_reliability"].isin([0, 1])
    ndvi = raw(ds, "_250m_16_days_NDVI").where(ok)
    evi = raw(ds, "_250m_16_days_EVI").where(ok)
    rel = ds["_250m_16_days_pixel_reliability"]
    out = xr.Dataset({"ndvi": ndvi, "evi": evi}, coords={"time": ds.time, "lat": ds.lat, "lon": ds.lon})
    out["ndvi"].attrs = {"long_name": "MOD13Q1.061 16-day NDVI, pixel_reliability 0/1 only"}
    out["evi"].attrs = {"long_name": "MOD13Q1.061 16-day EVI, pixel_reliability 0/1 only"}
    write(out, "modis_vi_16day_250m.nc", {"ndvi": 1e-4, "evi": 1e-4}, {"product": "MOD13Q1.061"})
    s = pd.DataFrame({**stats(ndvi, "ndvi"), "evi_mean": evi.mean(["lat", "lon"]).values,
                      "cloud_frac": (rel == 3).mean(["lat", "lon"]).values}, index=pd.Index(ds.time.values, name="date"))
    series(s, "modis_vi_16day_area.parquet")
    ds.close()
    log_granules(task)
    cleanup(task)


def mod16():
    task = "agrisim_mod16a2gf"
    print(task)
    f, ds = open_nc(task)
    et, pet = (raw(ds, v).where(ds[v] <= 32700) for v in ("ET_500m", "PET_500m"))
    t = pd.DatetimeIndex(ds.time.values)
    days = np.where(t.day_of_year >= 361, (pd.to_datetime(t.year.astype(str) + "-12-31") - t).days + 1, 8)
    out = xr.Dataset({"et": et, "pet": pet}, coords={"time": ds.time, "lat": ds.lat, "lon": ds.lon})
    out["days"] = ("time", days.astype("int8"))
    out["et"].attrs = {"long_name": "MOD16A2GF.061 actual evapotranspiration", "units": "mm per composite"}
    out["pet"].attrs = {"long_name": "MOD16A2GF.061 potential evapotranspiration", "units": "mm per composite"}
    write(out, "modis_et_8day_500m.nc", {"et": 0.1, "pet": 0.1}, {"product": "MOD16A2GF.061 (gap-filled)"})
    s = pd.DataFrame({**stats(et, "et"), "pet_mean": pet.mean(["lat", "lon"]).values, "days": days},
                     index=pd.Index(t, name="date"))
    s["et_pet_ratio"] = s.et_mean / s.pet_mean
    series(s, "modis_et_8day_area.parquet")
    ds.close()
    log_granules(task)
    cleanup(task)


def mod11():
    task = "agrisim_mod11a2"
    print(task)
    f, ds = open_nc(task)
    out = xr.Dataset(coords={"time": ds.time, "lat": ds.lat, "lon": ds.lon})
    cols = {}
    for part in ("Day", "Night"):
        qc = ds[f"QC_{part}"].fillna(0).astype("int32")  # QC fill 0 == "good" bits; LST itself is fill 0 there
        mand, err = qc & 0b11, (qc >> 6) & 0b11
        ok = (mand == 0) | ((mand == 1) & (err <= 1))
        v = f"lst_{part.lower()}"
        out[v] = (raw(ds, f"LST_{part}_1km") - 273.15).where(ok)
        out[v].attrs = {"long_name": f"MOD11A2.061 8-day {part.lower()} land surface temperature, QC-filtered",
                        "units": "degC"}
        cols.update(stats(out[v], v))
    write(out, "modis_lst_8day_1km.nc", {"lst_day": 0.01, "lst_night": 0.01}, {"product": "MOD11A2.061"})
    series(pd.DataFrame(cols, index=pd.Index(ds.time.values, name="date")), "modis_lst_8day_area.parquet")
    ds.close()
    log_granules(task)
    cleanup(task)


# ------------------------------------------------------------------------------------------------ ECOSTRESS
def ecostress():
    import rasterio
    from rasterio.warp import Resampling, reproject

    task = "agrisim_ecostress_et"
    print(task)
    files = sorted((DIR / task).glob("*ETdaily*.tif"))
    if not files:
        print("  no files")
        return
    grids = {}
    for f in files:
        with rasterio.open(f) as r:
            grids.setdefault((r.shape, tuple(r.transform)), []).append(f)
    (shape, transform), _ = max(grids.items(), key=lambda kv: len(kv[1]))
    transform = rasterio.Affine(*transform[:6])
    rows, scenes = [], []
    for f in files:
        with rasterio.open(f) as r:
            a = np.full(shape, np.nan, dtype="float32")
            reproject(rasterio.band(r, 1), a, dst_transform=transform, dst_crs=r.crs, resampling=Resampling.nearest,
                      src_nodata=np.nan, dst_nodata=np.nan)
        stamp = f.name.split("_doy")[1][:13]  # YYYYDDDHHMMSS
        t = pd.to_datetime(stamp[:7], format="%Y%j") + pd.to_timedelta(
            int(stamp[7:9]) * 3600 + int(stamp[9:11]) * 60 + int(stamp[11:13]), unit="s")
        v = a[np.isfinite(a)]
        rows.append({"granule": f.stem.replace("_aid0001", ""), "time_utc": t,
                     "local_hour": round((t.hour + t.minute / 60 + 3) % 24, 1),  # EEST, all scenes May-Sep
                     "valid_frac": round(v.size / a.size, 3),
                     **({"et_mean": v.mean(), "et_p10": np.percentile(v, 10), "et_median": np.median(v),
                         "et_p90": np.percentile(v, 90)} if v.size else {})})
        scenes.append((t, a))
    df = pd.DataFrame(rows).sort_values("time_utc")
    df.to_csv(PROC / "ecostress_et_scenes.csv", index=False, float_format="%.3f")
    print(f"  ecostress_et_scenes.csv: {len(df)} scenes, median valid {df.valid_frac.median():.2f}")
    lon = transform.c + transform.a * (np.arange(shape[1]) + 0.5)
    lat = transform.f + transform.e * (np.arange(shape[0]) + 0.5)
    years = sorted({t.year for t, _ in scenes})
    med, cnt = [], []
    for y in years:
        stack = np.stack([a for t, a in scenes if t.year == y])
        with np.errstate(all="ignore"):
            med.append(np.nanmedian(stack, axis=0))
        cnt.append(np.isfinite(stack).sum(axis=0))
    out = xr.Dataset({"et_median": (("year", "lat", "lon"), np.stack(med)),
                      "nobs": (("year", "lat", "lon"), np.stack(cnt).astype("int16"))},
                     coords={"year": years, "lat": lat, "lon": lon})
    out["et_median"].attrs = {"long_name": "ECOSTRESS L3T JET ETdaily, median of clear overpasses May-Sep",
                              "units": "mm/day"}
    out["nobs"].attrs = {"long_name": "clear overpasses in the median"}
    write(out, "ecostress_et_dryseason_70m.nc", {"et_median": 0.001}, {"product": "ECO_L3T_JET.002 ETdaily",
                                                                       "crs": "EPSG:4326"})
    log_granules(task)
    cleanup(task)


# ------------------------------------------------------------------------------------------------ SMAP
def in_area(ds, half=0.045):
    """9 km cells whose footprint overlaps the study area."""
    w, e, s, n = STUDY_AREA
    return ((ds.lat + half > s) & (ds.lat - half < n)) & ((ds.lon + half > w) & (ds.lon - half < e))


def smap_l3():
    tasks = sorted(p.name for p in DIR.glob("agrisim_spl3smp_e*") if any(p.glob("*.nc")))
    if not tasks:
        print("smap l3: no files")
        return
    print(" + ".join(tasks))
    ds = xr.concat([open_nc(t)[1] for t in tasks], "time").sortby("time")
    ds = ds.isel(time=~pd.Index(ds.time.values).duplicated())
    out = xr.Dataset(coords={"time": ds.time, "lat": ds.lat, "lon": ds.lon})
    cols = {}
    for p, sm, fl in (("am", "Soil_Moisture_Retrieval_Data_AM_soil_moisture",
                       "Soil_Moisture_Retrieval_Data_AM_retrieval_qual_flag"),
                      ("pm", "Soil_Moisture_Retrieval_Data_PM_soil_moisture_pm",
                       "Soil_Moisture_Retrieval_Data_PM_retrieval_qual_flag_pm")):
        # Over Evia no retrieval has "recommended quality" (bit 0 always set: coast, relief, forest), so we keep
        # successful retrievals (bit 2 = 0, flag values 1 and 9) and drop the rest (5 and 13 carry values anyway).
        ok = (ds[fl] != ds[fl].attrs["_FillValue"]) & ((ds[fl] & 4) == 0)
        out[f"sm_{p}"] = raw(ds, sm).where(ok)
        out[f"sm_{p}"].attrs = {"long_name": f"SPL3SMP_E.006 {p.upper()} soil moisture (top ~5 cm), successful "
                                             "retrievals; none flagged recommended quality here", "units": "m3/m3"}
        cols[f"sm_{p}"] = out[f"sm_{p}"].where(in_area(ds)).mean(["lat", "lon"]).values
    out["in_area"] = in_area(ds).astype("int8")
    write(out, "smap_l3_daily_9km.nc", {"sm_am": 1e-4, "sm_pm": 1e-4},
          {"product": "SPL3SMP_E.006 (NSIDC)", "note": "use for seasonality and anomalies, not absolute values"})
    s = pd.DataFrame(cols, index=pd.Index(ds.time.values, name="date"))
    s["sm"] = s[["sm_am", "sm_pm"]].mean(axis=1)
    series(s, "smap_l3_daily_area.parquet")
    for t in tasks:
        log_granules(t)
        cleanup(t)


def smap_l4():
    task = "agrisim_spl4smgp"
    if not any((DIR / task).glob("*.nc")):
        print("smap l4: no files (task still processing?)")
        return
    print(task)
    f, ds = open_nc(task)
    out = xr.Dataset(coords={"lat": ds.lat, "lon": ds.lon})
    for v, name in (("Geophysical_Data_sm_surface", "sm_surface"), ("Geophysical_Data_sm_rootzone", "sm_rootzone")):
        a = raw(ds, v)
        a = a.where(a >= 0)
        out[name] = a.resample(time="1D").mean()  # 3-hourly -> daily
        out[name].attrs = {"long_name": f"SPL4SMGP.008 daily mean {name.replace('_', ' ')}", "units": "m3/m3"}
    out["in_area"] = in_area(ds).astype("int8")
    write(out, "smap_l4_daily_9km.nc", {"sm_surface": 1e-4, "sm_rootzone": 1e-4},
          {"product": "SPL4SMGP.008 (NSIDC), model + SMAP assimilation, 3-hourly averaged to daily"})
    s = pd.DataFrame({n: out[n].where(out.in_area == 1).mean(["lat", "lon"]).values
                      for n in ("sm_surface", "sm_rootzone")}, index=pd.Index(out.time.values, name="date"))
    series(s, "smap_l4_daily_area.parquet")
    log_granules(task)
    cleanup(task)


def smap():
    smap_l3()
    smap_l4()


if __name__ == "__main__":
    what = next((a for a in sys.argv[1:] if not a.startswith("--")), "all")
    jobs = {"mod13q1": mod13q1, "mod16": mod16, "mod11": mod11, "ecostress": ecostress, "smap": smap}
    for k, fn in jobs.items():
        if what in (k, "all"):
            fn()
