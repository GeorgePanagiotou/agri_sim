"""Scratch (delete later): Sentinel-2 L2A cloud-masked median composites of North Evia, pre- and post-fire 2021.

Runs in STAIR's venv and uses STAIR's stored CDSE sign-in (src.datasources.download._openeo_connect), in place.
Bands: B02 B03 B04 (RGB), B08 (NIR), B11 B12 (SWIR) at 20 m, UTM 34N.

    PYTHONPATH=<STAIR>/backend <STAIR>/.venv/Scripts/python.exe fetch_s2.py <out_dir> <period> [<period> ...]
"""
import sys
import time
from pathlib import Path

from src.datasources.download import _openeo_connect  # STAIR, run in place

AOI = {"west": 22.80, "south": 38.60, "east": 23.70, "north": 39.05}
PERIODS = {
    "pre_2021-07": ("2021-07-01", "2021-08-03"),   # fire started 3 Aug 2021 (end date excluded)
    "post_2021-09": ("2021-08-20", "2021-09-21"),
}
BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]

out = Path(sys.argv[1])
wanted = sys.argv[2:] or list(PERIODS)
conn = _openeo_connect()
print("connected", flush=True)

for name in wanted:
    target = out / name
    if any(target.glob("*.tif")):
        print("exists, skipping", name, flush=True)
        continue
    start, end = PERIODS[name]
    cube = conn.load_collection("SENTINEL2_L2A", spatial_extent=AOI, temporal_extent=[start, end],
                                bands=BANDS, max_cloud_cover=50)
    scl = conn.load_collection("SENTINEL2_L2A", spatial_extent=AOI, temporal_extent=[start, end],
                               bands=["SCL"], max_cloud_cover=50).band("SCL")
    # cloud shadow 3, cloud medium/high 8/9, cirrus 10, no data 0
    mask = (scl == 0) | (scl == 3) | (scl == 8) | (scl == 9) | (scl == 10)
    cube = cube.resample_spatial(resolution=20, projection=32634, method="average")
    mask = mask.resample_cube_spatial(cube, method="near")
    comp = cube.mask(mask).reduce_dimension(dimension="t", reducer="median")
    job = comp.create_job(title=f"agrisim_evia_{name}", out_format="GTiff")
    t0 = time.time()
    print("started", name, flush=True)
    job.start_and_wait(print=lambda *a, **k: print(*a, flush=True), max_poll_interval=30)
    target.mkdir(parents=True, exist_ok=True)
    job.get_results().download_files(target)
    print("done", name, f"{time.time() - t0:.0f}s", [p.name for p in target.iterdir()], flush=True)
