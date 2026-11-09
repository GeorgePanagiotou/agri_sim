"""Shared settings for the data scripts: area, periods, demo fields, paths.

Values are a first draft (2026-11-09); refine the AOI once we have the 2021 burn perimeter.
"""
from pathlib import Path

# Analysis area: North Evia (lon_min, lon_max, lat_min, lat_max), WGS84
AOI = (22.80, 23.70, 38.60, 39.05)

# Periods
CLIMATE_START, CLIMATE_END = "1991-01-01", "2020-12-31"  # baseline normals
RECORD_START = "1981-01-01"  # NASA POWER daily starts 1981
FIRE_START, FIRE_END = "2021-08-03", "2021-08-14"

# Demo points / fields (lon, lat): placeholders, to be picked on the map
DEMO_FIELDS = {
    "istiaia_plain": {"label": "Field 1 · Istiaia plain", "lonlat": (23.15, 38.94)},
    "mantoudi_valley": {"label": "Field 2 · Mantoudi valley (below the burn scar)", "lonlat": (23.47, 38.80)},
    "limni_slope": {"label": "Field 3 · Limni hillside", "lonlat": (23.32, 38.77)},
}

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
RAW = DATA / "raw"
PROC = DATA / "processed"
REF = DATA / "reference"
OUT = DATA / "output"
