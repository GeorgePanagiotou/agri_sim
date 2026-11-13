"""Georeferencing helpers; coordinate order is always longitude, latitude."""
from pyproj import Geod
from shapely.geometry import shape

GEOD = Geod(ellps='WGS84')

def area_hectares(geometry):
    geom = shape(geometry) if isinstance(geometry, dict) else geometry
    area_m2, _ = GEOD.geometry_area_perimeter(geom)
    return abs(area_m2) / 10_000

def within_lonlat(lon, lat, bounds):
    west, east, south, north = bounds
    return west <= lon <= east and south <= lat <= north
