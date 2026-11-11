"""Study pack for the team: every layer on the common 30 m Landsat grid + combined CSVs + a one-page atlas.

    ..\\.venv\\Scripts\\python.exe data_prep\\study_pack.py      (~1-2 min; needs the local Landsat NDVI cube)

Reads only data/processed/ (NASA/USGS data + SoilGrids). Writes data/processed/study_pack/:
- vegetation_landsat_30m.tif   Landsat NDVI before (2016-2020) / after (2022-2025) the fire, by season; bare months
- fields_history_30m.tif       share of years cropped / fallow, before vs after (field pixels only)
- water_heat_30m.tif           MODIS ET/PET/LST, ECOSTRESS ET, GPM IMERG rain (coarse cells, nearest = blocky)
- study_points.csv             all bands (+ terrain, soil, land use, burn) at every field pixel + a 300 m grid
- area_monthly_2000_2025.csv   one row per month, all time series side by side; area_yearly_2000_2025.csv
- atlas.png                    16 key layers on one page
The terrain / soil / land-use / burn layers are already on the same grid (terrain_30m.tif, soil_30m.tif,
landsat_field_map_30m.tif, landsat_dnbr_2021_30m.tif, modis_mcd64a1_2021_burndate.tif).
"""
import warnings

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.transform import from_origin, xy
from rasterio.warp import Resampling, reproject, transform as warp_xy

from config import PROC

warnings.filterwarnings("ignore", category=RuntimeWarning)  # all-NaN medians over sea / no-data pixels
OUT = PROC / "study_pack"
OUT.mkdir(exist_ok=True)
PRE, POST = range(2016, 2021), range(2022, 2026)  # fire Aug 2021 excluded from both

with rasterio.open(PROC / "landsat_field_map_30m.tif") as r:
    PROFILE, SHAPE, TRANSFORM, CRS = r.profile, r.shape, r.transform, r.crs
    LU, LU_OLD, BURN = r.read(1), r.read(2), r.read(3)
LAND = LU != 0  # 0 = water / none
FIELD = np.isin(LU, [1, 2])


def read_tif(name):
    with rasterio.open(PROC / name) as r:
        names = [d or name.split(".")[0] for d in r.descriptions]
        return {n: r.read(i + 1).astype("float32") for i, n in enumerate(names)}, r.nodata


def write_tif(name, bands, notes):
    prof = dict(PROFILE, count=len(bands), dtype="float32", nodata=np.nan, compress="deflate", predictor=3,
                tiled=True, blockxsize=256, blockysize=256)
    path = OUT / name
    with rasterio.open(path, "w", **prof) as w:
        for i, (k, a) in enumerate(bands.items(), 1):
            w.write(np.where(LAND, a, np.nan).astype("float32"), i)
            w.set_band_description(i, k)
            w.update_tags(i, note=notes.get(k, ""))
        w.update_tags(periods=f"before = {PRE.start}-{PRE.stop - 1}, after = {POST.start}-{POST.stop - 1} "
                              "(fire Aug 2021 excluded)", **{k: v for k, v in notes.items()})
    print(f"  {name}: {len(bands)} bands, {path.stat().st_size / 1e6:.1f} MB")


def warp(a, lat, lon):
    """Regular lat/lon grid (cell centres, lat descending) -> 30 m UTM grid, nearest (keeps the true cell size)."""
    dx, dy = float(lon[1] - lon[0]), float(lat[0] - lat[1])
    src_t = from_origin(float(lon[0]) - dx / 2, float(lat[0]) + dy / 2, dx, dy)
    dst = np.full(SHAPE, np.nan, dtype="float32")
    reproject(np.asarray(a, dtype="float32"), dst, src_transform=src_t, src_crs="EPSG:4326", dst_transform=TRANSFORM,
              dst_crs=CRS, resampling=Resampling.nearest, src_nodata=np.nan, dst_nodata=np.nan)
    return dst


