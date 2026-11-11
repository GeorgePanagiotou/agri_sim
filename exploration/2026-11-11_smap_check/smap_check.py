"""Is the very low 2025 SMAP dry-season soil moisture real? Cross-check against independent NASA data.

    ..\\..\\.venv\\Scripts\\python.exe smap_check.py      (run from this folder, or from agrisim/ with the path)

Needs data/processed/ files; the SMAP flag check also needs the raw AppEEARS SPL3 files
(`data_prep/appeears.py download agrisim_spl3`), and is skipped without them.
Outputs here: yearly_dryseason.csv, monthly_2024_2025.csv, flags_by_year.csv, smap_check.png
"""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "data_prep"))
from config import PROC, RAW, STUDY_AREA  # noqa: E402

DRY = [5, 6, 7, 8, 9]          # May-Sep
BASE = range(2015, 2024)       # baseline years for anomalies (SMAP record starts 2015-03-31)
YEARS = range(2015, 2026)

# ------------------------------------------------------------------ load
smap = pd.read_parquet(PROC / "smap_l3_daily_area.parquet").set_index("date")
cube = xr.open_dataset(PROC / "smap_l3_daily_9km.nc")
power = pd.read_parquet(PROC / "power_daily_1981_2026.parquet")
imerg = pd.read_parquet(PROC / "imerg_daily_area_mean.parquet")["precip_mm"]
gda = pd.read_parquet(PROC / "grace_da_weekly_2003_2026.parquet")
gda = gda[(gda.lat == 38.875) & (gda.lon == 23.375)].set_index("date")  # the 0.25 deg cell holding the study area
et = pd.read_parquet(PROC / "modis_et_8day_area.parquet").set_index("date")
lst = pd.read_parquet(PROC / "modis_lst_8day_area.parquet").set_index("date")
vi = pd.read_parquet(PROC / "modis_vi_16day_area.parquet").set_index("date")


def dry(s):
    s = s[s.index.month.isin(DRY)]
    return s.groupby(s.index.year)


# ------------------------------------------------------------------ yearly dry-season table
smap_days = smap.sm.dropna().index
pw_on_smap = power.loc[power.index.isin(smap_days)]  # same days as SMAP: removes sampling differences
hy = power.PRECTOTCORR.groupby(np.where(power.index.month >= 10, power.index.year + 1, power.index.year)).sum()
hy_im = imerg.groupby(np.where(imerg.index.month >= 10, imerg.index.year + 1, imerg.index.year)).agg(["sum", "count"])
low = (cube.sm_am.where(cube.in_area == 1) <= 0.03)
cells = cube[["sm_am", "sm_pm"]].where(cube.in_area == 1).to_dataframe().dropna(how="all").reset_index()
cells = cells[cells.time.dt.month.isin(DRY)]
cell_mean = cells.groupby([cells.time.dt.year, "lat", "lon"]).sm_am.mean().unstack(["lat", "lon"])

t = pd.DataFrame({
    "smap_sm": dry(smap.sm).mean(),
    "smap_am": dry(smap.sm_am).mean(),
    "smap_pm": dry(smap.sm_pm).mean(),
    "smap_days": dry(smap.sm).count(),
    "smap_cell_min": cell_mean.min(axis=1),
    "smap_cell_max": cell_mean.max(axis=1),
    "smap_share_le_0.03": (low.where(cube.sm_am.notnull()).to_dataframe(name="v").dropna()
                           .pipe(lambda d: d[d.index.get_level_values("time").month.isin(DRY)])
                           .groupby(lambda i: i[0].year).v.mean()),
    "power_gwettop": dry(power.GWETTOP).mean(),
    "power_gwettop_smapdays": dry(pw_on_smap.GWETTOP).mean(),
    "power_gwetroot": dry(power.GWETROOT).mean(),
    "gracda_sfsm_pct": dry(gda.sfsm_pct).mean(),
    "gracda_rtzsm_pct": dry(gda.rtzsm_pct).mean(),
    "rain_power_octsep_mm": hy,
    "rain_imerg_octsep_mm": hy_im["sum"].where(hy_im["count"] >= 360),
    "rain_power_mjjas_mm": dry(power.PRECTOTCORR).sum(),
    "modis_et_mjjas_mm": dry(et.et_mean).sum(),
    "modis_lst_day_mjjas_c": dry(lst.lst_day_mean).mean(),
    "modis_ndvi_mjjas": dry(vi.ndvi_mean).mean(),
}).loc[list(YEARS)]
t.index.name = "year"
t.round(3).to_csv(HERE / "yearly_dryseason.csv")

z_cols = ["smap_sm", "power_gwettop", "power_gwetroot", "gracda_sfsm_pct", "gracda_rtzsm_pct",
          "rain_power_octsep_mm", "modis_et_mjjas_mm"]
z = (t[z_cols] - t.loc[list(BASE), z_cols].mean()) / t.loc[list(BASE), z_cols].std()
rank = t[z_cols].rank()  # 1 = driest / lowest of 2015-2025

# ------------------------------------------------------------------ monthly anomalies: does SMAP track POWER?
def month_anom(s):
    m = s.resample("MS").mean()
    clim = m[m.index.year.isin(BASE)].groupby(m[m.index.year.isin(BASE)].index.month).mean()
    return m - clim.reindex(m.index.month).values


ma = pd.DataFrame({"smap": month_anom(smap.sm), "gwettop": month_anom(power.GWETTOP),
                   "sfsm_pct": month_anom(gda.sfsm_pct)}).loc["2015-04":"2025-12"]
