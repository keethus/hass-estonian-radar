"""Tests for distance, coverage classification and grid mapping."""

from __future__ import annotations

import pytest
from radar.geo import (
    coverage_quality,
    haversine_km,
    latlon_to_pixel,
    motion_to_speed_bearing,
    nearest_radar,
    pixel_size_km,
)

# Cēsis, northern Latvia — near the useful edge of the Estonian radar network.
CESIS = (57.31211, 25.27102)
RIGA = (56.9496, 24.1052)
LISBON = (38.7223, -9.1393)


def test_haversine_matches_known_distance() -> None:
    # Cēsis to Rīga is about 75 km in a straight line.
    assert haversine_km(*CESIS, *RIGA) == pytest.approx(78, abs=5)


def test_zero_distance() -> None:
    assert haversine_km(*CESIS, *CESIS) == pytest.approx(0.0)


class TestCoverage:
    def test_cesis_is_within_useful_range(self) -> None:
        name, distance = nearest_radar(*CESIS)

        assert name == "Sürgavere"
        assert 100 < distance < 160
        assert coverage_quality(distance) == "good"

    def test_riga_is_marginal(self) -> None:
        _, distance = nearest_radar(*RIGA)

        assert coverage_quality(distance) == "marginal"

    def test_far_away_is_out_of_range(self) -> None:
        _, distance = nearest_radar(*LISBON)

        assert coverage_quality(distance) == "out_of_range"

    @pytest.mark.parametrize(
        ("distance", "expected"),
        [
            (0.0, "excellent"),
            (79.9, "excellent"),
            (80.0, "good"),
            (149.9, "good"),
            (150.0, "marginal"),
            (249.9, "marginal"),
            (250.0, "out_of_range"),
        ],
    )
    def test_band_edges(self, distance: float, expected: str) -> None:
        assert coverage_quality(distance) == expected


class TestGridMapping:
    def test_corners_map_to_corners(self, geometry) -> None:
        assert latlon_to_pixel(geometry, geometry.ur_lat, geometry.ll_lon) == (0, 0)
        assert latlon_to_pixel(geometry, geometry.ll_lat, geometry.ur_lon) == (
            geometry.ysize - 1,
            geometry.xsize - 1,
        )

    def test_centre_maps_to_centre(self, geometry) -> None:
        mid_lat = (geometry.ll_lat + geometry.ur_lat) / 2
        mid_lon = (geometry.ll_lon + geometry.ur_lon) / 2

        y, x = latlon_to_pixel(geometry, mid_lat, mid_lon)

        assert y == pytest.approx((geometry.ysize - 1) / 2, abs=1)
        assert x == pytest.approx((geometry.xsize - 1) / 2, abs=1)

    def test_pixel_size_is_plausible(self, geometry) -> None:
        # 4 degrees of latitude over 240 rows is a little under 2 km per cell.
        assert pixel_size_km(geometry) == pytest.approx(1.86, abs=0.1)


class TestMotionConversion:
    def test_southward_motion_reports_bearing_180(self) -> None:
        speed, bearing = motion_to_speed_bearing(dy=6.0, dx=0.0, cell_km=1.0, step_minutes=5)

        assert bearing == pytest.approx(180.0)
        assert speed == pytest.approx(72.0)

    def test_eastward_motion_reports_bearing_90(self) -> None:
        _, bearing = motion_to_speed_bearing(dy=0.0, dx=4.0, cell_km=1.0, step_minutes=5)

        assert bearing == pytest.approx(90.0)

    def test_northwest_motion(self) -> None:
        _, bearing = motion_to_speed_bearing(dy=-3.0, dx=-3.0, cell_km=1.0, step_minutes=5)

        assert bearing == pytest.approx(315.0)