# ------------------------------------------------------------------ 1. vegetation (Landsat 30 m)
def vegetation():
    print("vegetation (Landsat NDVI cube)")
    ds = xr.open_dataset(PROC / "landsat_ndvi_monthly_30m.nc")
    t = pd.DatetimeIndex(ds.time.values)

    def ndvi(mask):
        v = ds.ndvi.values[np.asarray(mask)].astype("float32")
        return np.where(v == 0, np.nan, (v - 1) / 200 - 0.25)

    def season_median(years, months):
        return np.nanmedian(ndvi(t.year.isin(years) & t.month.isin(months)), axis=0)

    def bare_months(years):
        v = ndvi(t.year.isin(years))
        return 12 * (v < 0.2).sum(0) / np.maximum(np.isfinite(v).sum(0), 1)

    b = {
        "ndvi_summer_before": season_median(PRE, [6, 7, 8]),
        "ndvi_summer_after": season_median(POST, [6, 7, 8]),
        "ndvi_spring_before": season_median(PRE, [3, 4, 5]),
        "ndvi_spring_after": season_median(POST, [3, 4, 5]),
        "ndvi_autumn_before": season_median(PRE, [10, 11]),
        "ndvi_autumn_2021": season_median([2021], [10, 11]),
        "ndvi_autumn_after": season_median(POST, [10, 11]),
        "bare_months_per_year_before": bare_months(PRE),
        "bare_months_per_year_after": bare_months(POST),
    }
    b["ndvi_summer_change"] = b["ndvi_summer_after"] - b["ndvi_summer_before"]
    b["ndvi_autumn_change"] = b["ndvi_autumn_after"] - b["ndvi_autumn_before"]
    notes = {"ndvi_summer_before": "median of monthly Landsat NDVI, Jun-Aug",
             "ndvi_spring_before": "Mar-May", "ndvi_autumn_before": "Oct-Nov: soil cover going into the storm season",
             "ndvi_autumn_2021": "Oct-Nov 2021, right after the fire (storm Athena, Oct 2021)",
             "bare_months_per_year_before": "months per year with NDVI < 0.2 (share of clear months x 12)",
             "ndvi_summer_change": "after - before (negative = less green)"}
    ds.close()
    write_tif("vegetation_landsat_30m.tif", b, notes)
    return b


# ------------------------------------------------------------------ 2. field history (Landsat field-years)
def fields_history():
    print("field history")
    ds = xr.open_dataset(PROC / "landsat_field_years.nc")
    yc = ds.year_class

    def share(years, classes):
        sub = yc.sel(year=[y for y in years if y in ds.year.values]).values
        valid = np.isin(sub, [1, 2, 3])
        hit = np.isin(sub, classes)
        out = hit.sum(0) / np.maximum(valid.sum(0), 1)
        return np.where(valid.sum(0) > 0, out, np.nan).astype("float32")

    pre = range(2013, 2021)  # the field map itself is built on 2013-2020
    b = {"crop_share_2013_2020": share(pre, [1, 3]), "crop_share_2022_2025": share(POST, [1, 3]),
         "summer_crop_share_2013_2020": share(pre, [3]), "summer_crop_share_2022_2025": share(POST, [3]),
         "fallow_share_2022_2025": share(POST, [2])}
    b["crop_share_change"] = b["crop_share_2022_2025"] - b["crop_share_2013_2020"]
    notes = {"crop_share_2013_2020": "share of agricultural years (Oct-Sep) classed crop or summer crop, field "
                                     "pixels only (landsat_field_years.nc)",
             "fallow_share_2022_2025": "share of years classed fallow / low cover",
             "crop_share_change": "after - before (negative = cropped less often, possible abandonment)"}
    ds.close()
    write_tif("fields_history_30m.tif", b, notes)
    return b


