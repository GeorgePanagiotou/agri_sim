"""Area of interest: a named area, a bbox or a point. All coordinates WGS84 lon/lat (EPSG:4326).

Named areas come from the repo's area registry, configs/areas/<name>.yaml (the same files the data pipeline
uses: `python -m agrisim.pipelines.prepare_area --name <name> --bbox ...`). For each area <name>:

    <name>          its study box (where the pipeline downloaded data)
    <name>_aoi      the wider analysis box, when the config has one
    <name>_pilot    the pilot point

The registry is re-read on every call, so an area prepared while the service runs shows up without a restart.
A bbox or point that falls inside a registered study box uses that area's local files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# Older names, kept so existing requests keep working (Evia demo).
LEGACY = {
    "study_area": "evia",
    "aoi": "evia_aoi",
}
EVIA_POINTS = {   # demo spots from data_prep/config.py (not surveyed parcels)
    "istiaia_plain": ("Field 1 - Istiaia plain", (23.15, 38.94)),
    "mantoudi_valley": ("Field 2 - Mantoudi valley", (23.47, 38.80)),
    "limni_slope": ("Field 3 - Limni hillside", (23.32, 38.77)),
}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class AreaError(ValueError):
    pass


@dataclass(frozen=True)
class Area:
    west: float
    south: float
    east: float
    north: float
    name: str | None = None
    home: str | None = None        # registered area whose local files serve this request
    data_dir: Path | None = None   # <data_root>/processed of that area

    @property
    def lon(self) -> float:
        return (self.west + self.east) / 2

    @property
    def lat(self) -> float:
        return (self.south + self.north) / 2

    @property
    def is_point(self) -> bool:
        return self.west == self.east and self.south == self.north

    def as_dict(self) -> dict:
        return {"name": self.name, "bbox": [self.west, self.south, self.east, self.north],
                "centroid": [round(self.lon, 5), round(self.lat, 5)], "is_point": self.is_point,
                "local_data_from": self.home}


def registry(repo_root: Path) -> dict[str, dict]:
    """{area name: {label, study (w,s,e,n), aoi, pilot, data_dir}} from configs/areas/*.yaml."""
    out = {}
    for path in sorted((repo_root / "configs" / "areas").glob("*.yaml")):
        name = path.stem
        if not NAME_RE.match(name):
            continue
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            w, e, s, n = (float(v) for v in cfg["study_area"])   # file order: lon_min, lon_max, lat_min, lat_max
        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError):
            continue   # a broken config must not take the service down
        aoi = cfg.get("aoi")
        pilot = cfg.get("pilot") or [(w + e) / 2, (s + n) / 2]
        out[name] = {
            "label": cfg.get("label", name),
            "study": (w, s, e, n),
            "aoi": (float(aoi[0]), float(aoi[2]), float(aoi[1]), float(aoi[3])) if aoi else None,
            "pilot": (float(pilot[0]), float(pilot[1])),
            "data_dir": repo_root / cfg.get("data_root", f"data/areas/{name}") / "processed",
            "notes": cfg.get("notes"),
        }
    return out


def named_areas(repo_root: Path) -> dict[str, dict]:
    """Every name a request may use: {name: {label, bbox | point, home}}."""
    reg = registry(repo_root)
    names = {}
    for name, a in reg.items():
        names[name] = {"label": a["label"], "bbox": a["study"], "home": name}
        if a["aoi"]:
            names[f"{name}_aoi"] = {"label": f"{a['label']} (analysis area)", "bbox": a["aoi"], "home": name}
        names[f"{name}_pilot"] = {"label": f"{a['label']} (pilot point)", "point": a["pilot"], "home": name}
    if "evia" in reg:
        for old, new in LEGACY.items():
            if new in names:
                names[old] = {**names[new], "label": names[new]["label"] + f" (alias of {new})"}
        for key, (label, point) in EVIA_POINTS.items():
            names[key] = {"label": label, "point": point, "home": "evia"}
    return names


def _check(w: float, s: float, e: float, n: float) -> None:
    if not (-180 <= w <= e <= 180 and -90 <= s <= n <= 90):
        raise AreaError("coordinates out of range, or bbox is not west<=east, south<=north (lon -180..180, lat -90..90)")


def _home_for(lon: float, lat: float, reg: dict[str, dict]) -> str | None:
    """The registered area whose study box contains the point (smallest box wins)."""
    inside = [(abs((a["study"][2] - a["study"][0]) * (a["study"][3] - a["study"][1])), name)
              for name, a in reg.items()
              if a["study"][0] <= lon <= a["study"][2] and a["study"][1] <= lat <= a["study"][3]]
    return min(inside)[1] if inside else None


def parse_area(area: str | None, lon: float | None, lat: float | None, bbox: str | None,
               repo_root: Path) -> Area:
    """Exactly one of: area=<name> | lon+lat | bbox=west,south,east,north."""
    given = [area is not None, lon is not None or lat is not None, bbox is not None]
    if sum(given) != 1:
        raise AreaError("give exactly one of: area=<name>, lon+lat, bbox=west,south,east,north")
    reg = registry(repo_root)
    if area is not None:
        names = named_areas(repo_root)
        spec = names.get(area)
        if spec is None:
            raise AreaError(f"unknown area {area!r}; known: {', '.join(names)}")
        w, s, e, n = spec["bbox"] if "bbox" in spec else (*spec["point"], *spec["point"])
        home = spec["home"]
        return Area(w, s, e, n, name=area, home=home, data_dir=reg[home]["data_dir"])
    if bbox is not None:
        try:
            w, s, e, n = (float(v) for v in bbox.split(","))
        except ValueError:
            raise AreaError("bbox must be 4 numbers: west,south,east,north") from None
    else:
        if lon is None or lat is None:
            raise AreaError("a point needs both lon and lat")
        w, s, e, n = lon, lat, lon, lat
    _check(w, s, e, n)
    home = _home_for((w + e) / 2, (s + n) / 2, reg)
    return Area(w, s, e, n, home=home, data_dir=reg[home]["data_dir"] if home else None)
