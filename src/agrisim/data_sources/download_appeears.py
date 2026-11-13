"""Download approved NASA MODIS, SMAP and ECOSTRESS subsets through NASA AppEEARS.

Runs only products explicitly named in the 2026 Space Apps Field Shift resources.
The original NASA product/version and selected science/QA bands are saved with
requests and NASA task IDs. Source endpoint: appeears.earthdatacloud.nasa.gov.

    python data_prep/download_appeears.py products
    python data_prep/download_appeears.py submit --products modis_ndvi modis_lst --start 2023-01-01 --end 2024-12-31
    python data_prep/download_appeears.py status
    python data_prep/download_appeears.py download

AppEEARS API requires a valid NASA Earthdata .netrc entry. Be mindful that
ECOSTRESS imagery can produce large requests even for a small study area.
"""
import argparse
import json
import netrc
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
try:
    import truststore
    truststore.inject_into_ssl()  # Trust Windows system certificates, matching original user script.
except ImportError:
    pass

try:
    from .config import RAW, STUDY_AREA
except ImportError:
    from .config import RAW, STUDY_AREA

API = "https://appeears.earthdatacloud.nasa.gov/api"
TASK_ROOT = RAW / "appeears"
REGISTRY = {
    "modis_ndvi": {
        "product": "MOD13Q1.061",
        "layers": ["_250m_16_days_NDVI", "_250m_16_days_EVI", "_250m_16_days_pixel_reliability"],
        "format": "netcdf4", "pad": 0.0,
    },
    "modis_et": {
        "product": "MOD16A2GF.061",
        "layers": ["ET_500m", "PET_500m", "ET_QC_500m"],
        "format": "netcdf4", "pad": 0.0,
    },
    "modis_lst": {
        "product": "MOD11A2.061",
        "layers": ["LST_Day_1km", "LST_Night_1km", "QC_Day", "QC_Night"],
        "format": "netcdf4", "pad": 0.0,
    },
    "smap_surface": {
        "product": "SPL3SMP_E.006",
        "layers": [
            "Soil_Moisture_Retrieval_Data_AM_soil_moisture",
            "Soil_Moisture_Retrieval_Data_AM_retrieval_qual_flag",
            "Soil_Moisture_Retrieval_Data_PM_soil_moisture_pm",
            "Soil_Moisture_Retrieval_Data_PM_retrieval_qual_flag_pm",
        ], "format": "netcdf4", "pad": 0.05,
    },
    "smap_l4": {
        "product": "SPL4SMGP.008",
        "layers": ["Geophysical_Data_sm_surface", "Geophysical_Data_sm_rootzone"],
        "format": "netcdf4", "pad": 0.05,
    },
    "ecostress_et": {
        "product": "ECO_L3T_JET.002",
        "layers": ["ETdaily"], "format": "geotiff", "pad": 0.0,
    },
}


def polygon(pad=0.0):
    w, e, s, n = STUDY_AREA
    w, e, s, n = w - pad, e + pad, s - pad, n + pad
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": {
            "type": "Polygon", "coordinates": [[
                [w, s], [e, s], [e, n], [w, n], [w, s],
            ]],
        }}],
    }


def params_for(key, start, end):
    """A NASA AppEEARS area request using fixed, challenge-listed data products."""
    if key not in REGISTRY:
        raise ValueError(f"Unapproved NASA AppEEARS product key: {key}")
    p = REGISTRY[key]
    return {
        "dates": [{"startDate": date.fromisoformat(start).strftime("%m-%d-%Y"),
                   "endDate": date.fromisoformat(end).strftime("%m-%d-%Y")}],
        "layers": [{"product": p["product"], "layer": layer} for layer in p["layers"]],
        "geo": polygon(p["pad"]),
        "output": {"format": {"type": p["format"]}, "projection": "geographic"},
    }


def nasa_headers():
    for filename in ("_netrc", ".netrc"):
        p = Path.home() / filename
        if not p.is_file():
            continue
        auth = netrc.netrc(p).authenticators("urs.earthdata.nasa.gov")
        if auth:
            r = requests.post(f"{API}/login", auth=(auth[0], auth[2]), timeout=60)
            r.raise_for_status()
            return {"Authorization": f"Bearer {r.json()['token']}"}
    raise RuntimeError("Set up a NASA Earthdata `urs.earthdata.nasa.gov` entry in ~/.netrc (Windows: ~/_netrc)")


def task_file():
    return TASK_ROOT / "tasks.json"


def load_tasks():
    path = task_file()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_tasks(tasks):
    TASK_ROOT.mkdir(parents=True, exist_ok=True)
    path = task_file()
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    tmp.replace(path)