# ------------------------------------------------------------------ 3. water & heat (coarse NASA products)
def yearly_sum(da, years, need):
    t = pd.DatetimeIndex(da.time.values)
    out = []
    for y in years:
        sub = da.isel(time=np.where(t.year == y)[0])
        s = sub.sum("time", min_count=need)
        out.append(s)
    return xr.concat(out, "year").mean("year").values


def water_heat():
    print("water & heat")
    b, notes = {}, {}
    et = xr.open_dataset(PROC / "modis_et_8day_500m.nc")
    for k, yrs in (("before", PRE), ("after", POST)):
        b[f"modis_et_mm_year_{k}"] = warp(yearly_sum(et.et, yrs, 40), et.lat, et.lon)
    b["modis_et_change"] = b["modis_et_mm_year_after"] - b["modis_et_mm_year_before"]
    b["modis_pet_mm_year_2016_2025"] = warp(yearly_sum(et.pet, range(2016, 2026), 40), et.lat, et.lon)
    b["modis_et_pet_ratio_after"] = b["modis_et_mm_year_after"] / b["modis_pet_mm_year_2016_2025"]
    notes["modis_et_mm_year_before"] = "MOD16A2GF actual ET, mm/year, 500 m cells"
    et.close()

    lst = xr.open_dataset(PROC / "modis_lst_8day_1km.nc")
    t = pd.DatetimeIndex(lst.time.values)
    jja = t.month.isin([6, 7, 8])
    for k, yrs in (("before", PRE), ("after", POST)):
        sel = np.where(jja & t.year.isin(yrs))[0]
        b[f"modis_lst_day_summer_c_{k}"] = warp(lst.lst_day.isel(time=sel).mean("time").values, lst.lat, lst.lon)
    b["modis_lst_day_summer_change"] = b["modis_lst_day_summer_c_after"] - b["modis_lst_day_summer_c_before"]
    sel = np.where(jja & t.year.isin(POST))[0]
    b["modis_lst_night_summer_c_after"] = warp(lst.lst_night.isel(time=sel).mean("time").values, lst.lat, lst.lon)
    notes["modis_lst_day_summer_c_before"] = "MOD11A2 daytime land surface temperature, Jun-Aug mean, degC, 1 km cells"
    lst.close()

    eco = xr.open_dataset(PROC / "ecostress_et_dryseason_70m.nc")
    b["ecostress_et_mm_day_2022_2025"] = warp(eco.et_median.mean("year").values, eco.lat, eco.lon)
    notes["ecostress_et_mm_day_2022_2025"] = "ECOSTRESS daily ET, May-Sep median per year, mean of 2022-2025, 70 m"
    eco.close()

    im = pd.read_parquet(PROC / "imerg_daily_2001_2025.parquet")
    im = im[(im.date >= "2001-01-01") & (im.date <= "2024-12-31")]
    nyear = 24
    g = im.groupby(["lat", "lon"])
    cells = pd.DataFrame({
        "rain": g.precip_mm.sum() / nyear,
        "octdec": im[im.date.dt.month >= 10].groupby(["lat", "lon"]).precip_mm.sum() / g.precip_mm.sum(),
        "heavy": im[im.precip_mm >= 30].groupby(["lat", "lon"]).size().reindex(g.size().index, fill_value=0) / nyear,
    })
    lats, lons = np.sort(cells.index.get_level_values(0).unique())[::-1], np.sort(cells.index.get_level_values(1).unique())
    for k, name in (("rain", "imerg_rain_mm_year_2001_2024"), ("octdec", "imerg_oct_dec_share"),
                    ("heavy", "imerg_days_ge30mm_per_year")):
        grid = cells[k].unstack("lon").reindex(index=lats, columns=lons).values
        b[name] = warp(grid, lats, lons)
    notes["imerg_rain_mm_year_2001_2024"] = "GPM IMERG Final, mean annual rain, 0.1 deg cells (~10 km)"
    notes["imerg_oct_dec_share"] = "share of the annual rain falling Oct-Dec (storm season)"
    notes["imerg_days_ge30mm_per_year"] = "days with >= 30 mm (erosive storms)"
    write_tif("water_heat_30m.tif", b, notes)
    return b


