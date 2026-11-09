"""Scratch: map fields / grazing land in the study area from the spring 2021 Sentinel-2 composite (10 m), find which
burned (dNBR July->Sept with a threshold taken from unburned fields outside the EFFIS perimeter), and whether they
were green again in spring 2022.  Writes a small field-class GeoTIFF, stats JSON and PNG.

    python fields_study.py <study_dir> <worldcover_2020.tif> <effis_2021_perimeter.geojson> <out_dir>
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject

S, WC, PERIM, OUT = (Path(a) for a in sys.argv[1:5])
OUT.mkdir(parents=True, exist_ok=True)


def load(period):
    with rasterio.open(sorted((S / period).glob("*.tif"))[0]) as src:
        a = src.read().astype("float32")
        names = list(src.descriptions)
        prof = src.profile
    return {b: a[names.index(b)] for b in ("B02", "B03", "B04", "B08", "B11", "B12")}, prof


sp21, prof = load("spring_2021")
su21, _ = load("summer_2021")
po21, _ = load("post_2021")
sp22, _ = load("spring_2022")
H, W = sp21["B04"].shape
ha = abs(prof["transform"].a * prof["transform"].e) / 1e4


def ndvi(x):
    with np.errstate(all="ignore"):
        return (x["B08"] - x["B04"]) / (x["B08"] + x["B04"])


def nbr(x):
    with np.errstate(all="ignore"):
        return (x["B08"] - x["B12"]) / (x["B08"] + x["B12"])


n_sp21, n_su21, n_sp22 = ndvi(sp21), ndvi(su21), ndvi(sp22)
dnbr = nbr(su21) - nbr(po21)

lc = np.zeros((H, W), "uint8")
with rasterio.open(WC) as src:
    reproject(rasterio.band(src, 1), lc, dst_transform=prof["transform"], dst_crs=prof["crs"], resampling=Resampling.nearest)
perim = gpd.read_file(PERIM).to_crs(prof["crs"])
inside = rasterize(perim.geometry, out_shape=(H, W), transform=prof["transform"], fill=0, default_value=1).astype(bool)

# Herbaceous = green in spring, dry/harvested in July (cereals, hay, grassland)
herb = (n_sp21 >= 0.45) & (n_su21 <= 0.32) & np.isfinite(dnbr)
field = herb & (lc == 40)                 # arable fields (WorldCover cropland)
graze = herb & np.isin(lc, (20, 30))      # grass / shrub = grazing land
summer_green = (n_su21 >= 0.5) & (lc == 40)  # irrigated summer crops (green in July)

# Threshold from unburned herbaceous land outside the perimeter: change from drying/harvest alone
null = dnbr[herb & ~inside]
thr = float(np.nanpercentile(null, 95))
burned = dnbr > max(thr, 0.08)

classes = np.zeros((H, W), "uint8")  # 0 other, 1 field unburned, 2 field burned, 3 grazing unburned, 4 grazing burned,
classes[field & ~burned] = 1          # 5 irrigated summer crop, 6 forest burned (tree, dNBR > 0.27)
classes[field & burned] = 2
classes[graze & ~burned] = 3
classes[graze & burned] = 4
classes[summer_green] = 5
classes[(lc == 10) & (dnbr > 0.27)] = 6
with rasterio.open(OUT / "field_classes_10m.tif", "w", **(prof | {"count": 1, "dtype": "uint8", "nodata": None,
                                                              "compress": "deflate"})) as dst:
    dst.write(classes, 1)
    dst.update_tags(classes="0 other, 1 field unburned, 2 field burned, 3 grazing unburned, 4 grazing burned, "
                            "5 irrigated summer crop, 6 forest burned", dnbr_threshold=f"{thr:.3f}")


def stat(m):
    return {"ha": round(float(m.sum() * ha)),
            "ndvi_spring21": round(float(np.nanmedian(n_sp21[m])), 2) if m.any() else None,
            "ndvi_spring22": round(float(np.nanmedian(n_sp22[m])), 2) if m.any() else None,
            "green_again_2022_share": round(float((n_sp22[m] >= 0.45).mean()), 2) if m.any() else None}


st = {"dnbr_threshold_from_unburned_herbaceous_p95": round(thr, 3),
      "fields_burned": stat(field & burned), "fields_unburned": stat(field & ~burned),
      "fields_inside_perimeter": stat(field & inside), "fields_outside_perimeter": stat(field & ~inside),
      "grazing_burned": stat(graze & burned), "grazing_unburned": stat(graze & ~burned),
      "irrigated_summer_crops": stat(summer_green),
      "worldcover_cropland_total_ha": round(float((lc == 40).sum() * ha))}
print(json.dumps(st, indent=1))
json.dump(st, open(OUT / "field_stats.json", "w"), indent=1)

# figure: spring 2021 RGB | post-fire RGB | spring 2022 RGB | classes
def rgb(x):
    return np.clip(np.nan_to_num(np.dstack([x["B04"], x["B03"], x["B02"]]) / 2200), 0, 1) ** (1 / 1.4)
cols = ["#00000000", "#e8c34a", "#b2182b", "#a6d96a", "#5e3c99", "#1a9850", "#3a3a3a"]
cm = matplotlib.colors.ListedColormap(cols)
fig, axs = plt.subplots(1, 4, figsize=(24, 9), dpi=100)
for ax, img, t in zip(axs, (rgb(sp21), rgb(po21), rgb(sp22)), ("Spring 2021 (before)", "Sept 2021 (after fire)",
                                                                 "Spring 2022 (first spring after)")):
    ax.imshow(img); ax.set_title(t); ax.axis("off")
axs[3].imshow(rgb(sp21) * 0.35 + 0.6); axs[3].imshow(classes, cmap=cm, vmin=0, vmax=6, interpolation="nearest")
axs[3].set_title(f"Fields & grazing land (burned: dNBR > {thr:.2f})"); axs[3].axis("off")
labels = ["field, unburned", "field, burned", "grazing, unburned", "grazing, burned", "irrigated summer crop",
          "forest, burned"]
axs[3].legend(handles=[matplotlib.patches.Patch(color=c, label=l) for c, l in zip(cols[1:], labels)],
              loc="lower left", fontsize=9)
plt.tight_layout(); plt.savefig(OUT / "fields_study_area.png"); print(OUT / "fields_study_area.png")