r_all = ma.smap.corr(ma.gwettop)
r_base = ma.loc[:"2023-12"].smap.corr(ma.loc[:"2023-12"].gwettop)
r_gda = ma.smap.corr(ma.sfsm_pct)
mon = pd.DataFrame({"smap_sm": smap.sm.resample("MS").mean(), "smap_days": smap.sm.resample("MS").count(),
                    "power_gwettop": power.GWETTOP.resample("MS").mean(),
                    "gracda_sfsm_pct": gda.sfsm_pct.resample("MS").mean(),
                    "rain_power_mm": power.PRECTOTCORR.resample("MS").sum()}).loc["2024-01":"2025-12"]
clim = smap.sm[smap.index.year.isin(BASE)]
mon["smap_clim_2015_2023"] = clim.groupby(clim.index.month).mean().reindex(mon.index.month).values
mon.round(3).to_csv(HERE / "monthly_2024_2025.csv")

# ------------------------------------------------------------------ SMAP flags per year (raw files, optional)
flags = None
raws = sorted((RAW / "appeears").glob("agrisim_spl3smp_e*/*.nc"))
if raws:
    ds = xr.concat([xr.open_dataset(f, decode_cf=False, decode_times=False).load() for f in raws], "time")
    tt = pd.Timestamp("2000-01-01") + pd.to_timedelta(ds.time.values.astype("int64"), unit="s")
    w, e, s, n = STUDY_AREA
    sel = dict(lat=ds.lat[(ds.lat + 0.045 > s) & (ds.lat - 0.045 < n)], lon=ds.lon[(ds.lon + 0.045 > w) & (ds.lon - 0.045 < e)])
    fl = ds["Soil_Moisture_Retrieval_Data_AM_retrieval_qual_flag"].sel(**sel)
    df = fl.assign_coords(time=tt).to_dataframe(name="flag").reset_index()
    df = df[df.flag != 65534]
    df = df[df.time.dt.month.isin(DRY)]
    flags = pd.crosstab(df.time.dt.year, df.flag, normalize="index").round(3)
    flags.index.name = "year"
    flags.to_csv(HERE / "flags_by_year.csv")

# ------------------------------------------------------------------ print
pd.set_option("display.width", 200)
print("Dry season (May-Sep) by year\n", t.round(3).T.to_string(), "\n")
print("z-score vs 2015-2023\n", z.round(2).T.to_string(), "\n")
print("rank (1 = lowest of 2015-2025)\n", rank.T.astype(int).to_string(), "\n")
print(f"monthly anomaly correlation SMAP vs POWER GWETTOP: r = {r_all:.2f} (2015-2025), {r_base:.2f} (2015-2023); "
      f"SMAP vs GRACE-DA sfsm pct: r = {r_gda:.2f}\n")
print("Monthly 2024-2025\n", mon.round(3).to_string(), "\n")
if flags is not None:
    print("AM flag shares in the study-area cells, May-Sep (1, 9 = kept)\n", flags.to_string())

# ------------------------------------------------------------------ figure (light, static PNG for the team)
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
C = {"smap": "#2a78d6", "power": "#eb6834", "gracda": "#1baf7a"}
plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})
fig, ax = plt.subplots(3, 1, figsize=(9, 9.5), gridspec_kw={"height_ratios": [1.2, 1, 0.8]})

a = ax[0]
for col, key, lab in (("smap_sm", "smap", "SMAP L3 surface soil moisture"),
                      ("power_gwettop", "power", "POWER GWETTOP (MERRA-2)"),
                      ("gracda_sfsm_pct", "gracda", "GRACE-DA surface soil moisture pct")):
    a.plot(z.index, z[col], color=C[key], lw=2, marker="o", ms=5, label=lab)
    a.annotate(f"{z[col].iloc[-1]:+.1f}", (z.index[-1], z[col].iloc[-1]), xytext=(6, 0), textcoords="offset points",
               va="center", color=INK, fontsize=8)
a.axhline(0, color=INK2, lw=0.8)
a.set_title("Dry-season (May–Sep) mean, standardised to 2015–2023 (z-score)", loc="left", color=INK, fontsize=10)
a.set_xticks(list(YEARS))
a.grid(axis="y", color=GRID, lw=0.6)
a.legend(frameon=False, loc="lower left", fontsize=8)

a = ax[1]
a.plot(ma.index, ma.smap / ma.smap.std(), color=C["smap"], lw=1.5, label="SMAP L3")
a.plot(ma.index, ma.gwettop / ma.gwettop.std(), color=C["power"], lw=1.5, label="POWER GWETTOP")
a.axhline(0, color=INK2, lw=0.8)
a.set_title(f"Monthly anomaly (÷ std), r = {r_all:.2f}", loc="left", color=INK, fontsize=10)
a.grid(axis="y", color=GRID, lw=0.6)
a.legend(frameon=False, loc="lower left", fontsize=8, ncol=2)

a = ax[2]
rain = t.rain_power_octsep_mm
a.bar(rain.index, rain, color=C["smap"], width=0.7)
a.axhline(rain.loc[list(BASE)].mean(), color=INK2, lw=0.8, ls="--")
for y in (2024, 2025):
    a.annotate(f"{rain[y]:.0f}", (y, rain[y]), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8,
               color=INK)
a.set_title("Rain, hydrological year Oct–Sep (POWER, mm); dashed = 2015–2023 mean", loc="left", color=INK,
            fontsize=10)
a.set_xticks(list(YEARS))
a.grid(axis="y", color=GRID, lw=0.6)
fig.tight_layout()
fig.savefig(HERE / "smap_check.png", dpi=130)
print("wrote", HERE / "smap_check.png")
