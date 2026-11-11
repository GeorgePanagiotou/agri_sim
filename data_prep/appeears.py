"""NASA AppEEARS area subsets for the study area: MODIS NDVI/ET/LST, SMAP soil moisture, ECOSTRESS ET/ESI.

AppEEARS (https://appeears.earthdatacloud.nasa.gov) cuts the products to our polygon on the server, so only a few MB
come down. Login uses your Earthdata entry in ~/.netrc (Windows: ~/_netrc), never printed or stored.

    ..\\.venv\\Scripts\\python.exe data_prep\\appeears.py submit      # once; task ids -> data/raw/appeears/tasks.json
    ..\\.venv\\Scripts\\python.exe data_prep\\appeears.py status
    ..\\.venv\\Scripts\\python.exe data_prep\\appeears.py download [task]   # files of finished tasks (skips existing)

Raw files go to data/raw/appeears/<task>/ (git-ignored). The appeears_*.py scripts turn them into data/processed/.
"""
import json
import netrc
import sys
import time
from pathlib import Path

import requests
import truststore

from config import RAW, STUDY_AREA

truststore.inject_into_ssl()
API = "https://appeears.earthdatacloud.nasa.gov/api"
DIR = RAW / "appeears"
TASKS_FILE = DIR / "tasks.json"


