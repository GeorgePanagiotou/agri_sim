"""Landsat-only field map and crop/fallow history from the monthly NDVI cube (landsat_ndvi_history.py).

Per agricultural year (Oct of the year before .. Sep), per 30 m pixel:
  spring_peak = max NDVI Mar-May, early = max Mar-Apr, summer_min = min Jul-Sep, summer_max = max Jul-Aug
  annual-like year:  spring_peak - summer_min >= 0.25 and summer_min <= 0.30 and summer_max < 0.45
  summer-green year: summer_max >= 0.50 and summer_max - early >= 0.20   (irrigated summer crop)
  woody year:        summer_min >= 0.35 and early >= 0.35                (forest, olive, shrub: green all year)
Land use for a period = what most of its years look like (fields: annual-like or summer-green in >= 50 % of years).

Crop vs. fallow per year, for field pixels: each pixel gets its OWN threshold between its good and poor years
(2-means on its spring peaks over all years in the cube). A pixel with < 0.12 between the two groups has no clear
fallow years. Per-pixel thresholds make the result robust to the small NDVI offsets between Landsat 5/7/8/9.
Because the threshold uses every year, adding a year can flip borderline years: adding 2026 changed crop/fallow in
about 1 % of field pixel-years (spring_peak unchanged).

Outputs (data/processed):
  landsat_field_map_30m.tif   band 1 land use 2013-2020, band 2 land use 1985-1995, band 3 burn 2021 (dNBR class)
                              land use: 0 no data/water, 1 rainfed field, 2 irrigated summer field, 3 woody,
                                        4 herbaceous/shrub (grazing land), 5 bare/built
                              burn: 0 unburned, 1 low, 2 moderate-low, 3 moderate-high, 4 high
  landsat_field_years.nc      year_class(year, y, x): 0 n/a, 1 crop, 2 fallow/low, 3 summer crop, 9 no data
                              spring_peak(year, y, x) uint8 like the NDVI cube
  landsat_field_years.csv     per year: field pixels by class, split by burned / unburned in 2021

    ..\\.venv\\Scripts\\python.exe data_prep\\landsat_field_map.py
"""
import numpy as np
import pandas as pd
import rasterio
import xarray as xr

from config import PROC
from landsat_common import profile, water_mask

# Water from Landsat's own QA water flag: the 8 clearest Landsat 8 scenes of 2016-2020
_sc = pd.read_csv(PROC / "landsat_scenes.csv")
_sc = _sc[(_sc.platform == "landsat-8") & _sc.date.str[:4].astype(int).between(2016, 2020)]
WATER = water_mask(_sc.sort_values(["valid_share", "cloud_cover"], ascending=[False, True]).id.head(8))
print("water pixels:", int(WATER.sum()), f"({WATER.mean():.1%} of the grid)")

ds = xr.open_dataset(PROC / "landsat_ndvi_monthly_30m.nc")
raw = ds.ndvi.values  # uint8 (time, y, x)
t = pd.DatetimeIndex(ds.time.values)
T, H, W = raw.shape
# Agricultural years fully inside the cube (Evia cube 1984-2025 -> 1985..2025, as before)
YEARS = list(range(max(1985, int(t.year.min()) + 1), int(t.year.max()) + 1))


def months(year, mlist):
    """Decoded NDVI for the given months of the agricultural year (Oct-Dec belong to the year before)."""
    idx = [np.where((t.year == (year - 1 if m >= 10 else year)) & (t.month == m))[0] for m in mlist]
    idx = [i[0] for i in idx if len(i)]
    if not idx:
        return np.full((1, H, W), np.nan, "float32")
    v = raw[idx].astype("float32")
    return np.where(v == 0, np.nan, (v - 1) / 200 - 0.25)


def nanmax(a):
    with np.errstate(all="ignore"):
        return np.where(np.isfinite(a).any(0), np.nanmax(np.where(np.isfinite(a), a, -9), 0), np.nan)


def nanmin(a):
    with np.errstate(all="ignore"):
        return np.where(np.isfinite(a).any(0), np.nanmin(np.where(np.isfinite(a), a, 9), 0), np.nan)