def split_params(params):
    days = params["dates"][0]
    a = datetime.strptime(days["startDate"], "%m-%d-%Y").date()
    b = datetime.strptime(days["endDate"], "%m-%d-%Y").date()
    if a >= b:
        raise RuntimeError("AppEEARS rejected even a single-day request as oversized; reduce the study area")
    mid = a + (b - a) // 2
    result = []
    for lo, hi in ((a, mid), (mid + timedelta(days=1), b)):
        modified = dict(params)
        modified["dates"] = [{"startDate": lo.strftime("%m-%d-%Y"), "endDate": hi.strftime("%m-%d-%Y")}]
        result.append(modified)
    return result


def submit_one(session, headers, tasks, name, key, params):
    if name in tasks:
        print(f"{name} already submitted, skipping")
        return
    resp = session.post(f"{API}/task", headers=headers, json={
        "task_type": "area", "task_name": name, "params": params,
    }, timeout=120)
    if resp.status_code == 400 and "exceeds the maximum" in resp.text.lower():
        print(f"{name}: too large for AppEEARS; dividing date range")
        for i, partial in enumerate(split_params(params), 1):
            submit_one(session, headers, tasks, f"{name}_p{i}", key, partial)
        return
    resp.raise_for_status()
    tid = resp.json()["task_id"]
    tasks[name] = {"task_id": tid, "key": key, "params": params}
    save_tasks(tasks)
    print(f"NASA AppEEARS: submitted {name}, task ID {tid}")


def status(session, headers, tasks):
    for name, task in tasks.items():
        resp = session.get(f"{API}/task/{task['task_id']}", headers=headers, timeout=60)
        resp.raise_for_status()
        value = resp.json()
        print(f"{name}: {value.get('status')}, {value.get('progress', {}).get('summary', '')}")


def download(session, headers, tasks, selector=None):
    for name, task in tasks.items():
        if selector and not name.startswith(selector):
            continue
        tid = task["task_id"]
        resp = session.get(f"{API}/task/{tid}", headers=headers, timeout=60)
        resp.raise_for_status()
        if resp.json().get("status") != "done":
            print(f"{name} not yet ready")
            continue
        resp = session.get(f"{API}/bundle/{tid}", headers=headers, timeout=90)
        resp.raise_for_status()
        files = resp.json()["files"]
        dest = TASK_ROOT / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "nasa_request.json").write_text(json.dumps(task, indent=2), encoding="utf-8")
        for item in files:
            filename = Path(item["file_name"]).name
            out = dest / filename
            if out.exists() and out.stat().st_size == item["file_size"]:
                continue
            for attempt in range(5):
                try:
                    with session.get(f"{API}/bundle/{tid}/{item['file_id']}", headers=headers, timeout=(30, 300), stream=True) as r:
                        r.raise_for_status()
                        tmp = out.with_suffix(out.suffix + ".part")
                        with tmp.open("wb") as stream:
                            for chunk in r.iter_content(chunk_size=1 << 20):
                                if chunk:
                                    stream.write(chunk)
                        if tmp.stat().st_size != item["file_size"]:
                            raise IOError(f"Incomplete NASA download for {filename}")
                        tmp.replace(out)
                    break
                except (requests.RequestException, IOError):
                    if attempt == 4:
                        raise
                    time.sleep(2 ** attempt + 1)
        print(f"{name}: {len(files)} files -> {dest}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("products", help="List fixed, approved NASA products (no login required)")
    sp = sub.add_parser("submit", help="Queue NASA AppEEARS area subsets")
    sp.add_argument("--products", nargs="+", choices=sorted(REGISTRY), required=True)
    sp.add_argument("--start", default="2023-09-01")
    sp.add_argument("--end", default="2025-01-31")
    sub.add_parser("status")
    dl = sub.add_parser("download")
    dl.add_argument("--task", default=None, help="Optional task-name prefix")
    args = ap.parse_args(argv)
    if args.command == "products":
        for key, p in REGISTRY.items():
            print(f"{key:16} {p['product']:20} {', '.join(p['layers'])}")
        return
    headers = nasa_headers()
    with requests.Session() as session:
        if args.command == "submit":
            a, b = date.fromisoformat(args.start), date.fromisoformat(args.end)
            if a > b:
                ap.error("--start must not follow --end")
            tasks = load_tasks()
            for key in args.products:
                name = f"agrisim_{key}_{a:%Y%m%d}_{b:%Y%m%d}"
                submit_one(session, headers, tasks, name, key, params_for(key, args.start, args.end))
        elif args.command == "status":
            status(session, headers, load_tasks())
        else:
            download(session, headers, load_tasks(), args.task)


if __name__ == "__main__":
    main()