# ------------------------------------------------------------------ 4. combined point table
def points(layers):
    print("points")
    stack = {"land_use_2013_2020": LU.astype("float32"), "land_use_1985_1995": LU_OLD.astype("float32"),
             "burn_class_2021": BURN.astype("float32")}
    for name in ("terrain_30m.tif", "soil_30m.tif"):
        stack.update(read_tif(name)[0])
    stack["dnbr_2021"] = read_tif("landsat_dnbr_2021_30m.tif")[0]["landsat_dnbr_2021_30m"]
    bd = read_tif("modis_mcd64a1_2021_burndate.tif")[0]["modis_mcd64a1_2021_burndate"]
    stack["modis_burn_doy_2021"] = np.where(bd > 0, bd, np.nan)
    for b in layers:
        stack.update(b)
    grid = np.zeros(SHAPE, bool)
    grid[5::10, 5::10] = True  # every 10th pixel = 300 m spacing
    fields = FIELD | np.isin(LU_OLD, [1, 2])
    pick = (fields | grid) & LAND
    rows, cols = np.nonzero(pick)
    x, y = xy(TRANSFORM, rows, cols)
    lon, lat = warp_xy(CRS, "EPSG:4326", x, y)
    df = pd.DataFrame({"row": rows, "col": cols, "sample": np.where(fields[rows, cols], "field", "grid_300m"),
                       "x_utm34n": np.round(x, 1), "y_utm34n": np.round(y, 1),
                       "lon": np.round(lon, 6), "lat": np.round(lat, 6)})
    for k, a in stack.items():
        df[k] = a[rows, cols]
    df = df.round(4)
    df.to_csv(OUT / "study_points.csv", index=False)
    print(f"  study_points.csv: {len(df)} rows ({(df['sample'] == 'field').sum()} field pixels), {df.shape[1]} cols, "
          f"{(OUT / 'study_points.csv').stat().st_size / 1e6:.1f} MB")


