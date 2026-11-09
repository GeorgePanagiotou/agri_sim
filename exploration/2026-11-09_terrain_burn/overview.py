"""Overview figure: NASADEM terrain, burned share of the upslope area with fields, MODIS burn date (run from agrisim/).

    ..\\.venv\\Scripts\\python.exe exploration\\2026-11-09_terrain_burn\\overview.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

P = Path("data/processed")
OUT = Path(__file__).parent
with rasterio.open(P / "terrain_30m.tif") as s:
    elev, slope, acc, ls, bshare = s.read()
with rasterio.open(P / "landsat_field_map_30m.tif") as s:
    lu = s.read(1)
with rasterio.open(P / "modis_mcd64a1_2021_burndate.tif") as s:
    doy = s.read(1).astype("float32")
fields = np.isin(lu, (1, 2))
hill = np.nan_to_num(slope) / 40

fig, axs = plt.subplots(1, 4, figsize=(24, 8.5), dpi=100)
im = axs[0].imshow(elev, cmap="terrain", vmin=0, vmax=900); axs[0].set_title("NASADEM elevation (m)")
fig.colorbar(im, ax=axs[0], shrink=0.6)
im = axs[1].imshow(slope, cmap="magma_r", vmin=0, vmax=35); axs[1].set_title("Slope (deg)")
fig.colorbar(im, ax=axs[1], shrink=0.6)
axs[2].imshow(hill, cmap="Greys", vmin=0, vmax=1.5)
bs = np.where(fields, bshare, np.nan)
im = axs[2].imshow(bs, cmap="YlOrRd", vmin=0, vmax=1, interpolation="nearest")
axs[2].set_title("Fields: share of upslope area burned in 2021"); fig.colorbar(im, ax=axs[2], shrink=0.6)
d = np.where(doy > 0, doy, np.nan)
axs[3].imshow(hill, cmap="Greys", vmin=0, vmax=1.5)
im = axs[3].imshow(d, cmap="viridis", vmin=214, vmax=223, interpolation="nearest")
cb = fig.colorbar(im, ax=axs[3], shrink=0.6, ticks=range(214, 224))
cb.ax.set_yticklabels([f"{d - 212} Aug" for d in range(214, 224)])
axs[3].set_title("MODIS MCD64A1 burn date, Aug 2021")
for a in axs:
    a.axis("off")
plt.tight_layout(); plt.savefig(OUT / "terrain_burn_overview.png"); print(OUT / "terrain_burn_overview.png")
