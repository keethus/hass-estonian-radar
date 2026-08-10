"""Geographic helpers: grid projection, radar distance, coverage quality."""

from __future__ import annotations

import logging
import math

from .const import (
    COVERAGE_BANDS,
    COVERAGE_OUT_OF_RANGE,
    RADAR_SITES,
)
from .models import GridGeometry

_LOGGER = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest_radar(lat: float, lon: float) -> tuple[str, float]:
    """Return ``(name, distance_km)`` of the closest radar site."""
    name, distance = min(
        (
            (site_name, haversine_km(lat, lon, site_lat, site_lon))
            for site_name, site_lat, site_lon in RADAR_SITES
        ),
        key=lambda item: item[1],
    )
    return name, distance


def coverage_quality(distance_km: float) -> str:
    """Classify how trustworthy the radar is at a given distance.

    Radar beams climb with range because of their elevation angle and the curvature of
    the Earth, so a location 200 km out is only sampled several kilometres up — deep
    convection still shows, drizzle and shallow winter precipitation do not.
    """
    for bound, label in COVERAGE_BANDS:
        if distance_km < bound:
            return label
    return COVERAGE_OUT_OF_RANGE


def latlon_to_pixel(geometry: GridGeometry, lat: float, lon: float) -> tuple[int, int]:
    """Map WGS84 coordinates to a ``(y, x)`` pixel index in the composite grid.

    Uses the grid's own projection definition when pyproj can parse it. The linear
    fallback is only correct for small areas near the middle of the domain, but it
    keeps the integration working if the projection string is ever missing or exotic.
    """
    projected = _projected_pixel(geometry, lat, lon)
    if projected is not None:
        return projected

    x = (lon - geometry.ll_lon) / (geometry.ur_lon - geometry.ll_lon) * (geometry.xsize - 1)
    y = (geometry.ur_lat - lat) / (geometry.ur_lat - geometry.ll_lat) * (geometry.ysize - 1)
    return round(y), round(x)


def _projected_pixel(geometry: GridGeometry, lat: float, lon: float) -> tuple[int, int] | None:
    if not geometry.projdef:
        return None
    try:
        from pyproj import Proj

        projection = Proj(geometry.projdef)
        ul_x, ul_y = projection(geometry.ul_lon, geometry.ul_lat)
        ur_x, _ = projection(geometry.ur_lon, geometry.ur_lat)
        _, ll_y = projection(geometry.ll_lon, geometry.ll_lat)
        point_x, point_y = projection(lon, lat)

        x_span = (ur_x - ul_x) / float(geometry.xsize - 1)
        y_span = (ul_y - ll_y) / float(geometry.ysize - 1)
        if not x_span or not y_span:
            return None

        return (
            round((ul_y - point_y) / y_span),
            round((point_x - ul_x) / x_span),
        )
    except (ImportError, RuntimeError, ValueError, TypeError) as err:
        _LOGGER.debug("Falling back to linear grid mapping: %s", err)
        return None


def pixel_size_km(geometry: GridGeometry) -> float:
    """Approximate ground size of one grid cell, used to report storm speed."""
    height = haversine_km(geometry.ll_lat, geometry.ll_lon, geometry.ul_lat, geometry.ul_lon)
    if height <= 0 or geometry.ysize <= 1:
        return 1.0
    return height / (geometry.ysize - 1)


def motion_to_speed_bearing(
    dy: float, dx: float, cell_km: float, step_minutes: int
) -> tuple[float, float]:
    """Convert pixel motion into ``(km/h, compass bearing)``.

    Grid rows run north to south, so a positive ``dy`` means the field is moving
    *southward*.
    """
    north = -dy * cell_km
    east = dx * cell_km
    distance_km = math.hypot(north, east)
    speed = distance_km / (step_minutes / 60.0)
    bearing = (math.degrees(math.atan2(east, north)) + 360.0) % 360.0
    return speed, bearing