# ------------------------------------------------------------------ 5. combined monthly / yearly series
def series():
    print("series")
    ms = lambda s, how="mean": getattr(s.resample("MS"), how)()
    pw = pd.read_parquet(PROC / "power_daily_1981_2026.parquet")
    im = pd.read_parquet(PROC / "imerg_daily_area_mean.parquet").precip_mm
    vi = pd.read_parquet(PROC / "modis_vi_16day_area.parquet").set_index("date")
    et = pd.read_parquet(PROC / "modis_et_8day_area.parquet").set_index("date")
    lst = pd.read_parquet(PROC / "modis_lst_8day_area.parquet").set_index("date")
    gda = pd.read_parquet(PROC / "grace_da_weekly_2003_2026.parquet")
    gda = gda[(gda.lat == 38.875) & (gda.lon == 23.375)].set_index("date")
    gm = pd.read_csv(PROC / "grace_mascon_tws_2002_2026.csv", parse_dates=["date"])
    gm = gm[(gm.lat == 38.75) & (gm.lon == 23.25)].set_index("date").tws_land_cm

    # 8-day composites -> daily rate -> monthly total (a composite spanning two months is split by its rate)
    def composite_month(s, days):
        daily = pd.Series(np.repeat((s / days).values, days.values),
                          index=np.concatenate([pd.date_range(d, periods=n) for d, n in zip(s.index, days)]))
        return daily.resample("MS").sum(min_count=20)

    m = pd.DataFrame({
        "rain_imerg_mm": ms(im, "sum").where(ms(im, "count") >= 28),
        "rain_power_mm": ms(pw.PRECTOTCORR, "sum"),
        "t2m_mean_c": ms(pw.T2M), "tmax_mean_c": ms(pw.T2M_MAX), "tmin_mean_c": ms(pw.T2M_MIN),
        "days_tmax_ge_35c": ms((pw.T2M_MAX >= 35).astype(int), "sum"),
        "rh2m_pct": ms(pw.RH2M), "wind2m_ms": ms(pw.WS2M),
        "power_soil_wetness_top": ms(pw.GWETTOP), "power_soil_wetness_root": ms(pw.GWETROOT),
        "modis_ndvi": ms(vi.ndvi_mean), "modis_evi": ms(vi.evi_mean),
        "modis_et_mm": composite_month(et.et_mean, et.days), "modis_pet_mm": composite_month(et.pet_mean, et.days),
        "modis_lst_day_c": ms(lst.lst_day_mean), "modis_lst_night_c": ms(lst.lst_night_mean),
        "gracda_surface_sm_pct": ms(gda.sfsm_pct), "gracda_rootzone_sm_pct": ms(gda.rtzsm_pct),
        "gracda_groundwater_pct": ms(gda.gws_pct), "grace_tws_anomaly_cm": ms(gm),
    })
    # Landsat NDVI by group: fields / woody x burned (dNBR >= 0.27) / unburned
    ds = xr.open_dataset(PROC / "landsat_ndvi_monthly_30m.nc")
    v = ds.ndvi.values
    groups = {"landsat_ndvi_fields_burned": FIELD & (BURN >= 2), "landsat_ndvi_fields_unburned": FIELD & (BURN == 0),
              "landsat_ndvi_woody_burned": (LU == 3) & (BURN >= 2), "landsat_ndvi_woody_unburned": (LU == 3) & (BURN == 0),
              "landsat_ndvi_grazing_burned": (LU == 4) & (BURN >= 2)}
    for k, mask in groups.items():
        sub = v[:, mask].astype("float32")
        sub = np.where(sub == 0, np.nan, (sub - 1) / 200 - 0.25)
        ok = np.isfinite(sub).mean(1) >= 0.3  # month needs >= 30 % of the group clear
        m[k] = pd.Series(np.where(ok, np.nanmedian(sub, 1), np.nan), index=pd.DatetimeIndex(ds.time.values).to_period("M")
                         .to_timestamp()).reindex(m.index)
    ds.close()
    m = m.loc["2000-01":"2025-12"]
    m.index.name = "month"
    m.round(3).to_csv(OUT / "area_monthly_2000_2025.csv")
    sums = [c for c in m if c.endswith("_mm") or c.startswith("days_")]
    y = pd.concat([m[sums].groupby(m.index.year).sum(min_count=12),
                   m.drop(columns=sums).groupby(m.index.year).mean()], axis=1)[m.columns]
    y.index.name = "year"
    y.round(3).to_csv(OUT / "area_yearly_2000_2025.csv")
    print(f"  area_monthly_2000_2025.csv: {len(m)} months x {m.shape[1]} series; area_yearly_2000_2025.csv")
    print("  groups (pixels):", {k: int(v.sum()) for k, v in groups.items()})


