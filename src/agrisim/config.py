"""Shared geographic area, study dates and output paths for AgriSim.

All coordinates are WGS84. The area comes from configs/areas/<name>.yaml, selected with the environment variable
AGRISIM_AREA (default "evia", which keeps the original data/ and outputs/ paths). The sowing pilot centre is
PROVISIONAL: it is not an independently verified field boundary.
"""
from pathlib import Path

from agrisim.area import load as _load_area

AREA = _load_area()
AREA_NAME = AREA.name

REPO = Path(__file__).resolve().parents[2]
DATA = AREA.data_root
RAW = DATA / "raw"
PROC = DATA / "processed"
REF = REPO / "data" / "reference"          # hand-made reference tables are shared by every area
OUT = DATA / "output"
OUTPUTS = AREA.outputs                     # engine outputs (risk, sowing, ...)
CRS = AREA.crs                             # UTM grid of the 30 m layers

# (longitude west, longitude east, latitude south, latitude north)
AOI = AREA.aoi
STUDY_AREA = AREA.study_area

# A candidate location and historical windows; not a surveyed parcel.
SOWING_LON, SOWING_LAT = AREA.pilot
SOWING_SEASONS = tuple((f"{y}-09-01", f"{y+1}-06-30") for y in range(2020, 2026))

CLIMATE_START, CLIMATE_END = "1991-01-01", "2020-12-31"
RECORD_START = "1981-01-01"
FIRE_START, FIRE_END = ((AREA.fire or {}).get("start"), (AREA.fire or {}).get("end"))
