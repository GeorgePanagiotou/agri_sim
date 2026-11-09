"""SoilGrids 2.0 (ISRIC, 250 m; supporting data, not NASA) for the study area, warped to the 30 m Landsat grid
(window reads of the public VRT/COGs, nothing downloaded whole), plus derived soil-water and erodibility layers.

Properties (mean, depths 0-5, 5-15, 15-30, 30-60, 60-100 cm): clay, sand, silt (g/kg), soc (dg/kg), bdod (cg/cm3),
cfvo (coarse fragments, cm3/dm3), phh2o (pH*10), nitrogen (cg/kg).

Derived
- field capacity / wilting point per depth: Saxton & Rawls (2006) pedotransfer functions (sand, clay, organic matter
  = 1.724 * SOC); available water capacity AWC (mm) for 0-30 cm and 0-100 cm, reduced for coarse fragments
- RUSLE K (t ha h ha-1 MJ-1 mm-1) of the topsoil (0-15 cm): Williams (1995, EPIC) x 0.1317

Output: data/processed/soil_30m.tif (bands named) + data/processed/soil_summary.csv (median per land use)

    ..\\.venv\\Scripts\\python.exe data_prep\\soil_soilgrids.py
"""
import numpy as np
import pandas as pd
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling

from config import PROC
from landsat_common import CRS, HEIGHT, TRANSFORM, WIDTH, profile

URL = "/vsicurl/https://files.isric.org/soilgrids/latest/data/{p}/{p}_{d}_mean.vrt"
PROPS = {"clay": 10, "sand": 10, "silt": 10, "soc": 10, "bdod": 100, "cfvo": 10, "phh2o": 10, "nitrogen": 100}
# scale -> clay/sand/silt %, soc g/kg, bdod g/cm3, cfvo %, pH, nitrogen g/kg
DEPTHS = {"0-5cm": 50, "5-15cm": 100, "15-30cm": 150, "30-60cm": 300, "60-100cm": 400}  # thickness mm


def read(prop, depth):
    with rasterio.open(URL.format(p=prop, d=depth)) as src, WarpedVRT(
            src, crs=CRS, transform=TRANSFORM, width=WIDTH, height=HEIGHT, resampling=Resampling.bilinear,
            src_nodata=src.nodata, nodata=np.nan, dtype="float32") as vrt:
        return vrt.read(1) / PROPS[prop]


soil = {(p, d): read(p, d) for p in PROPS for d in DEPTHS}
print("read", len(soil), "layers")


def saxton_rawls(sand_pct, clay_pct, om_pct):
    S, C, OM = sand_pct / 100, clay_pct / 100, np.clip(om_pct, 0, 8)
    t1500 = -0.024 * S + 0.487 * C + 0.006 * OM + 0.005 * S * OM - 0.013 * C * OM + 0.068 * S * C + 0.031
    wp = t1500 + (0.14 * t1500 - 0.02)
    t33 = -0.251 * S + 0.195 * C + 0.011 * OM + 0.006 * S * OM - 0.027 * C * OM + 0.452 * S * C + 0.299
    fc = t33 + (1.283 * t33 ** 2 - 0.374 * t33 - 0.015)
    return fc, wp


awc = {}
for d, th in DEPTHS.items():
    fc, wp = saxton_rawls(soil[("sand", d)], soil[("clay", d)], 1.724 * soil[("soc", d)] / 10)
    awc[d] = np.clip(fc - wp, 0, None) * th * (1 - soil[("cfvo", d)] / 100)  # mm in the layer
awc30 = awc["0-5cm"] + awc["5-15cm"] + awc["15-30cm"]
awc100 = awc30 + awc["30-60cm"] + awc["60-100cm"]


def k_epic(sand, silt, clay, orgc):
    sn1 = 1 - sand / 100
    f_cs = 0.2 + 0.3 * np.exp(-0.256 * sand * (1 - silt / 100))
    f_cl = (silt / np.maximum(clay + silt, 1e-3)) ** 0.3
    f_oc = 1 - 0.25 * orgc / (orgc + np.exp(3.72 - 2.95 * orgc))
    f_hs = 1 - 0.7 * sn1 / (sn1 + np.exp(-5.51 + 22.9 * sn1))
    return 0.1317 * f_cs * f_cl * f_oc * f_hs


top = lambda p: (soil[(p, "0-5cm")] * 50 + soil[(p, "5-15cm")] * 100) / 150
K = k_epic(top("sand"), top("silt"), top("clay"), top("soc") / 10)  # orgC in %

bands = {"clay_pct_0_30": None, "sand_pct_0_30": None, "silt_pct_0_30": None, "soc_gkg_0_30": None,
         "bdod_gcm3_0_30": None, "cfvo_pct_0_30": None, "ph_0_30": None, "nitrogen_gkg_0_30": None}
w = np.array([50, 100, 150]) / 300
for name, p in zip(bands, PROPS):
    bands[name] = sum(soil[(p, d)] * wi for d, wi in zip(("0-5cm", "5-15cm", "15-30cm"), w))
bands |= {"awc_mm_0_30": awc30, "awc_mm_0_100": awc100, "rusle_k": K}

with rasterio.open(PROC / "soil_30m.tif", "w", **profile("float32", count=len(bands), nodata=np.nan)) as dst:
    dst.write(np.stack([b.astype("float32") for b in bands.values()]))
    dst.descriptions = tuple(bands)
    dst.update_tags(source="SoilGrids 2.0 (ISRIC) mean, 250 m, warped bilinear to 30 m; AWC Saxton & Rawls 2006; "
                           "K Williams 1995 (EPIC) x 0.1317 (t ha h / ha MJ mm)")

with rasterio.open(PROC / "landsat_field_map_30m.tif") as s:
    lu = s.read(1)
names = {1: "rainfed field", 2: "irrigated field", 3: "woody", 4: "grazing (herb/shrub)"}
rows = [{"land_use": n, **{k: round(float(np.nanmedian(v[lu == c])), 3) for k, v in bands.items()}}
        for c, n in names.items()]
df = pd.DataFrame(rows)
df.to_csv(PROC / "soil_summary.csv", index=False)
print(df.T.to_string())
