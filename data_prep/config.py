"""Shared settings for the data scripts: area, periods, demo fields, paths.

The area comes from configs/areas/<name>.yaml, selected with the environment variable AGRISIM_AREA (default "evia",
which keeps the original data/ paths and the UTM 34N grid). See src/agrisim/area.py.
"""
from pathlib import Path

from agrisim.area import load as _load_area

AREA = _load_area()
AREA_NAME = AREA.name

# Analysis area (lon_min, lon_max, lat_min, lat_max), WGS84
AOI = AREA.aoi
STUDY_AREA = AREA.study_area
CRS = AREA.crs  # UTM grid of every 30 m layer

# Periods
CLIMATE_START, CLIMATE_END = "1991-01-01", "2020-12-31"  # baseline normals
RECORD_START = "1981-01-01"  # NASA POWER daily starts 1981
FIRE_START, FIRE_END = ((AREA.fire or {}).get("start"), (AREA.fire or {}).get("end"))

# Demo points / fields (lon, lat): North Evia placeholders, to be picked on the map
DEMO_FIELDS = {
    "istiaia_plain": {"label": "Field 1 · Istiaia plain", "lonlat": (23.15, 38.94)},
    "mantoudi_valley": {"label": "Field 2 · Mantoudi valley (below the burn scar)", "lonlat": (23.47, 38.80)},
    "limni_slope": {"label": "Field 3 · Limni hillside", "lonlat": (23.32, 38.77)},
} if AREA.is_default else {}

REPO = Path(__file__).resolve().parents[1]
DATA = AREA.data_root
RAW = DATA / "raw"
PROC = DATA / "processed"
REF = REPO / "data" / "reference"
OUT = DATA / "output"
