"""Scratch: first look at the Landsat field history. WorldCover 2020 classes on the Landsat grid; per agricultural
year, the share of cropland pixels that were winter crop / fallow / summer-green; mean NDVI by class over time."""
import sys
import numpy as np, pandas as pd, xarray as xr, rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

nc, wc, out = sys.argv[1:4]
ds = xr.open_dataset(nc)
v = ds.ndvi.values.astype("float32"); v = np.where(v == 0, np.nan, (v - 1) / 200 - 0.25)
x, y = ds.x.values, ds.y.values
tr = from_origin(x[0] - 15, y[0] + 15, 30, 30)
lc = np.zeros((len(y), len(x)), "uint8")
with rasterio.open(wc) as s:
    reproject(rasterio.band(s, 1), lc, dst_transform=tr, dst_crs="EPSG:32634", resampling=Resampling.mode)
t = pd.DatetimeIndex(ds.time.values)
years = range(1985, 2026)
rows = []
crop = lc == 40
for yr in years:
    spr = np.nanmax(v[(t.year == yr) & t.month.isin([3, 4, 5])], axis=0) if ((t.year == yr) & t.month.isin([3, 4, 5])).any() else np.full(lc.shape, np.nan)
    sm = np.nanmax(v[(t.year == yr) & t.month.isin([7, 8])], axis=0) if ((t.year == yr) & t.month.isin([7, 8])).any() else np.full(lc.shape, np.nan)
    ok = crop & np.isfinite(spr) & np.isfinite(sm)
    n = ok.sum()
    rows.append({"year": yr, "pixels": int(n),
                 "winter_crop": float(((spr >= 0.45) & (sm < 0.35))[ok].mean()) if n else np.nan,
                 "fallow_or_bare": float(((spr < 0.35) & (sm < 0.35))[ok].mean()) if n else np.nan,
                 "summer_green": float((sm >= 0.45)[ok].mean()) if n else np.nan})
df = pd.DataFrame(rows).set_index("year").round(2)
print(df.to_string())
df.to_csv(out + "/cropland_year_types.csv")

ts = {}
for k, name in {10: "tree", 30: "grass", 40: "cropland"}.items():
    m = lc == k
    ts[name] = np.nanmean(v[:, m], axis=1)
ts = pd.DataFrame(ts, index=t)
fig, axs = plt.subplots(2, 1, figsize=(16, 8), dpi=100)
ts.rolling(3, min_periods=1, center=True).mean().plot(ax=axs[0], color=["#2f6b2f", "#9bbf3a", "#e8a33b"])
axs[0].axvline(pd.Timestamp("2021-08-03"), color="red", ls="--"); axs[0].set_title("Landsat mean NDVI in the study area by 2020 land cover (3-month mean); red = fire 3 Aug 2021")
df[["winter_crop", "fallow_or_bare", "summer_green"]].plot(ax=axs[1], marker="o", color=["#e8a33b", "#8c6d46", "#1a9850"])
axs[1].set_title("Cropland pixels per year: winter crop (green Mar-May, dry Jul-Aug) / fallow-bare / summer-green")
axs[1].axvline(2021, color="red", ls="--")
plt.tight_layout(); plt.savefig(out + "/landsat_field_history.png"); print(out + "/landsat_field_history.png")
