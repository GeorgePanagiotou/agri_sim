"""Download NASA POWER point data for the study area (no login needed).

- daily 1981-01-01 .. last month: temperature, dew point, humidity, rain, wind, radiation, pressure, soil wetness
- hourly October 2021: rain, temperature, wind (storm "Athena", 10-11 Oct 2021)

POWER's meteorology grid is 0.5 x 0.625 deg (MERRA-2), so the whole study area is one cell: these are area values,
not field values.

    ..\\.venv\\Scripts\\python.exe data_prep\\download_power.py
"""
import json

import pandas as pd
import requests

from config import PROC, RAW, STUDY_AREA

LON = round((STUDY_AREA[0] + STUDY_AREA[1]) / 2, 3)
LAT = round((STUDY_AREA[2] + STUDY_AREA[3]) / 2, 3)
API = "https://power.larc.nasa.gov/api/temporal/{res}/point"
DAILY = ["T2M", "T2M_MAX", "T2M_MIN", "T2MDEW", "RH2M", "PRECTOTCORR", "WS2M", "ALLSKY_SFC_SW_DWN", "PS",
         "GWETTOP", "GWETROOT"]
HOURLY = ["PRECTOTCORR", "T2M", "WS2M"]
JOBS = [  # (name, resolution, parameters, start, end)
    ("power_daily_1981_2026", "daily", DAILY, "19810101", "20261031"),
    ("power_hourly_2021-10", "hourly", HOURLY, "20211001", "20211031"),
]

(RAW / "power").mkdir(parents=True, exist_ok=True)
PROC.mkdir(parents=True, exist_ok=True)
for name, res, params, start, end in JOBS:
    raw = RAW / "power" / f"{name}.json"
    if raw.exists():
        print("exists, skipping download", raw.name)
    else:
        r = requests.get(API.format(res=res), timeout=300, params={
            "parameters": ",".join(params), "community": "AG", "longitude": LON, "latitude": LAT,
            "start": start, "end": end, "format": "JSON", "time-standard": "UTC"})
        r.raise_for_status()
        raw.write_text(r.text, encoding="utf-8")
        print("downloaded", raw.name)
    d = json.loads(raw.read_text(encoding="utf-8"))
    fill = d["header"]["fill_value"]
    df = pd.DataFrame(d["properties"]["parameter"]).astype("float64").replace(fill, float("nan"))
    fmt = "%Y%m%d" if res == "daily" else "%Y%m%d%H"
    df.index = pd.to_datetime(df.index, format=fmt)
    df.index.name = "date" if res == "daily" else "time_utc"
    df = df.astype("float32")
    out = PROC / f"{name}.parquet"
    df.to_parquet(out)
    grid = d["geometry"]["coordinates"]
    print(f"{out.name}: {len(df)} rows, {df.index.min()} .. {df.index.max()}, cell centre {grid[:2]}")
