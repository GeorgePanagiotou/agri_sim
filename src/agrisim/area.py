"""Study-area selection: which area the data scripts and engines work on.

The area is chosen with the environment variable AGRISIM_AREA (default "evia") and described by
configs/areas/<name>.yaml. North Evia keeps the original paths (data/, outputs/) and grid, so nothing changes for
the demo. Any other area gets its own folders under data/areas/<name>/ and its own UTM grid.

    AGRISIM_AREA=messara python data_prep/landsat_ndvi_history.py
    python -m agrisim.pipelines.prepare_area --name messara --bbox 24.70 24.95 34.98 35.10
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
AREAS_DIR = REPO / "configs" / "areas"
ENV = "AGRISIM_AREA"
DEFAULT = "evia"


def utm_epsg(lon: float, lat: float) -> int:
    """WGS84 / UTM zone EPSG code of a point (326xx north, 327xx south)."""
    if not (-180 <= lon <= 180 and -80 <= lat <= 84):
        raise ValueError("Point outside the UTM range")
    zone = min(int((lon + 180) // 6) + 1, 60)
    return (32600 if lat >= 0 else 32700) + zone


@dataclass(frozen=True)
class Area:
    name: str
    label: str
    study_area: tuple[float, float, float, float]   # lon_min, lon_max, lat_min, lat_max (W, E, S, N)
    pilot: tuple[float, float]                     # lon, lat
    crs: str
    data_root: Path
    outputs: Path
    fire: dict | None = None                       # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} or None
    aoi: tuple[float, float, float, float] | None = None
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def bbox_wsen(self) -> tuple[float, float, float, float]:
        w, e, s, n = self.study_area
        return w, s, e, n

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT


def _validate_name(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name):
        raise ValueError("Area name: lowercase letters, digits and _ (start with a letter)")
    return name


def _validate_box(w: float, e: float, s: float, n: float) -> None:
    if not (-180 <= w < e <= 180 and -80 <= s < n <= 84):
        raise ValueError("Bounding box must be lon_min < lon_max, lat_min < lat_max in WGS84")
    if (e - w) > 1.0 or (n - s) > 1.0:
        raise ValueError("Bounding box larger than 1 x 1 degree: too big for the 30 m pipeline")


def load(name: str | None = None) -> Area:
    name = _validate_name(name or os.getenv(ENV, DEFAULT))
    path = AREAS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Unknown area '{name}': create {path} (python -m agrisim.pipelines.prepare_area)")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    w, e, s, n = (float(v) for v in cfg["study_area"])
    _validate_box(w, e, s, n)
    pilot = tuple(float(v) for v in cfg.get("pilot") or ((w + e) / 2, (s + n) / 2))
    crs = cfg.get("crs") or f"EPSG:{utm_epsg((w + e) / 2, (s + n) / 2)}"
    root = REPO / cfg.get("data_root", f"data/areas/{name}")
    outputs = REPO / cfg.get("outputs", f"data/areas/{name}/outputs")
    aoi = tuple(float(v) for v in cfg["aoi"]) if cfg.get("aoi") else (w - 0.1, e + 0.1, s - 0.1, n + 0.1)
    known = {"name", "label", "study_area", "pilot", "crs", "data_root", "outputs", "fire", "aoi", "notes"}
    return Area(name=name, label=cfg.get("label", name), study_area=(w, e, s, n), pilot=pilot, crs=crs,
                data_root=root, outputs=outputs, fire=cfg.get("fire"), aoi=aoi, notes=cfg.get("notes", ""),
                extra={k: v for k, v in cfg.items() if k not in known})


def create(name: str, bbox_wesn: tuple[float, float, float, float], label: str | None = None,
           pilot: tuple[float, float] | None = None, fire: dict | None = None, overwrite: bool = False) -> Path:
    """Write configs/areas/<name>.yaml for a new area (data under data/areas/<name>/)."""
    name = _validate_name(name)
    w, e, s, n = (float(v) for v in bbox_wesn)
    _validate_box(w, e, s, n)
    path = AREAS_DIR / f"{name}.yaml"
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists (use overwrite=True to replace it)")
    cfg = {"label": label or name, "study_area": [w, e, s, n],
           "pilot": list(pilot) if pilot else [round((w + e) / 2, 5), round((s + n) / 2, 5)],
           "crs": f"EPSG:{utm_epsg((w + e) / 2, (s + n) / 2)}",
           "data_root": f"data/areas/{name}", "outputs": f"data/areas/{name}/outputs",
           "fire": fire, "notes": "Created by prepare_area; pilot point = box centre unless given (not a surveyed field)."}
    AREAS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
