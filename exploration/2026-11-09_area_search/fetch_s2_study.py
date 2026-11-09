"""Scratch (delete later): Sentinel-2 L2A cloud-masked median composites of the STUDY AREA (Kireas - Agia Anna)
at 10 m, for field mapping: spring 2021 (green crops, before the fire), July 2021, Sept 2021, spring 2022.

Runs in STAIR's venv with STAIR's stored CDSE sign-in (run in place). Writes one GeoTIFF per period plus
job-results.json (the list of scenes used).
"""
import sys
import time
from pathlib import Path

from src.datasources.download import _openeo_connect  # STAIR, run in place

AOI = {"west": 23.32, "south": 38.75, "east": 23.50, "north": 38.95}
PERIODS = {
    "spring_2021": ("2021-03-25", "2021-05-11"),
    "summer_2021": ("2021-07-01", "2021-08-03"),
    "post_2021": ("2021-08-20", "2021-09-21"),
    "spring_2022": ("2022-03-25", "2022-05-11"),
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
                                bands=BANDS, max_cloud_cover=60)
    scl = conn.load_collection("SENTINEL2_L2A", spatial_extent=AOI, temporal_extent=[start, end],
                               bands=["SCL"], max_cloud_cover=60).band("SCL")
    mask = (scl == 0) | (scl == 3) | (scl == 8) | (scl == 9) | (scl == 10)
    cube = cube.resample_spatial(resolution=10, projection=32634, method="near")
    mask = mask.resample_cube_spatial(cube, method="near")
    comp = cube.mask(mask).reduce_dimension(dimension="t", reducer="median")
    job = comp.create_job(title=f"agrisim_study_{name}", out_format="GTiff")
    t0 = time.time()
    print("started", name, flush=True)
    job.start_and_wait(print=lambda *a, **k: None, max_poll_interval=30)
    target.mkdir(parents=True, exist_ok=True)
    job.get_results().download_files(target)
    print("done", name, f"{time.time() - t0:.0f}s", flush=True)
