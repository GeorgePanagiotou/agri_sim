"""Download NASA POWER agroclimatology for the North Evia study area.

Example:
    python data_prep/download_power.py --start 1991-01-01 --end 2025-12-31
    python data_prep/download_power.py --frequency hourly --start 2021-10-01 --end 2021-10-31

POWER values describe a coarse NASA regional model grid, NOT field measurements.
"""
import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd
import requests

try:
    from .config import PROC, RAW, STUDY_AREA
except ImportError:
    from .config import PROC, RAW, STUDY_AREA

API = "https://power.larc.nasa.gov/api/temporal/{frequency}/point"
PARAMETERS = {
    "daily": [
        "T2M", "T2M_MAX", "T2M_MIN", "T2MDEW", "RH2M", "PRECTOTCORR",
        "WS2M", "ALLSKY_SFC_SW_DWN", "PS", "GWETTOP", "GWETROOT",
    ],
    "hourly": ["PRECTOTCORR", "T2M", "WS2M"],
}


def extract(frame_json: dict, frequency: str) -> pd.DataFrame:
    """Parse only NASA POWER values; retain missing values as NaN."""
    fill = frame_json["header"]["fill_value"]
    df = pd.DataFrame(frame_json["properties"]["parameter"]).astype("float64")
    df = df.replace(fill, float("nan"))
    df.index = pd.to_datetime(df.index, format="%Y%m%d" if frequency == "daily" else "%Y%m%d%H")
    df.index.name = "date" if frequency == "daily" else "time_utc"
    return df.astype("float32")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frequency", choices=PARAMETERS, default="daily")
    ap.add_argument("--start", default="1991-01-01", help="YYYY-MM-DD")
    ap.add_argument("--end", default="2025-12-31", help="YYYY-MM-DD")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    a, b = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if a > b:
        ap.error("--start must not be after --end")
    west, east, south, north = STUDY_AREA
    lon, lat = round((west + east) / 2, 5), round((south + north) / 2, 5)
    name = f"power_{args.frequency}_{a:%Y%m%d}_{b:%Y%m%d}"
    cache = RAW / "power" / f"{name}.json"
    out = PROC / f"{name}.parquet"
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.refresh or not cache.is_file():
        response = requests.get(
            API.format(frequency=args.frequency),
            params={
                "community": "AG", "format": "JSON", "time-standard": "UTC",
                "longitude": lon, "latitude": lat,
                "start": a.strftime("%Y%m%d"), "end": b.strftime("%Y%m%d"),
                "parameters": ",".join(PARAMETERS[args.frequency]),
            }, timeout=(20, 240),
        )
        response.raise_for_status()
        data = response.json()
        if "properties" not in data:
            raise RuntimeError(f"NASA POWER response did not contain data: {str(data)[:300]}")
        tmp = cache.with_suffix(".json.part")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(cache)
    data = json.loads(cache.read_text(encoding="utf-8"))
    df = extract(data, args.frequency)
    df.to_parquet(out)
    print(f"NASA POWER: {len(df)} rows -> {out}")
    print(f"Region cell at {lon} E, {lat} N; {df.index.min()} to {df.index.max()}")


if __name__ == "__main__":
    main()
