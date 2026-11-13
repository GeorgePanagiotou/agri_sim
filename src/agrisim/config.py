"""Shared geographic area, study dates and output paths for Agrisimfinal.

All coordinates are WGS84. The sowing pilot centre is PROVISIONAL: it is not
an independently verified field boundary. Edit dates/area here before a run.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
RAW = DATA / "raw"
PROC = DATA / "processed"
REF = DATA / "reference"
OUT = DATA / "output"

# (longitude west, longitude east, latitude south, latitude north)
AOI = (22.80, 23.70, 38.60, 39.05)
STUDY_AREA = (23.32, 23.50, 38.75, 38.95)

# A candidate location and historical windows; not a surveyed parcel.
SOWING_LON, SOWING_LAT = 23.43232, 38.75920
SOWING_SEASONS = (("2023-09-01", "2024-01-31"), ("2024-09-01", "2025-01-31"))

CLIMATE_START, CLIMATE_END = "1991-01-01", "2020-12-31"
RECORD_START = "1981-01-01"
FIRE_START, FIRE_END = "2021-08-03", "2021-08-14"
