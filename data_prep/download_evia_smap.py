"""Extract two seasons of native SPL4SMGP v008 point data via NASA CMR and OPeNDAP.

An Earthdata user token is read from EARTHDATA_TOKEN or a hidden prompt. Only
the two requested science variables and the native cell coordinates are read.
Monthly checkpoints allow a stopped run to resume without re-fetching points.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import getpass
import os
import re
import struct
import threading
import time
from urllib.parse import unquote

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

from config import PROC, RAW, SOWING_LAT, SOWING_LON, SOWING_SEASONS

CACHE = RAW / "evia_sowing" / "smap"
OUT = PROC / "evia_sowing" / "smap"
CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
OPENDAP = "https://opendap.earthdata.nasa.gov/collections/"
VARIABLES = ("cell_lat", "cell_lon", "/Geophysical_Data/sm_surface", "/Geophysical_Data/soil_temp_layer1")
# EASE-Grid 2.0 Global M09, upper-left outer edge and equal-area cell spacing, metres.
WEST, NORTH, SPACING = -17367530.4451615, 7314540.8306386, 9008.055210146
x, y = Transformer.from_crs(4326, 6933, always_xy=True).transform(SOWING_LON, SOWING_LAT)
ROW, COL = int((NORTH-y)//SPACING), int((x-WEST)//SPACING)
CELL_LON, CELL_LAT = Transformer.from_crs(6933, 4326, always_xy=True).transform(
    WEST+(COL+0.5)*SPACING, NORTH-(ROW+0.5)*SPACING)
LOCAL = threading.local()


def atomic_csv(frame, target):
    tmp = target.with_suffix(".partial.csv")
    frame.to_csv(tmp, index=False)
    tmp.replace(target)


def catalog(start, end, refresh):
    file = CACHE / f"catalog_{start}_{end}.csv"
    if file.exists() and not refresh:
        return pd.read_csv(file)
    params = {"short_name": "SPL4SMGP", "version": "008", "page_size": 2000,
              "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z"}
    rows = []
    with requests.Session() as session:
        page = 1
        while True:
            response = session.get(CMR, params={**params, "page_num": page}, timeout=(15, 90))
            response.raise_for_status()
            entries = response.json()["feed"]["entry"]
            for item in entries:
                match = re.search(r"SMAP_L4_SM_gph_(\d{8}T\d{6})_Vv\d+_\d+\.h5", item["title"])
                if not match:
                    raise ValueError("Unexpected SPL4SMGP granule naming")
                date = pd.to_datetime(match[1], format="%Y%m%dT%H%M%S", utc=True).strftime("%Y-%m-%dT%H:%M:%SZ")
                if not start <= date[:10] <= end:
                    continue
                url = next(link["href"] for link in item["links"] if link.get("href","").startswith(OPENDAP))
                rows.append({"time_utc": date, "granule": match[0], "concept_id": item["id"],
                             "updated": item["updated"], "opendap": url})
            if len(entries) < params["page_size"]:
                break
            page += 1
    frame = pd.DataFrame(rows).sort_values(["time_utc","updated","concept_id"]).drop_duplicates("time_utc",keep="last")
    if frame.empty:
        raise RuntimeError(f"No SMAP granules for {start} to {end}")
    atomic_csv(frame, file)
    return frame


def decode_point(data):
    header, marker, binary = data.partition(b"Data:\n")
    if not marker:
        raise ValueError("Expected a DAP2 binary response")
    keys = [unquote(name.decode()) for name in re.findall(rb"\bFloat32\s+([^\s\[]+)\[", header)]
    if set(keys) != set(VARIABLES) or len(binary) != 12 * len(VARIABLES):
        raise ValueError("Unexpected point-subset schema")
    values = {}
    for key, (count, repeated_count, val) in zip(keys, struct.iter_unpack(">IIf", binary)):
        if count != 1 or repeated_count != 1:
            raise ValueError("Expected exactly one native pixel per variable")
        values[key] = val
    if abs(values["cell_lat"]-CELL_LAT) > 0.001 or abs(values["cell_lon"]-CELL_LON) > 0.001:
        raise ValueError("NASA cell coordinates do not match the containing EASE-Grid pixel")
    return values


def fetch(item, token):
    if not hasattr(LOCAL, "session"):
        LOCAL.session = requests.Session()
    url = item.opendap
    if not url.startswith(OPENDAP):
        raise ValueError("Invalid NASA OPeNDAP origin")
    query = ",".join(f"{var}[{ROW}][{COL}]" for var in VARIABLES)
    for attempt in range(5):
        try:
            response = LOCAL.session.get(url+".dods?"+query, headers={"Authorization":"Bearer "+token},
                                         timeout=(15, 80))
            if response.status_code in (401, 403) or "text/html" in response.headers.get("Content-Type",""):
                raise PermissionError("NASA did not authorize this point request. Check the Earthdata token.")
            if response.status_code in (429, 500, 502, 503, 504):
                delay = response.headers.get("Retry-After","")
                time.sleep(min(60, float(delay)) if delay.isdigit() else 2**attempt)
                continue
            response.raise_for_status()
            values = decode_point(response.content)
            moisture = values[VARIABLES[2]]
            temperature = values[VARIABLES[3]]
            return {"time_utc": item.time_utc, "granule": item.granule, "concept_id": item.concept_id,
                    "cell_lat": values["cell_lat"], "cell_lon": values["cell_lon"],
                    "sm_surface_m3m3": moisture if 0 <= moisture <= 0.9 else np.nan,
                    "soil_temp_layer1_K": temperature if 210 <= temperature <= 340 else np.nan}
        except (requests.ConnectionError, requests.Timeout, ValueError) as err:
            if attempt == 4:
                raise RuntimeError(f"{item.granule}: {type(err).__name__} while reading the point") from None
            time.sleep(2**attempt)
    raise RuntimeError(f"NASA temporarily unavailable for {item.granule}")


def save_months(records, months):
    for month in months:
        frame = pd.DataFrame([row for key,row in records.items() if key.startswith(month)])
        if not frame.empty:
            atomic_csv(frame.sort_values("time_utc"), CACHE / f"points_{month}.csv")


def publish(manifest, records):
    # Explicitly represent any catalog gaps, retaining valid sample counts for each variable.
    days = [d for start,end in SOWING_SEASONS for d in pd.date_range(start,end)]
    stamps = [(day+pd.Timedelta(hours=hour, minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
              for day in days for hour in range(1,24,3)]
    if not set(manifest.time_utc) <= set(stamps):
        raise ValueError("Unexpected granule centre time")
    measured = pd.DataFrame([records[date] for date in manifest.time_utc])
    series = pd.DataFrame({"time_utc":stamps}).merge(measured, on="time_utc", how="left", validate="one_to_one")
    series["soil_temp_layer1_C"] = series.soil_temp_layer1_K - 273.15
    series["row"], series["col"] = ROW, COL
    series["date_utc"] = series.time_utc.str[:10]
    daily = series.groupby("date_utc").agg(
        sm_surface_m3m3=("sm_surface_m3m3","mean"), sm_samples=("sm_surface_m3m3","count"),
        soil_temp_layer1_C=("soil_temp_layer1_C","mean"), temp_samples=("soil_temp_layer1_C","count"),
        granules=("granule","count")).reset_index()
    daily["complete_day"] = (daily.sm_samples == 8) & (daily.temp_samples == 8)
    atomic_csv(series, OUT / "smap_3hourly.csv")
    atomic_csv(daily, OUT / "smap_daily.csv")
    atomic_csv(manifest, OUT / "granules.csv")
    print(f"{len(measured)}/{len(stamps)} slots cataloged, {sum(daily.complete_day)}/{len(daily)} days with all 8 valid pairs.",flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers",type=int,choices=range(1,13),default=8)
    parser.add_argument("--refresh-catalog",action="store_true")
    args = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = pd.concat([catalog(a,b,args.refresh_catalog) for a,b in SOWING_SEASONS]).sort_values("time_utc")
    sources = manifest.set_index("time_utc").concept_id.to_dict()
    records = {}
    for file in CACHE.glob("points_*.csv"):
        for row in pd.read_csv(file).to_dict("records"):
            if sources.get(row["time_utc"]) == row["concept_id"]:
                records[row["time_utc"]] = row
    missing = [row for row in manifest.itertuples(index=False) if row.time_utc not in records]
    print(f"Native grid row {ROW}, col {COL}; {len(manifest)} granules; {len(missing)} points to extract.",flush=True)
    if missing:
        token = os.getenv("EARTHDATA_TOKEN") or getpass.getpass("Earthdata bearer token (hidden): ").strip()
        if not token:
            raise SystemExit("An Earthdata user token is required.")
        # Verify authentication, DAP schema and native cell before launching workers.
        first = fetch(missing[0], token)
        records[first["time_utc"]] = first
        save_months(records, {first["time_utc"][:7]})
        print(f"First point verified at {first['cell_lat']:.6f} N, {first['cell_lon']:.6f} E.",flush=True)
        dirty = set()
        failures = []
        with ThreadPoolExecutor(args.workers) as pool:
            futures = {pool.submit(fetch, row, token): row for row in missing[1:]}
            for i, future in enumerate(as_completed(futures),1):
                row = futures[future]
                try:
                    point = future.result()
                    records[row.time_utc] = point
                    dirty.add(row.time_utc[:7])
                except Exception as err:
                    failures.append((row.granule,type(err).__name__))
                if i % 48 == 0 or i == len(futures):
                    save_months(records, dirty)
                    dirty.clear()
                    print(f"{len(records)}/{len(manifest)} points cached; {len(failures)} failures",flush=True)
        if failures:
            raise SystemExit(f"{len(failures)} points need retry. First: {failures[0]}. Re-run to resume.")
    publish(manifest, records)


if __name__ == "__main__":
    main()
