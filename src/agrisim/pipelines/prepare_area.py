"""Prepare everything the engines and the ML training table need, for any study area.

    python -m agrisim.pipelines.prepare_area --name messara --bbox 24.70 24.95 34.98 35.10 --label "Messara plain"
    python -m agrisim.pipelines.prepare_area --name messara --plan          # what is done / still to run
    python -m agrisim.pipelines.prepare_area --name evia --steps risk,sowing,training_table

--bbox is lon_min lon_max lat_min lat_max (WGS84, at most 1 x 1 degree). It writes configs/areas/<name>.yaml; data go
to data/areas/<name>/ (Evia keeps data/). Every step runs as its own process with AGRISIM_AREA=<name>, is skipped
when its output exists (use --force STEP to redo) and is logged to <data_root>/prepare_area_log.json.

Steps, in order (all public NASA/USGS data + SoilGrids; Earthdata login from ~/_netrc for NASADEM and IMERG):
    harmonization   Landsat 5/7/9 -> 8 NDVI offsets: copied from Evia (sensor-level) unless the area has its own
    landsat         Landsat C2 L2 monthly NDVI cube, 30 m (Planetary Computer windows)        slowest: ~1-3 h
    field_map       land use + crop/fallow history per pixel and agricultural year
    soil            SoilGrids 2.0 on the 30 m grid (texture, SOC, AWC, RUSLE K)
    terrain         NASADEM elevation, slope, flow accumulation, LS factor
    imerg           GPM IMERG Final daily per 0.1 deg cell (GES DISC OPeNDAP)
    imerg_late      GPM IMERG Late Run after Final ends .. yesterday (same cells; product kept separate)
    imerg_late_cal  monthly Late -> Final factors from 2019 .. Final end (readers scale Late days with them)
    power           NASA POWER daily at the area centre (1991 .. two days ago)
    risk            Environmental Risk Engine v1
    sowing          sowing-window engine v1
    training_table  ML training table (rainfed field pixel x season)
    ml_models       14 Nov / 1 Mar tables, live table, XGBoost vigour + crop models trained on this area
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from agrisim.area import REPO, create, load

PY = sys.executable
STEP_ORDER = ["harmonization", "landsat", "field_map", "soil", "terrain", "imerg", "imerg_late", "imerg_late_cal",
              "power", "risk", "sowing", "training_table", "ml_models"]


def last_month_end(today: date | None = None) -> date:
    today = today or date.today()
    return today.replace(day=1) - timedelta(days=1)


def steps(area, first_year: int, last_year: int, imerg_last: int) -> dict:
    proc = area.data_root / "processed"
    power_end = date.today() - timedelta(days=2)   # POWER daily has a latency of ~1-3 days
    dp = REPO / "data_prep"
    return {
        "harmonization": {"done": proc / "landsat_ndvi_harmonization.json", "cmd": None},
        "landsat": {"done": proc / "landsat_ndvi_monthly_30m.nc",
                    "cmd": [PY, str(dp / "landsat_ndvi_history.py"), str(first_year), str(last_year)]},
        "field_map": {"done": proc / "landsat_field_years.nc", "cmd": [PY, str(dp / "landsat_field_map.py")]},
        "soil": {"done": proc / "soil_30m.tif", "cmd": [PY, str(dp / "soil_soilgrids.py")]},
        "terrain": {"done": proc / "terrain_30m.tif", "cmd": [PY, str(dp / "terrain_nasadem.py")]},
        "imerg": {"done": proc / "imerg_daily_2001_2025.parquet",
                  "cmd": [PY, str(dp / "download_imerg_daily.py"), "2001", str(imerg_last)]},
        "imerg_late": {"done": area.data_root / "raw" / "imerg_late",   # re-run with --force imerg_late to update
                       "cmd": [PY, str(dp / "download_imerg_late.py")]},
        "imerg_late_cal": {"done": proc / "imerg_late_to_final.csv",
                           "cmd": [PY, str(dp / "imerg_late_calibration.py")]},
        "power": {"done": proc / f"power_daily_19910101_{power_end:%Y%m%d}.parquet",
                  "cmd": [PY, "-m", "agrisim.data_sources.power", "--start", "1991-01-01",
                          "--end", power_end.isoformat()]},
        "risk": {"done": area.outputs / "risk_daily.csv",
                 "cmd": [PY, "-m", "agrisim.decision_engine.environmental_risk", "--start", "2001-01-01"]},
        "sowing": {"done": area.outputs / "sowing_reliability.csv",
                   "cmd": [PY, "-m", "agrisim.decision_engine.sowing_window"]},
        "training_table": {"done": proc / "ml" / "training_table_v1.parquet",
                           "cmd": [PY, "-m", "agrisim.pipelines.build_training_table"]},
        "ml_models": {"done": proc / "ml" / "models" / "1114" / "run_manifest.json",
                      "cmd": [PY, "-m", "agrisim.pipelines.ml_for_area"]},
    }


def copy_harmonization(area) -> str:
    target = area.data_root / "processed" / "landsat_ndvi_harmonization.json"
    source = REPO / "data" / "processed" / "landsat_ndvi_harmonization.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return "no Evia harmonization file; Landsat cube will use no offsets"
    data = json.loads(source.read_text(encoding="utf-8"))
    data["copied_from"] = "evia (sensor-level Landsat 5/7/9 -> 8 offsets; re-run landsat_harmonize.py to refit)"
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return "copied from Evia"


def _alive(pid: int) -> bool:
    if os.name == "nt":   # os.kill(pid, 0) would terminate the process on Windows
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def running(area) -> dict | None:
    """The live run holding this area's lock ({pid, started, steps}), or None (stale locks are ignored)."""
    path = area.data_root / "prepare_area.lock"
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if _alive(int(info.get("pid", -1))) else None