# ------------------------------------------------------------------ 6. atlas
def atlas(veg, hist, wh):
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap, TwoSlopeNorm
    from matplotlib.patches import Patch

    print("atlas")
    terr, _ = read_tif("terrain_30m.tif")
    soil, _ = read_tif("soil_30m.tif")
    ext = (TRANSFORM.c, TRANSFORM.c + TRANSFORM.a * SHAPE[1], TRANSFORM.f + TRANSFORM.e * SHAPE[0], TRANSFORM.f)
    land = lambda a: np.where(LAND, a, np.nan)
    INK, INK2, SURF = "#0b0b0b", "#52514e", "#fcfcfb"
    lu_cmap = ListedColormap(["#eda100", "#2a78d6", "#008300", "#e87ba4", "#b5b4ae"])
    panels = [
        ("Elevation (m) · NASADEM", land(terr["elevation_m"]), dict(cmap="Greys")),
        ("Slope (°) · NASADEM", land(terr["slope_deg"]), dict(cmap="Greys", vmax=35)),
        ("Land use 2013–2020 · Landsat", np.where(LU > 0, LU, np.nan),
         dict(cmap=lu_cmap, norm=BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5, 5.5], 5))),
        ("Burn severity 2021 (0–4) · Landsat dNBR", np.where(LAND, BURN, np.nan), dict(cmap="Oranges", vmin=0, vmax=4)),
        ("Summer NDVI before (2016–20)", veg["ndvi_summer_before"], dict(cmap="Greens", vmin=0, vmax=0.8)),
        ("Summer NDVI after (2022–25)", veg["ndvi_summer_after"], dict(cmap="Greens", vmin=0, vmax=0.8)),
        ("Summer NDVI change", veg["ndvi_summer_change"], dict(cmap="BrBG", norm=TwoSlopeNorm(0, -0.4, 0.4))),
        ("Autumn NDVI 2021 (bare before storms)", veg["ndvi_autumn_2021"], dict(cmap="Greens", vmin=0, vmax=0.8)),
        ("Bare months / year after", veg["bare_months_per_year_after"], dict(cmap="Oranges", vmin=0, vmax=12)),
        ("Fields: crop share change", hist["crop_share_change"], dict(cmap="BrBG", norm=TwoSlopeNorm(0, -1, 1))),
        ("Soil water capacity 0–100 cm (mm) · SoilGrids", land(soil["awc_mm_0_100"]), dict(cmap="Blues")),
        ("RUSLE LS factor · NASADEM", land(terr["ls_factor"]), dict(cmap="Oranges", vmax=15)),
        ("ET change (mm/yr) · MODIS 500 m", wh["modis_et_change"], dict(cmap="BrBG", norm=TwoSlopeNorm(0, -300, 300))),
        ("Summer day LST change (°C) · MODIS 1 km", wh["modis_lst_day_summer_change"],
         dict(cmap="RdBu_r", norm=TwoSlopeNorm(0, -8, 8))),
        ("Dry-season ET (mm/day) · ECOSTRESS 70 m", wh["ecostress_et_mm_day_2022_2025"], dict(cmap="Blues", vmin=0)),
        ("Rain (mm/yr) · GPM IMERG 10 km", wh["imerg_rain_mm_year_2001_2024"], dict(cmap="Blues")),
    ]
    plt.rcParams.update({"font.size": 8, "figure.facecolor": SURF, "axes.facecolor": "#ffffff"})
    fig, axs = plt.subplots(4, 4, figsize=(13, 17))
    for a, (title, arr, kw) in zip(axs.flat, panels):
        im = a.imshow(land(arr), extent=ext, interpolation="nearest", **kw)
        a.set_title(title, loc="left", color=INK, fontsize=8.5)
        a.set_xticks([]), a.set_yticks([])
        for s in a.spines.values():
            s.set_color("#e4e3df")
        if "Land use" in title:
            a.legend(handles=[Patch(color=lu_cmap(i), label=l) for i, l in enumerate(
                ["rainfed field", "irrigated field", "woody", "grazing", "bare/built"])], loc="lower left",
                fontsize=6.5, frameon=True)
        else:
            cb = fig.colorbar(im, ax=a, fraction=0.046, pad=0.02)
            cb.ax.tick_params(labelsize=7, colors=INK2)
            cb.outline.set_visible(False)
    fig.suptitle("North Evia study area (Kireas – Agia Anna) · NASA/USGS layers on the 30 m grid · "
                 "before = 2016–2020, after = 2022–2025", x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    fig.savefig(OUT / "atlas.png", dpi=110)
    print("  atlas.png")


if __name__ == "__main__":
    veg = vegetation()
    hist = fields_history()
    wh = water_heat()
    points([veg, hist, wh])
    series()
    atlas(veg, hist, wh)