Y = len(YEARS)
peak, annual, summer, woody, valid, maxall = (np.zeros((Y, H, W), d) for d in
                                              ("float32", bool, bool, bool, bool, "float32"))
for k, yr in enumerate(YEARS):
    sp, early = nanmax(months(yr, [3, 4, 5])), nanmax(months(yr, [3, 4]))
    smin, smax = nanmin(months(yr, [7, 8, 9])), nanmax(months(yr, [7, 8]))
    peak[k] = sp
    valid[k] = np.isfinite(sp) & np.isfinite(smin) & np.isfinite(smax)
    annual[k] = valid[k] & (sp - smin >= 0.25) & (smin <= 0.30) & (smax < 0.45)
    summer[k] = valid[k] & (smax >= 0.50) & (smax - np.nan_to_num(early, nan=0) >= 0.20)
    woody[k] = valid[k] & (smin >= 0.35) & (np.nan_to_num(early, nan=0) >= 0.35)  # green in early spring too
    maxall[k] = nanmax(np.stack([sp, smax]))

with np.errstate(all="ignore"):
    med_all = np.nanmedian(np.where(raw == 0, np.nan, (raw.astype("float32") - 1) / 200 - 0.25), axis=0)


def land_use(sel):
    n = valid[sel].sum(0).astype("float32")
    with np.errstate(all="ignore"):
        f_ann, f_sum, f_wood = annual[sel].sum(0) / n, summer[sel].sum(0) / n, woody[sel].sum(0) / n
        top = np.nanmax(maxall[sel], 0)
    lu = np.full((H, W), 4, "uint8")             # default: herbaceous / shrub (grazing land)
    lu[f_wood >= 0.5] = 3
    lu[(f_ann + f_sum >= 0.5) & (f_wood < 0.3)] = 1
    lu[(f_sum >= 0.4) & (f_wood < 0.3)] = 2
    lu[top < 0.25] = 5                           # never green: bare / built
    lu[WATER | (n < 3)] = 0                      # water (Landsat QA flag) / no data
    return lu


yrs = np.array(YEARS)
lu_now = land_use((yrs >= 2013) & (yrs <= 2020))
lu_old = land_use((yrs >= 1985) & (yrs <= 1995))

# per-pixel 2-means on spring peaks (all years)
lo = np.nanpercentile(np.where(valid, peak, np.nan), 25, axis=0)
hi = np.nanpercentile(np.where(valid, peak, np.nan), 75, axis=0)
for _ in range(10):
    thr = (lo + hi) / 2
    with np.errstate(all="ignore"):
        hi_new = np.nanmean(np.where(valid & (peak >= thr), peak, np.nan), 0)
        lo_new = np.nanmean(np.where(valid & (peak < thr), peak, np.nan), 0)
    hi, lo = np.where(np.isfinite(hi_new), hi_new, hi), np.where(np.isfinite(lo_new), lo_new, lo)
thr = (lo + hi) / 2
separable = (hi - lo) >= 0.12

field_px = np.isin(lu_now, (1, 2)) | np.isin(lu_old, (1, 2))
cls = np.zeros((Y, H, W), "uint8")
for k in range(Y):
    c = np.full((H, W), 9, "uint8")
    c[valid[k]] = 1
    c[valid[k] & separable & (peak[k] < thr)] = 2
    c[summer[k]] = 3
    c[~field_px] = 0
    cls[k] = c

DNBR = PROC / "landsat_dnbr_2021_30m.tif"
if DNBR.exists():  # Evia: the August 2021 fire (landsat_burn_2021.py)
    with rasterio.open(DNBR) as s:
        dnbr = s.read(1)
else:              # other areas: no fire mapped -> burn band 0 everywhere
    print("no burn map (landsat_dnbr_2021_30m.tif): burn band set to 0")
    dnbr = np.zeros((H, W), "float32")
