"""Small Landsat true-colour images of the study area for the team to look at (30 m, uint8 GeoTIFF + PNG preview).
For each window the clearest scene (from data/processed/landsat_scenes.csv) is read as a window and saved; ~1 MB each.

Output: data/processed/imagery/landsat_rgb_<date>_<platform>.tif / .png  + imagery/README.md (scene list)

    ..\\.venv\\Scripts\\python.exe data_prep\\landsat_rgb.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio

from config import PROC
from landsat_common import catalog, clear_mask, profile, reflectance

WINDOWS = {  # label: (start, end, why)
    "spring_1987": ("1987-03-15", "1987-06-15", "fields 'then' (Landsat 5)"),
    "pre_fire_2021": ("2021-07-01", "2021-08-02", "just before the fire"),
    "post_fire_2021": ("2021-08-16", "2021-10-07", "after the fire, before storm Athena"),
    "spring_2022": ("2022-03-15", "2022-06-15", "first spring after the fire"),
    "spring_2025": ("2025-03-15", "2025-06-15", "recent"),
}
OUT = PROC / "imagery"
OUT.mkdir(parents=True, exist_ok=True)
sc = pd.read_csv(PROC / "landsat_scenes.csv")
sc = sc[sc.platform != "landsat-7"]  # avoid SLC-off stripes
cat = catalog()
lines = ["# Landsat true-colour images (study area, 30 m)", "", "| File | Scene | Why |", "|---|---|---|"]
for label, (a, b, why) in WINDOWS.items():
    cand = sc[(sc.date >= a) & (sc.date <= b)].sort_values(["valid_share", "cloud_cover"], ascending=[False, True])
    item = next(cat.search(collections=["landsat-c2-l2"], ids=[cand.id.iloc[0]]).items())
    rgb = np.stack([reflectance(item, k) for k in ("red", "green", "blue")])
    ok = clear_mask(item)
    img = np.clip(rgb / 0.25, 0, 1) ** (1 / 1.6)
    u8 = np.where(np.isfinite(img), np.round(img * 254) + 1, 0).astype("uint8")
    name = f"landsat_rgb_{item.properties['datetime'][:10]}_{item.properties['platform']}"
    with rasterio.open(OUT / f"{name}.tif", "w", **profile("uint8", count=3, nodata=0)) as dst:
        dst.write(u8)
    plt.imsave(OUT / f"{name}.png", np.moveaxis(u8, 0, -1))
    lines.append(f"| `{name}.tif` / `.png` | {item.id} (clear {ok.mean():.0%}) | {why} |")
    print(name, f"clear {ok.mean():.0%}")
(OUT / "README.md").write_text("\n".join(lines) + "\n\nSource: Landsat Collection 2 Level-2 (USGS/NASA), "
                               "via Microsoft Planetary Computer. Reflectance stretched 0-0.25, gamma 1.6.\n",
                               encoding="utf-8")
