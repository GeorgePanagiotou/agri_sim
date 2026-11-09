"""Scratch: quick-look PNGs (pre/post RGB, dNBR, land cover + burn) with the candidate windows."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import ListedColormap
from matplotlib.patches import Rectangle
from rasterio.warp import transform as wtransform

D = Path(sys.argv[1])
picks = json.load(open(D / sys.argv[2]))["picks"] if len(sys.argv) > 2 else []
BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]


def rgb(period):
    f = sorted((D / period).glob("*.tif"))[0]
    with rasterio.open(f) as src:
        a = src.read().astype("float32")
        names = list(src.descriptions)
        tr, crs = src.transform, src.crs
    idx = [names.index(b) for b in ("B04", "B03", "B02")] if all(names) else [2, 1, 0]
    img = np.dstack([a[i] for i in idx]) / 2500.0
    return np.clip(np.nan_to_num(img), 0, 1) ** (1 / 1.4), tr, crs


pre, tr, crs = rgb("pre_2021-07")
post, _, _ = rgb("post_2021-09")
with rasterio.open(D / "dnbr.tif") as s:
    dnbr = s.read(1)
with rasterio.open(D / "worldcover_on_s2grid.tif") as s:
    lc = s.read(1)
H, W = dnbr.shape
ext = [tr.c, tr.c + tr.a * W, tr.f + tr.e * H, tr.f]

lc_col = {0: "#ffffff", 10: "#2f6b2f", 20: "#b5a13a", 30: "#d7e38a", 40: "#e8a33b", 50: "#c0392b", 60: "#bbbbbb",
          80: "#9cc8e8", 90: "#4fa3a3"}
lut = np.zeros((256, 4)); [lut.__setitem__(k, matplotlib.colors.to_rgba(v)) for k, v in lc_col.items()]
lc_img = lut[lc]
burn = np.nan_to_num(dnbr) > 0.27
lc_img[burn & (lc != 80)] = lc_img[burn & (lc != 80)] * 0.45  # burned land darkened

fig, axs = plt.subplots(2, 2, figsize=(18, 11), dpi=110)
panels = [(pre, "Sentinel-2 · July 2021 (before)"), (post, "Sentinel-2 · Aug–Sep 2021 (after)"),
          (None, "dNBR burn severity (>0.27 = burned)"), (lc_img, "ESA WorldCover 2020 · burned land darkened")]
for ax, (img, title) in zip(axs.flat, panels):
    if img is None:
        im = ax.imshow(np.nan_to_num(dnbr), extent=ext, cmap="magma_r", vmin=-0.1, vmax=0.9)
        fig.colorbar(im, ax=ax, shrink=0.7)
    else:
        ax.imshow(img, extent=ext)
    ax.set_title(title)
    ax.set_xticks([]); ax.set_yticks([])
    for i, p in enumerate(picks, 1):
        w, s_, e, n = p["bbox_wsen"]
        xs, ys = wtransform("EPSG:4326", crs, [w, e], [s_, n])
        ax.add_patch(Rectangle((xs[0], ys[0]), xs[1] - xs[0], ys[1] - ys[0], fill=False, ec="cyan", lw=1.8))
        ax.text(xs[0], ys[1], f" {i}", color="cyan", fontsize=12, fontweight="bold", va="bottom")
handles = [matplotlib.patches.Patch(color=lc_col[k], label=n) for k, n in
           [(10, "tree"), (20, "shrub"), (30, "grass"), (40, "cropland"), (50, "built"), (60, "bare")]]
axs[1, 1].legend(handles=handles, loc="lower left", fontsize=8)
plt.tight_layout()
plt.savefig(D / "quicklook_evia_2021.png")
print(D / "quicklook_evia_2021.png")

# zoom per pick: pre RGB | post RGB | land cover
for i, p in enumerate(picks[:3], 1):
    w, s_, e, n = p["bbox_wsen"]
    xs, ys = wtransform("EPSG:4326", crs, [w, e], [s_, n])
    c0, c1 = int((xs[0] - tr.c) / tr.a), int((xs[1] - tr.c) / tr.a)
    r0, r1 = int((ys[1] - tr.f) / tr.e), int((ys[0] - tr.f) / tr.e)
    fig, axs = plt.subplots(1, 3, figsize=(18, 6.2), dpi=110)
    for ax, img, t in zip(axs, (pre, post, lc_img), ("before (Jul 2021)", "after (Aug–Sep 2021)", "land cover 2020, burned darkened")):
        ax.imshow(img[r0:r1, c0:c1]); ax.set_title(f"Window {i} · {t}"); ax.set_xticks([]); ax.set_yticks([])
    plt.tight_layout(); plt.savefig(D / f"zoom_{i}.png"); plt.close()
    print(D / f"zoom_{i}.png")