burn = np.digitize(np.nan_to_num(dnbr, nan=0), [0.10, 0.27, 0.44, 0.66]).astype("uint8")
burn[lu_now == 0] = 0

prof = profile("uint8", count=3, nodata=None)
with rasterio.open(PROC / "landsat_field_map_30m.tif", "w", **prof) as dst:
    dst.write(np.stack([lu_now, lu_old, burn]))
    dst.descriptions = ("land_use_2013_2020", "land_use_1985_1995", "burn_2021")
    dst.update_tags(land_use="0 none/water, 1 rainfed field, 2 irrigated summer field, 3 woody, "
                             "4 herbaceous/shrub (grazing), 5 bare/built",
                    burn_2021="0 unburned, 1 low, 2 moderate-low, 3 moderate-high, 4 high (dNBR 0.10/0.27/0.44/0.66)")

enc_peak = np.where(np.isfinite(peak), np.clip(np.round((peak + 0.25) * 200) + 1, 1, 255), 0).astype("uint8")
xr.Dataset({"year_class": (("year", "y", "x"), cls), "spring_peak": (("year", "y", "x"), enc_peak)},
           coords={"year": YEARS, "y": ds.y.values, "x": ds.x.values},
           attrs={"year_class": "0 not a field, 1 crop, 2 fallow/low, 3 summer crop, 9 no data",
                  "spring_peak": "ndvi = (v - 1) / 200 - 0.25; 0 = no data", "crs": ds.attrs.get("crs"),
                  "agricultural_year": "Oct of the year before .. Sep"}
           ).to_netcdf(PROC / "landsat_field_years.nc",
                       encoding={v: {"zlib": True, "complevel": 5} for v in ("year_class", "spring_peak")})

ha = 0.09
burned_field = field_px & (burn >= 1)
rows = []
for k, yr in enumerate(YEARS):
    row = {"year": yr}
    for name, m in (("burned2021", burned_field), ("unburned", field_px & ~burned_field)):
        c = cls[k][m]
        known = c[c != 9]
        for code, lab in ((1, "crop"), (2, "fallow"), (3, "summer")):
            row[f"{lab}_{name}"] = round(float((known == code).mean()), 3) if known.size else np.nan
        row[f"known_ha_{name}"] = round(float(known.size * ha))
    rows.append(row)
pd.DataFrame(rows).to_csv(PROC / "landsat_field_years.csv", index=False)

# alternation check on rainfed fields with separable years: observed switch rate vs. random expectation
m = (lu_now == 1) & separable
seq = cls[:, m]  # (years, pixels)
a, b = seq[:-1], seq[1:]
both = np.isin(a, (1, 2)) & np.isin(b, (1, 2))
switch = ((a != b) & both).sum() / both.sum()
p = (seq == 2).sum() / np.isin(seq, (1, 2)).sum()
print({"field_ha_2013_2020": round(float(np.isin(lu_now, (1, 2)).sum() * ha)),
       "rainfed_ha": round(float((lu_now == 1).sum() * ha)), "irrigated_ha": round(float((lu_now == 2).sum() * ha)),
       "field_ha_1985_1995": round(float(np.isin(lu_old, (1, 2)).sum() * ha)),
       "fields_then_not_now_ha": round(float((np.isin(lu_old, (1, 2)) & ~np.isin(lu_now, (1, 2))).sum() * ha)),
       "fields_burned_2021_ha": round(float((np.isin(lu_now, (1, 2)) & (burn >= 1)).sum() * ha)),
       "grazing_ha": round(float((lu_now == 4).sum() * ha)), "grazing_burned_ha": round(float(((lu_now == 4) & (burn >= 1)).sum() * ha)),
       "woody_ha": round(float((lu_now == 3).sum() * ha)), "woody_burned_ha": round(float(((lu_now == 3) & (burn >= 1)).sum() * ha)),
       "separable_share_of_rainfed": round(float(separable[lu_now == 1].mean()), 2),
       "fallow_share": round(float(p), 3), "switch_rate_observed": round(float(switch), 3),
       "switch_rate_if_random": round(float(2 * p * (1 - p)), 3)})
