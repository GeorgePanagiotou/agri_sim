"""Field windows, acquisition dates and coverage accounting for HLSL30 batches."""

import csv
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from affine import Affine
from rasterio.warp import transform_geom
from shapely import box, covers
from shapely.geometry import shape

if __package__:
    from .config import SOWING_LAT, SOWING_LON
else:
    from .config import SOWING_LAT, SOWING_LON


@dataclass(frozen=True)
class Site:
    name: str
    lon: float
    lat: float
    size: int

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.name) or self.name.upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ValueError("Use a field_id made of letters, digits, hyphens or underscores")
        if not (3 <= self.size <= 129 and self.size % 2):
            raise ValueError("Use an odd window size from 3 to 129 native pixels")
        if not (-180 < self.lon < 180 and -90 < self.lat < 90):
            raise ValueError("Invalid WGS84 longitude or latitude")
        if self.name.lower() == "evia_pilot" and (self.name, self.lon, self.lat, self.size) != (
            "evia_pilot",
            SOWING_LON,
            SOWING_LAT,
            33,
        ):
            raise ValueError("Use a new field_id for a window different from evia_pilot")

    def directory(self, base):
        folder = base / "evia_sowing"
        if self.name != "evia_pilot":
            folder = folder / "sites" / self.name
        return folder / "hls"


@dataclass(frozen=True)
class FieldWindow:
    site: Site
    start: str
    end: str
    farm_id: str = ""
    crop_id: str = ""
    sown_on: str = ""
    greenup_on: str = ""


def read_parcels(path):
    collection = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(collection, dict) or not isinstance(collection.get("features"), list):
        raise ValueError("Supply a GeoJSON FeatureCollection of confirmed field polygons")
    geometries = {}
    for feature in collection["features"]:
        field_id = (feature.get("properties") or {}).get("field_id")
        if field_id is None or not str(field_id).strip() or not feature.get("geometry"):
            raise ValueError("Each parcel needs properties.field_id and its polygon geometry")
        key = str(field_id).strip()
        if key in geometries:
            raise ValueError("Duplicate field IDs in parcel file")
        geometries[key] = feature["geometry"]
    return geometries


def interior_pixels(crs, affine, dimensions, geometry):
    """Mask whole native pixels using the confirmed WGS84 parcel boundary."""
    projected = shape(transform_geom("EPSG:4326", crs, geometry))
    if (
        projected.geom_type not in ("Polygon", "MultiPolygon")
        or not projected.is_valid
        or projected.is_empty
    ):
        raise ValueError("Each confirmed parcel must be a valid WGS84 Polygon or MultiPolygon")
    h, w = dimensions
    tr = Affine(*affine)
    if tr.b != 0 or tr.d != 0 or tr.a <= 0 or tr.e >= 0:
        raise ValueError("Expected a north-up grid")
    west, north = tr.c, tr.f
    east, south = west + w * tr.a, north + h * tr.e
    if not box(west, south, east, north).covers(projected):
        raise ValueError(
            "Parcel extends beyond the archive. Download a window covering its entire boundary."
        )
    rr, cc = np.indices((h, w))
    xx, yy = west + cc * tr.a, north + rr * tr.e
    return covers(projected, box(xx, yy + tr.e, xx + tr.a, yy))


def iso_day(value):
    try:
        parsed = date.fromisoformat(value)
        if value != parsed.isoformat():
            raise ValueError
    except ValueError:
        raise ValueError(f"Expected a date in YYYY-MM-DD format, got {value!r}") from None
    return value


def read_windows(path: Path, default_size):
    windows = []
    sites = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"field_id", "lon", "lat", "start_date", "end_date"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"{path.name} needs columns: {', '.join(sorted(required))}")
        for row in reader:
            try:
                if None in row:
                    raise ValueError("Unexpected extra CSV values")
                row = {key: (value or "").strip() for key, value in row.items()}
                site = Site(
                    row["field_id"],
                    float(row["lon"]),
                    float(row["lat"]),
                    int(row.get("size") or default_size),
                )
                known = sites.setdefault(site.name.casefold(), site)
                if known != site:
                    raise ValueError(f"Use one spelling, centre and size for {site.name}")
                start, end = iso_day(row["start_date"]), iso_day(row["end_date"])
                if end < start:
                    raise ValueError("end_date must be on or after start_date")
                sown, green = row.get("sown_on", ""), row.get("greenup_on", "")
                for day in (sown, green):
                    if day:
                        iso_day(day)
                if sown and green and green < sown:
                    raise ValueError("greenup_on must be on or after sown_on")
                windows.append(
                    FieldWindow(
                        site,
                        start,
                        end,
                        row.get("farm_id", ""),
                        row.get("crop_id", ""),
                        sown,
                        green,
                    )
                )
            except ValueError as exc:
                raise ValueError(f"{path.name}, row {reader.line_num}: {exc}") from None
    if not windows:
        raise ValueError("Add at least one field and date range to the CSV")
    by_site = {}
    for window in windows:
        by_site.setdefault(window.site, []).append(window)
    for site, periods in by_site.items():
        periods.sort(key=lambda w: w.start)
        if any(a.end >= b.start for a, b in zip(periods, periods[1:])):
            raise ValueError(f"Use non-overlapping date ranges for {site.name}")
        if len({w.farm_id for w in periods if w.farm_id}) > 1:
            raise ValueError(f"Use one farm_id for {site.name}")
    return by_site


def choose_dates(dates, limit):
    """Sample distinct UTC acquisitions in order, without using labels or cloud outcomes."""
    days = sorted(set(dates))
    if limit is None or len(days) <= limit:
        return days
    if limit == 1:
        return [days[len(days) // 2]]
    indices = np.rint(np.linspace(0, len(days) - 1, limit)).astype(int)
    return [days[i] for i in indices]


def coverage(window, available, chosen, rows, has_parcel, source):
    clear = rows.loc[
        (rows["clear_interior_pixels"] >= 9)
        & (rows["clear_interior_pixels"] >= 0.8 * rows["full_interior_pixels"]),
        "date_utc",
    ]
    if window.sown_on:
        clear = clear[clear >= window.sown_on]
    before = after = None
    if window.greenup_on:
        before = int((clear < window.greenup_on).sum())
        after = len(clear) - before
    return {
        "field_id": window.site.name,
        "farm_id": window.farm_id,
        "start_date": window.start,
        "end_date": window.end,
        "sown_on": window.sown_on,
        "greenup_on": window.greenup_on,
        "source": source,
        "footprint": "parcel" if has_parcel else "candidate_3x3",
        "available_dates": available,
        "selected_dates": len(chosen),
        "usable_dates": len(clear),
        "days_short_of_six": max(0, 6 - len(clear)),
        "usable_before_greenup": before,
        "usable_on_or_after_greenup": after,
        "three_each_side": "" if before is None else before >= 3 and after >= 3,
    }
