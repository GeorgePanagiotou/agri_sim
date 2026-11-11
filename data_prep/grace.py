"""NASA GRACE / GRACE-FO for North Evia (context only: water storage and drought, coarse resolution).

1. GRACE-DA drought indicators (GRACEDADM_CLSM025GL_7D v3.0, GES DISC): weekly 0.25 deg percentiles of surface soil
   moisture, root-zone soil moisture and groundwater storage, from GRACE/GRACE-FO assimilated into the Catchment land
   model. Read through Earthdata Cloud OPeNDAP (a 3x3-cell subset per week, ~300 bytes), not the 2 MB global files.
2. JPL GRACE/GRACE-FO mascon CRI RL06.3 v04 (PO.DAAC): monthly terrestrial water storage anomaly (cm of water) on a
   0.5 deg grid (true mascon size ~3 deg). The whole record is one 44 MB file: downloaded, cells around Evia kept,
   raw file deleted.

Outputs
- data/raw/grace_da/<year>.parquet         per-year cache (resume)
- data/processed/grace_da_weekly_2003_2026.parquet   date, lat, lon, sfsm_pct, rtzsm_pct, gws_pct
- data/processed/grace_mascon_tws_2002_2026.csv      date (mid-month), lat, lon, mascon_ID, land_mask, scale_factor,
  tws_cm, tws_land_cm (x gain factor, land only), uncertainty_cm (3x3 cells of 0.5 deg round Evia)

    ..\\.venv\\Scripts\\python.exe data_prep\\grace.py [da|mascon]
"""
import sys
import time
import urllib.parse
import warnings
from concurrent.futures import ThreadPoolExecutor

import earthaccess
import numpy as np
import pandas as pd

from config import PROC, RAW, STUDY_AREA

warnings.filterwarnings("ignore")
W, E, S, N = STUDY_AREA
LON_C, LAT_C = (W + E) / 2, (S + N) / 2
earthaccess.login(strategy="netrc")
session = earthaccess.get_requests_https_session()

# ---------------------------------------------------------------- GRACE-DA (weekly drought percentiles)
DA_CONCEPT = "C2283200566-GES_DISC"
# grid: lat -59.875..89.875, lon -179.875..179.875, step 0.25; 3x3 cells centred on the study area
LA = int(round((LAT_C + 59.875) / 0.25))
LO = int(round((LON_C + 179.875) / 0.25))
VARS = {"sfsm_inst": "sfsm_pct", "rtzsm_inst": "rtzsm_pct", "gws_inst": "gws_pct"}
CE = ";".join([f"/lat[{LA - 1}:{LA + 1}]", f"/lon[{LO - 1}:{LO + 1}]"]
              + [f"/{v}[0][{LA - 1}:{LA + 1}][{LO - 1}:{LO + 1}]" for v in VARS])