def run(name: str, selected: list[str], force: set[str], first_year: int, last_year: int, imerg_last: int,
        plan: bool) -> list[dict]:
    area = load(name)
    if not plan:   # one run per area at a time (CLI and the Streamlit Area explorer both start runs)
        other = running(area)
        if other and other["pid"] != os.getpid():
            raise SystemExit(f"Area {name}: a run is already in progress (pid {other['pid']}, since "
                             f"{other['started']}). Wait for it, or stop that process.")
        lock = area.data_root / "prepare_area.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"pid": os.getpid(), "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "steps": selected}), encoding="utf-8")
        try:
            return _run(area, selected, force, first_year, last_year, imerg_last, plan)
        finally:
            lock.unlink(missing_ok=True)
    return _run(area, selected, force, first_year, last_year, imerg_last, plan)


def _run(area, selected: list[str], force: set[str], first_year: int, last_year: int, imerg_last: int,
         plan: bool) -> list[dict]:
    plan_steps = steps(area, first_year, last_year, imerg_last)
    env = {**os.environ, "AGRISIM_AREA": area.name, "PYTHONIOENCODING": "utf-8"}
    log_path = area.data_root / "prepare_area_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    report = []
    print(f"Area {area.name}: {area.label} | box {area.study_area} | {area.crs} | data {area.data_root}")
    for step in selected:
        spec = plan_steps[step]
        done = spec["done"].exists()
        if plan:
            print(f"  {'done' if done else 'TODO':4}  {step:15} -> {spec['done'].relative_to(REPO)}")
            report.append({"step": step, "done": done})
            continue
        if done and step not in force:
            print(f"  skip  {step} (exists)")
            report.append({"step": step, "status": "skipped_exists"})
            continue
        print(f"  run   {step} ...", flush=True)
        start = time.time()
        if spec["cmd"] is None:
            note = copy_harmonization(area)
            status, code = note, 0
        else:
            step_log = area.data_root / "logs" / f"{step}.log"
            step_log.parent.mkdir(parents=True, exist_ok=True)
            with open(step_log, "w", encoding="utf-8") as fh:   # follow progress: Get-Content -Wait <log>
                code = subprocess.run(spec["cmd"], cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
            tail = step_log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]
            status = "ok" if code == 0 and spec["done"].exists() else "failed"
            print("        " + "\n        ".join(tail) + f"\n        (log: {step_log.relative_to(REPO)})")
        entry = {"step": step, "status": status, "returncode": code, "seconds": round(time.time() - start),
                 "finished": time.strftime("%Y-%m-%d %H:%M:%S")}
        report.append(entry)
        log.append({"area": area.name, **entry})
        area.data_root.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
        if status == "failed":
            print(f"  STOP: {step} failed (see output above); fix and re-run, finished steps are skipped")
            break
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="area name (lowercase), e.g. messara")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"),
                   help="create the area config (WGS84)")
    p.add_argument("--label", default=None)
    p.add_argument("--pilot", type=float, nargs=2, metavar=("LON", "LAT"), default=None)
    p.add_argument("--steps", default="all", help=f"comma list from: {','.join(STEP_ORDER)}")
    p.add_argument("--force", default="", help="comma list of steps to redo even if their output exists")
    p.add_argument("--first-year", type=int, default=1997, help="Landsat cube first year (history for 2002+)")
    p.add_argument("--last-year", type=int, default=2025)
    p.add_argument("--imerg-last-year", type=int, default=2025)
    p.add_argument("--plan", action="store_true")
    a = p.parse_args(argv)
    if a.bbox:
        path = create(a.name, tuple(a.bbox), label=a.label, pilot=tuple(a.pilot) if a.pilot else None)
        print("created", path.relative_to(REPO))
    selected = STEP_ORDER if a.steps == "all" else [s.strip() for s in a.steps.split(",") if s.strip()]
    unknown = set(selected) - set(STEP_ORDER)
    if unknown:
        p.error(f"unknown steps: {sorted(unknown)}")
    selected = [s for s in STEP_ORDER if s in selected]
    report = run(a.name, selected, {s.strip() for s in a.force.split(",") if s.strip()}, a.first_year,
                 a.last_year, a.imerg_last_year, a.plan)
    if any(r.get("status") == "failed" for r in report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
