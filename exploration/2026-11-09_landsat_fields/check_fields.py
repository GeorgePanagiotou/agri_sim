"""Check figures for the Landsat-only field map and crop/fallow history (reads agrisim/data/processed)."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

P = Path(sys.argv[1])
OUT = Path(sys.argv[2])
with rasterio.open(P / "landsat_field_map_30m.tif") as s:
    lu_now, lu_old, burn = s.read()
fy = xr.open_dataset(P / "landsat_field_years.nc")
cube = xr.open_dataset(P / "landsat_ndvi_monthly_30m.nc")
lu_cols = ["#ffffff", "#e8a33b", "#1a9850", "#2f6b2f", "#d7e38a", "#bbbbbb"]
lu_lab = ["none/water", "rainfed field", "irrigated summer field", "woody", "herbaceous/shrub (grazing)", "bare/built"]
cm_lu = ListedColormap(lu_cols)

fig, axs = plt.subplots(1, 3, figsize=(18, 8.5), dpi=100)
axs[0].imshow(lu_old, cmap=cm_lu, vmin=0, vmax=5, interpolation="nearest"); axs[0].set_title("Land use 1985-1995 (Landsat 5)")
axs[1].imshow(lu_now, cmap=cm_lu, vmin=0, vmax=5, interpolation="nearest"); axs[1].set_title("Land use 2013-2020 (Landsat 8)")
axs[2].imshow(burn, cmap=ListedColormap(["#f0f0f0", "#fee391", "#fe9929", "#cc4c02", "#662506"]), vmin=0, vmax=4,
              interpolation="nearest"); axs[2].set_title("Burn 2021, Landsat dNBR (low / mod-low / mod-high / high)")
for a in axs: a.axis("off")
axs[1].legend(handles=[Patch(color=c, label=l) for c, l in zip(lu_cols[1:], lu_lab[1:])], loc="lower left", fontsize=9)
plt.tight_layout(); plt.savefig(OUT / "landuse_then_now_burn.png"); plt.close()

cls_cols = ["#ffffff", "#e8a33b", "#8c6d46", "#1a9850", "#dddddd"]
cm_c = ListedColormap(cls_cols)
yrs = [2019, 2020, 2021, 2022, 2023]
fig, axs = plt.subplots(1, len(yrs), figsize=(22, 7), dpi=100)
for a, y in zip(axs, yrs):
    c = fy.year_class.sel(year=y).values.copy()
    c[c == 9] = 4
    a.imshow(c, cmap=cm_c, vmin=0, vmax=4, interpolation="nearest"); a.set_title(f"Fields, agricultural year {y}"); a.axis("off")
axs[0].legend(handles=[Patch(color=c, label=l) for c, l in zip(cls_cols[1:], ["crop", "fallow / low", "summer crop", "no data"])],
              loc="lower left", fontsize=9)
plt.tight_layout(); plt.savefig(OUT / "crop_fallow_2019_2023.png"); plt.close()

df = pd.read_csv(P / "landsat_field_years.csv").set_index("year")
fig, axs = plt.subplots(2, 1, figsize=(15, 8), dpi=100, sharex=True)
for a, grp in zip(axs, ("unburned", "burned2021")):
    df[[f"crop_{grp}", f"fallow_{grp}", f"summer_{grp}"]].plot(ax=a, marker="o", color=["#e8a33b", "#8c6d46", "#1a9850"])
    a.axvline(2021.5, color="red", ls="--"); a.set_title(f"Field pixels, {grp}: share crop / fallow / summer crop per agricultural year")
plt.tight_layout(); plt.savefig(OUT / "field_year_shares.png"); plt.close()

# example pixel curves: 4 rainfed fields (2 burned, 2 not) and 1 irrigated, chosen at random with a fixed seed
rng = np.random.default_rng(1)
picks = []
for cond, n in (((lu_now == 1) & (burn >= 2), 2), ((lu_now == 1) & (burn == 0), 2), ((lu_now == 2), 1)):
    yy, xx = np.nonzero(cond)
    if len(yy):
        for i in rng.choice(len(yy), size=min(n, len(yy)), replace=False):
            picks.append((yy[i], xx[i]))
v = cube.ndvi.values
t = pd.DatetimeIndex(cube.time.values)
fig, axs = plt.subplots(len(picks), 1, figsize=(16, 2.4 * len(picks)), dpi=100, sharex=True)
for a, (r, c) in zip(np.atleast_1d(axs), picks):
    s = v[:, r, c].astype("float32"); s = np.where(s == 0, np.nan, (s - 1) / 200 - 0.25)
    a.plot(t, s, ".-", lw=0.6, ms=2, color="#555")
    yc = fy.year_class.values[:, r, c]
    for yr, k in zip(fy.year.values, yc):
        col = {1: "#e8a33b", 2: "#8c6d46", 3: "#1a9850"}.get(int(k))
        if col:
            a.axvspan(pd.Timestamp(f"{yr - 1}-10-01"), pd.Timestamp(f"{yr}-09-30"), color=col, alpha=0.25, lw=0)
    a.axvline(pd.Timestamp("2021-08-03"), color="red", ls="--")
    a.set_ylim(-0.1, 0.95); a.set_title(f"pixel row {r} col {c} · land use {lu_lab[lu_now[r, c]]} · burn class {burn[r, c]}", fontsize=9)
plt.tight_layout(); plt.savefig(OUT / "example_field_curves.png"); plt.close()
print("figures in", OUT)