def da_read(granule):
    ur = granule["umm"]["GranuleUR"]
    day = pd.Timestamp(granule["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10])
    url = f"https://opendap.earthdata.nasa.gov/collections/{DA_CONCEPT}/granules/{urllib.parse.quote(ur)}.dap.csv"
    err = None
    for attempt in range(6):
        try:
            r = session.get(url, params={"dap4.ce": CE}, timeout=90)
            r.raise_for_status()
            rows = {}
            for line in r.text.splitlines():
                key, _, vals = line.partition(",")
                rows[key.strip()] = [float(v) for v in vals.split(",")] if vals else []
            lats, lons = rows["/lat"], rows["/lon"]
            out = []
            for i, lat in enumerate(lats):
                rec = {"date": day, "lat": lat}
                for j, lon in enumerate(lons):
                    out.append(dict(rec, lon=lon, **{VARS[v]: rows[f"/{v}[0][{i}]"][j] for v in VARS}))
            return pd.DataFrame(out)
        except Exception as exc:  # throttling / transient errors: back off
            err = exc
            time.sleep(2 ** attempt + 1)
    print("FAILED", day.date(), type(err).__name__, str(err)[:150], flush=True)
    return None


def grace_da():
    cache = RAW / "grace_da"
    cache.mkdir(parents=True, exist_ok=True)
    for year in range(2003, 2027):
        target = cache / f"{year}.parquet"
        have = pd.read_parquet(target) if target.exists() else None
        res = earthaccess.search_data(short_name="GRACEDADM_CLSM025GL_7D", version="3.0",
                                      temporal=(f"{year}-01-01", f"{year}-12-31"))
        res = [g for g in res if g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:4] == str(year)]
        done = set(have.date.dt.strftime("%Y-%m-%d")) if have is not None else set()
        todo = [g for g in res if g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10] not in done]
        if not todo:
            print(year, "complete, skipping", flush=True)
            continue
        with ThreadPoolExecutor(max_workers=6) as pool:
            parts = [d for d in pool.map(da_read, todo) if d is not None]
        df = pd.concat(([have] if have is not None else []) + parts).sort_values(["date", "lat", "lon"])
        df.to_parquet(target, index=False)
        print(year, len(res), "weeks,", df.date.nunique(), "in cache", flush=True)
    df = pd.concat([pd.read_parquet(p) for p in sorted(cache.glob("*.parquet"))])
    for c in VARS.values():
        df[c] = df[c].where(df[c] > -900)
    df = df.drop_duplicates(["date", "lat", "lon"]).sort_values(["date", "lat", "lon"])
    out = PROC / "grace_da_weekly_2003_2026.parquet"
    df.to_parquet(out, index=False)
    print("wrote", out, df.date.min().date(), "->", df.date.max().date(), df.date.nunique(), "weeks")


# ---------------------------------------------------------------- JPL mascon (monthly TWS anomaly)
def grace_mascon():
    import xarray as xr

    d = RAW / "grace_mascon"
    d.mkdir(parents=True, exist_ok=True)
    res = earthaccess.search_data(short_name="TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4")
    print("granules:", [g["umm"]["GranuleUR"] for g in res])
    files = earthaccess.download(res, str(d))
    nc = next(str(f) for f in files if str(f).endswith(".nc"))
    ds = xr.open_dataset(nc)
    lon360 = LON_C % 360
    sub = ds.sel(lat=slice(LAT_C - 0.75, LAT_C + 0.75), lon=slice(lon360 - 0.75, lon360 + 0.75))
    df = sub[["lwe_thickness", "uncertainty"]].to_dataframe().reset_index()
    static = sub[["land_mask", "scale_factor", "mascon_ID"]].to_dataframe().reset_index()
    df = df.merge(static, on=["lat", "lon"])
    df = df.rename(columns={"time": "date", "lwe_thickness": "tws_cm", "uncertainty": "uncertainty_cm"})
    # JPL: over land, multiply by the CRI gain factors (scale_factor) to restore signal lost to sampling/filtering
    df["tws_land_cm"] = np.where(df.land_mask > 0, df.tws_cm * df.scale_factor, np.nan)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["lon"] = np.where(df.lon > 180, df.lon - 360, df.lon)
    df = df[["date", "lat", "lon", "mascon_ID", "land_mask", "scale_factor", "tws_cm", "tws_land_cm",
             "uncertainty_cm"]].sort_values(["date", "lat", "lon"])
    out = PROC / "grace_mascon_tws_2002_2026.csv"
    df.to_csv(out, index=False, float_format="%.3f")
    print("wrote", out, df.date.nunique(), "solutions,", df[["lat", "lon"]].drop_duplicates().shape[0], "cells")
    ds.close()
    for f in d.glob("*"):
        f.unlink()  # keep only the extracted cells (small-downloads rule)
    print("deleted raw mascon file")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("mascon", "all"):
        grace_mascon()
    if what in ("da", "all"):
        grace_da()
