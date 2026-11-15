"""Field-specific HLS window planning and archive lookup for saved Evia polygons.

Planning is local and side-effect free. Acquisition is an explicit UI/CLI action.
Raw-cache identifiers include a boundary digest so geometry edits do not reuse
an incompatible HLS centre/window. A window can contain at most 129x129 pixels.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from rasterio.warp import transform, transform_geom
from shapely.geometry import shape

from .hls_fields import Site, interior_pixels

PIXEL_M = 30
MARGIN_PIXELS = 4
MAX_SIDE = 129


@dataclass(frozen=True)
class FieldHLSPlan:
    site: Site
    boundary_digest: str
    area_hectares: float
    approx_width_m: float
    approx_height_m: float


def _geometry(boundary: str | dict) -> dict:
    try:
        geojson = json.loads(boundary) if isinstance(boundary, str) else boundary
        polygon = shape(geojson)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise ValueError("Expected a saved WGS84 GeoJSON Polygon or MultiPolygon") from exc
    if polygon.geom_type not in ("Polygon", "MultiPolygon") or not polygon.is_valid or polygon.is_empty:
        raise ValueError("The saved field boundary must be a valid Polygon/MultiPolygon")
    w, s, e, n = polygon.bounds
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("Saved boundary coordinates must be WGS84 longitude/latitude")
    return geojson


def field_hls_plan(boundary: str | dict, field_id: int | str,
                   *, margin_pixels: int = MARGIN_PIXELS, max_side: int = MAX_SIDE) -> FieldHLSPlan:
    """Make a native-size square containing the entire polygon plus a safety margin.

    The size calculation uses the polygon's UTM bounding rectangle, not its
    centroid or area alone. Extra margin allows for arbitrary HLS grid origins.
    The downloaded/processed image is checked again against actual pixel bounds.
    """
    geometry = _geometry(boundary)
    if not (1 <= margin_pixels <= 16):
        raise ValueError("margin_pixels must be 1..16")
    if not (3 <= max_side <= MAX_SIDE and max_side % 2):
        raise ValueError(f"max_side must be odd and <= {MAX_SIDE}")
    identity = str(field_id)
    if not identity.isascii() or not identity.isdecimal():
        raise ValueError("Saved field_id must be a numeric SQLite field ID")
    polygon = shape(geometry)
    lon = polygon.centroid.x
    zone = min(60, max(1, int(math.floor((lon + 180) / 6)) + 1))
    crs = f"EPSG:{32600 + zone if polygon.centroid.y >= 0 else 32700 + zone}"
    projected = shape(transform_geom("EPSG:4326", crs, geometry))
    west, south, east, north = projected.bounds
    width, height = east - west, north - south
    half_span = max(width, height) / 2
    radius = int(math.ceil(half_span / PIXEL_M)) + margin_pixels
    side = max(3, 2 * radius + 1)
    if side > max_side:
        area = projected.area / 10_000
        raise ValueError(
            f"Saved boundary needs about {side}×{side} HLS pixels "
            f"({width / 1000:.2f}×{height / 1000:.2f} km bounds; {area:.1f} ha polygon). "
            f"This exceeds the safe {max_side}×{max_side} window. "
            "Check that you drew one agricultural field, not a wider region. "
            "Large polygons require a separately designed multi-window mosaic."
        )
    lon_c, lat_c = transform(crs, "EPSG:4326", [(west + east) / 2], [(south + north) / 2])
    serialized = json.dumps(geometry, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    site = Site(f"field_{identity}_{digest[:12]}", lon_c[0], lat_c[0], side)
    return FieldHLSPlan(site, digest, projected.area / 10_000, width, height)


def recent_season_periods(as_of: date, *, count: int = 4) -> list[tuple[str, str]]:
    """Nonoverlapping September–May periods, ending at the assessment date.

    HLS catalog availability timestamps still govern which data can enter
    historical assessments; downloading later never makes them historically known.
    """
    if not 1 <= count <= 10:
        raise ValueError("count must be 1..10")
    first_year = as_of.year if as_of.month >= 9 else as_of.year - 1
    periods = []
    for year in range(first_year - count + 1, first_year + 1):
        start = date(year, 9, 1)
        end = min(as_of, date(year + 1, 5, 31))
        if start <= end:
            periods.append((start.isoformat(), end.isoformat()))
    return periods


def candidate_archives(proc: Path, site_name: str):
    """Prefer exact boundary-version site archives, then legacy Evia pilot data."""
    batch_root = proc / "evia_sowing" / "hls_batches"
    if not batch_root.is_dir():
        return
    for site in (site_name, "evia_pilot"):
        candidates = sorted(batch_root.glob(f"*/{site}/hls/field_context.npz"), reverse=True)
        for path in candidates:
            if not path.parents[2].name.endswith(".partial"):
                yield path
    # Legacy pilot archive may live outside batch snapshots.
    original = proc / "evia_sowing" / "hls" / "field_context.npz"
    if original.is_file():
        yield original


def archive_covers_field(archive: Path, boundary: str | dict) -> bool:
    """Cheap coverage precheck: only load georeferencing, not full reflectance stack."""
    with np.load(archive, allow_pickle=False) as z:
        h, w = z["candidate_mask"].shape
        try:
            mask = interior_pixels(str(z["crs"].item()), tuple(z["transform"]),
                                   (h, w), _geometry(boundary))
        except ValueError as exc:
            if "Parcel extends beyond the archive" in str(exc):
                return False
            raise
        return bool(mask.any())
