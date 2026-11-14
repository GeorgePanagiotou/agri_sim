"""NASADEM (NASA, 1 arc-second ~30 m) terrain on the study-area Landsat grid: elevation, slope, D8 flow accumulation,
RUSLE LS factor, and the share of each pixel's upslope area that burned in 2021 (moderate-low or worse,
dNBR >= 0.27 from landsat_burn_2021.py).

Download: one NASADEM_HGT tile (~25 MB zip) via earthaccess into data/raw/nasadem/ (git-ignored).
Output: data/processed/terrain_30m.tif
  band 1 elevation (m) · 2 slope (deg) · 3 upslope area (cells, incl. itself) · 4 LS factor (RUSLE, Moore & Burch,
  slope length capped at 300 m) · 5 upslope burned share (0-1)

    ..\\.venv\\Scripts\\python.exe data_prep\\terrain_nasadem.py
"""
import heapq
import zipfile

import earthaccess
import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from config import PROC, RAW, STUDY_AREA
from landsat_common import CRS, HEIGHT, RES, TRANSFORM, WIDTH, profile

W, E, S, N = STUDY_AREA
out_dir = RAW / "nasadem"
out_dir.mkdir(parents=True, exist_ok=True)
def tile_name(lon, lat):
    return f"{'n' if lat >= 0 else 's'}{abs(int(np.floor(lat))):02d}{'e' if lon >= 0 else 'w'}{abs(int(np.floor(lon))):03d}"


needed = {tile_name(lon, lat) for lon in np.arange(np.floor(W), E, 1.0) for lat in np.arange(np.floor(S), N, 1.0)}
have = {z.stem.split("_")[-1].lower(): z for z in out_dir.glob("NASADEM_HGT_*.zip")}
if not needed <= set(have):
    earthaccess.login(strategy="netrc")
    res = earthaccess.search_data(short_name="NASADEM_HGT", bounding_box=(W, S, E, N))
    earthaccess.download(res, str(out_dir))
    have = {z.stem.split("_")[-1].lower(): z for z in out_dir.glob("NASADEM_HGT_*.zip")}
zips = [have[k] for k in sorted(needed) if k in have]
if not zips:
    raise SystemExit(f"No NASADEM tiles for {sorted(needed)} (sea only?)")

dem = np.full((HEIGHT, WIDTH), np.nan, "float32")
for z in zips:  # several 1-degree tiles when the area crosses a degree line
    hgt = next(n for n in zipfile.ZipFile(z).namelist() if n.endswith(".hgt"))
    print("NASADEM tile:", z.name, hgt)
    part = np.full((HEIGHT, WIDTH), np.nan, "float32")
    with rasterio.open(f"/vsizip/{z.as_posix()}/{hgt}") as src:
        reproject(rasterio.band(src, 1), part, dst_transform=TRANSFORM, dst_crs=CRS, resampling=Resampling.bilinear,
                  src_nodata=-32768, dst_nodata=np.nan)
    dem = np.where(np.isfinite(part), part, dem)
dem[dem < -20] = np.nan
sea = ~np.isfinite(dem) | (dem <= 0)

# slope (deg)
gy, gx = np.gradient(np.where(sea, 0, dem), RES)
slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")

# priority-flood with epsilon (Barnes et al. 2014): every land cell drains to the sea / grid edge
H, Wd = dem.shape
z = np.where(sea, -1e9, dem).astype("float64")
filled = z.copy()
done = np.zeros_like(sea)
heap = []
for r in range(H):
    for c in range(Wd):
        if sea[r, c] or r in (0, H - 1) or c in (0, Wd - 1):
            heapq.heappush(heap, (filled[r, c], r, c)); done[r, c] = True
NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
while heap:
    h, r, c = heapq.heappop(heap)
    for dr, dc in NB:
        rr, cc = r + dr, c + dc
        if 0 <= rr < H and 0 <= cc < Wd and not done[rr, cc]:
            done[rr, cc] = True
            filled[rr, cc] = max(filled[rr, cc], h + 1e-3)
            heapq.heappush(heap, (filled[rr, cc], rr, cc))

# D8 receiver = steepest downhill neighbour on the filled surface
rec = np.full((H, Wd), -1, "int64")
best = np.zeros((H, Wd))
for dr, dc in NB:
    dist = RES * (2 ** 0.5 if dr and dc else 1)
    shifted = np.full((H, Wd), np.inf)
    shifted[max(0, -dr):H - max(0, dr), max(0, -dc):Wd - max(0, dc)] = \
        filled[max(0, dr):H - max(0, -dr) if max(0, -dr) else H, max(0, dc):Wd - max(0, -dc) if max(0, -dc) else Wd]
    drop = (filled - shifted) / dist
    better = drop > best
    best[better] = drop[better]
    tgt = (np.arange(H)[:, None] + dr) * Wd + (np.arange(Wd)[None, :] + dc)
    rec[better] = tgt[better]
rec[sea] = -1

if (PROC / "landsat_dnbr_2021_30m.tif").exists():
    with rasterio.open(PROC / "landsat_dnbr_2021_30m.tif") as s:
        burned = (np.nan_to_num(s.read(1), nan=0) >= 0.27) & ~sea
else:  # areas without a mapped fire: upslope burned share = 0
    burned = np.zeros_like(sea)

# accumulate from high to low
order = np.argsort(-filled, axis=None)
acc = np.ones(H * Wd)
bacc = burned.ravel().astype("float64")
recf = rec.ravel()
for i in order:
    j = recf[i]
    if j >= 0:
        acc[j] += acc[i]
        bacc[j] += bacc[i]
acc = acc.reshape(H, Wd); bacc = bacc.reshape(H, Wd)
burn_share = np.where(sea, np.nan, bacc / acc).astype("float32")

# RUSLE LS (Moore & Burch 1986): (As / 22.13)^0.4 * (sin b / 0.0896)^1.3, As = specific catchment area, capped
As = np.minimum(acc * RES, 300.0)
ls = ((As / 22.13) ** 0.4 * (np.sin(np.radians(slope)) / 0.0896) ** 1.3).astype("float32")
for a in (slope, ls):
    a[sea] = np.nan

with rasterio.open(PROC / "terrain_30m.tif", "w", **profile("float32", count=5, nodata=np.nan)) as dst:
    dst.write(np.stack([dem, slope, np.where(sea, np.nan, acc).astype("float32"), ls, burn_share]))
    dst.descriptions = ("elevation_m", "slope_deg", "upslope_cells", "ls_factor", "upslope_burned_share")
land = ~sea
print({"land_ha": int(land.sum() * 0.09), "elev_m_median": round(float(np.nanmedian(dem[land]))),
       "slope_deg_median": round(float(np.nanmedian(slope[land])), 1),
       "slope_gt15deg_share": round(float((slope[land] > 15).mean()), 2),
       "ls_median": round(float(np.nanmedian(ls[land])), 2)})