def polygon(pad=0.0):
    w, e, s, n = STUDY_AREA
    w, e, s, n = w - pad, e + pad, s - pad, n + pad
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {
        "type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}}]}


def layers(product, names):
    return [{"product": product, "layer": n} for n in names]


TASKS = {
    # one task per MODIS product: AppEEARS caps the number of output files per request
    "agrisim_mod13q1": {
        "dates": [{"startDate": "01-01-2000", "endDate": "12-31-2025"}],
        "layers": layers("MOD13Q1.061", ["_250m_16_days_NDVI", "_250m_16_days_EVI", "_250m_16_days_pixel_reliability"]),
        "geo": polygon(), "output": {"format": {"type": "netcdf4"}, "projection": "geographic"},
    },
    "agrisim_mod16a2gf": {
        "dates": [{"startDate": "01-01-2000", "endDate": "12-31-2025"}],
        "layers": layers("MOD16A2GF.061", ["ET_500m", "PET_500m", "ET_QC_500m"]),
        "geo": polygon(), "output": {"format": {"type": "netcdf4"}, "projection": "geographic"},
    },
    "agrisim_mod11a2": {
        "dates": [{"startDate": "01-01-2000", "endDate": "12-31-2025"}],
        "layers": layers("MOD11A2.061", ["LST_Day_1km", "LST_Night_1km", "QC_Day", "QC_Night"]),
        "geo": polygon(), "output": {"format": {"type": "netcdf4"}, "projection": "geographic"},
    },
    # SMAP: one task per product; submit() splits the dates further if AppEEARS says the request is too big.
    # Pad so every 9 km cell touching the study area comes back whole.
    "agrisim_spl3smp_e": {
        "dates": [{"startDate": "03-31-2015", "endDate": "12-31-2025"}],
        "layers": layers("SPL3SMP_E.006", ["Soil_Moisture_Retrieval_Data_AM_soil_moisture",
                                           "Soil_Moisture_Retrieval_Data_AM_retrieval_qual_flag",
                                           "Soil_Moisture_Retrieval_Data_PM_soil_moisture_pm",
                                           "Soil_Moisture_Retrieval_Data_PM_retrieval_qual_flag_pm"]),
        "geo": polygon(pad=0.05), "output": {"format": {"type": "netcdf4"}, "projection": "geographic"},
    },
    "agrisim_spl4smgp": {
        "dates": [{"startDate": "03-31-2015", "endDate": "12-31-2025"}],
        "layers": layers("SPL4SMGP.008", ["Geophysical_Data_sm_surface", "Geophysical_Data_sm_rootzone"]),
        "geo": polygon(pad=0.05), "output": {"format": {"type": "netcdf4"}, "projection": "geographic"},
    },
    # ECOSTRESS 70 m is big: the full 2018-2025 request was 5.5x over the AppEEARS size cap. Keep it to daily ET in the
    # dry season (May-Sep) of the post-fire summers; L3T JET is already cloud-masked (NaN).
    "agrisim_ecostress_et": {
        "dates": [{"startDate": "05-01", "endDate": "09-30", "recurring": True, "yearRange": [2022, 2025]}],
        "layers": layers("ECO_L3T_JET.002", ["ETdaily"]),
        "geo": polygon(), "output": {"format": {"type": "geotiff"}, "projection": "geographic"},
    },
}


def login():
    for name in ("_netrc", ".netrc"):
        p = Path.home() / name
        if p.exists():
            auth = netrc.netrc(p).authenticators("urs.earthdata.nasa.gov")
            if auth:
                r = requests.post(f"{API}/login", auth=(auth[0], auth[2]), timeout=60)
                r.raise_for_status()
                return {"Authorization": f"Bearer {r.json()['token']}"}
    raise SystemExit("No urs.earthdata.nasa.gov entry in ~/_netrc or ~/.netrc")


def load_tasks():
    return json.loads(TASKS_FILE.read_text()) if TASKS_FILE.exists() else {}


def split_dates(params):
    """Two copies of params, each with half of the (single) date range."""
    from datetime import date, datetime, timedelta
    d = params["dates"][0]
    a, b = (datetime.strptime(d[k], "%m-%d-%Y").date() for k in ("startDate", "endDate"))
    mid = a + (b - a) // 2
    f = lambda x: x.strftime("%m-%d-%Y")
    return [dict(params, dates=[{"startDate": f(a), "endDate": f(mid)}]),
            dict(params, dates=[{"startDate": f(mid + timedelta(days=1)), "endDate": f(b)}])]


def submit_one(h, ids, name, params):
    if name in ids or any(k.startswith(name + "_p") for k in ids):
        print(name, "already submitted, skipping")
        return
    r = requests.post(f"{API}/task", headers=h, timeout=120,
                      json={"task_type": "area", "task_name": name, "params": params})
    if r.status_code == 400 and "exceeds the maximum" in r.text:
        print(name, "too big, splitting dates:", r.json()["message"])
        for i, half in enumerate(split_dates(params), 1):
            submit_one(h, ids, f"{name}_p{i}", half)
        return
    if not r.ok:
        raise SystemExit(f"{name}: {r.status_code} {r.text[:1000]}")
    ids[name] = r.json()["task_id"]
    print(name, params["dates"][0], "submitted:", ids[name])
    TASKS_FILE.write_text(json.dumps(ids, indent=1))


def submit(h):
    DIR.mkdir(parents=True, exist_ok=True)
    ids = load_tasks()
    for name, params in TASKS.items():
        submit_one(h, ids, name, params)


def status(h):
    out = {}
    for name, tid in load_tasks().items():
        s = requests.get(f"{API}/task/{tid}", headers=h, timeout=60).json()
        out[name] = s.get("status")
        print(name, tid, s.get("status"), s.get("progress", {}).get("summary", ""))
    return out


def download(h, only=None):
    for name, tid in load_tasks().items():
        if only and not name.startswith(only):
            continue
        s = requests.get(f"{API}/task/{tid}", headers=h, timeout=60).json()
        if s.get("status") != "done":
            print(name, "not done:", s.get("status"))
            continue
        files = requests.get(f"{API}/bundle/{tid}", headers=h, timeout=60).json()["files"]
        d = DIR / name
        d.mkdir(parents=True, exist_ok=True)
        total = sum(f["file_size"] for f in files)
        print(f"{name}: {len(files)} files, {total / 1e6:.1f} MB")
        for f in files:
            dest = d / Path(f["file_name"]).name
            if dest.exists() and dest.stat().st_size == f["file_size"]:
                continue
            for attempt in range(5):
                try:
                    with requests.get(f"{API}/bundle/{tid}/{f['file_id']}", headers=h, timeout=300, stream=True) as r:
                        r.raise_for_status()
                        tmp = dest.with_suffix(dest.suffix + ".part")
                        with open(tmp, "wb") as fh:
                            for chunk in r.iter_content(1 << 20):
                                fh.write(chunk)
                        tmp.replace(dest)
                    break
                except requests.RequestException as e:
                    print("  retry", f["file_name"], e)
                    time.sleep(2 ** attempt + 1)
        print(f"{name}: downloaded to {d}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    headers = login()
    if cmd == "download":
        download(headers, sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        {"submit": submit, "status": status}[cmd](headers)
