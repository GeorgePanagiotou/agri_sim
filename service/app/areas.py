"""Area of interest: a named area, a bbox or a point. All coordinates WGS84 lon/lat (EPSG:4326)."""
from __future__ import annotations

from dataclasses import dataclass

# Mirrors data_prep/config.py (there the order is lon_min, lon_max, lat_min, lat_max; here west, south, east, north).
NAMED_AREAS: dict[str, dict] = {
    "study_area": {"label": "Kireas - Agia Anna (study area)", "bbox": (23.32, 38.75, 23.50, 38.95)},
    "aoi": {"label": "North Evia (analysis area)", "bbox": (22.80, 38.60, 23.70, 39.05)},
    "istiaia_plain": {"label": "Field 1 - Istiaia plain", "point": (23.15, 38.94)},
    "mantoudi_valley": {"label": "Field 2 - Mantoudi valley", "point": (23.47, 38.80)},
    "limni_slope": {"label": "Field 3 - Limni hillside", "point": (23.32, 38.77)},
}


class AreaError(ValueError):
    pass


@dataclass(frozen=True)
class Area:
    west: float
    south: float
    east: float
    north: float
    name: str | None = None

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
                "centroid": [round(self.lon, 5), round(self.lat, 5)], "is_point": self.is_point}


def _check(w: float, s: float, e: float, n: float) -> None:
    if not (-180 <= w <= e <= 180 and -90 <= s <= n <= 90):
        raise AreaError("coordinates out of range, or bbox is not west<=east, south<=north (lon -180..180, lat -90..90)")


def parse_area(area: str | None, lon: float | None, lat: float | None, bbox: str | None) -> Area:
    """Exactly one of: area=<name> | lon+lat | bbox=west,south,east,north."""
    given = [area is not None, lon is not None or lat is not None, bbox is not None]
    if sum(given) != 1:
        raise AreaError("give exactly one of: area=<name>, lon+lat, bbox=west,south,east,north")
    if area is not None:
        spec = NAMED_AREAS.get(area)
        if spec is None:
            raise AreaError(f"unknown area {area!r}; known: {', '.join(NAMED_AREAS)}")
        w, s, e, n = spec["bbox"] if "bbox" in spec else (*spec["point"], *spec["point"])
        return Area(w, s, e, n, name=area)
    if bbox is not None:
        try:
            w, s, e, n = (float(v) for v in bbox.split(","))
        except ValueError:
            raise AreaError("bbox must be 4 numbers: west,south,east,north") from None
        _check(w, s, e, n)
        return Area(w, s, e, n)
    if lon is None or lat is None:
        raise AreaError("a point needs both lon and lat")
    _check(lon, lat, lon, lat)
    return Area(lon, lat, lon, lat)
