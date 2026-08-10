"""Tests for motion estimation and point nowcasting."""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pytest
from conftest import BASE_TIME, GRID_SIZE, make_frames, rain_blob
from radar.models import Motion, NowcastField, RadarFrame
from radar.nowcast import (
    build_field,
    classify_severity,
    estimate_motion,
    forecast_location,
    sample_window,
)

FORECAST_KWARGS = {"rain_threshold": 0.1, "window_radius": 2, "forecast_minutes": 90}


class TestEstimateMotion:
    @pytest.mark.parametrize(
        ("dy", "dx"),
        [(0, 0), (4, 0), (0, -6), (7, -11), (-3, 9), (20, 20)],
    )
    def test_recovers_known_translation(self, dy: int, dx: int) -> None:
        previous = rain_blob(centre=(120, 120))
        current = rain_blob(centre=(120 + dy, 120 + dx))

        motion = estimate_motion(previous, current)

        assert round(motion.dy) == dy
        assert round(motion.dx) == dx

    def test_empty_field_reports_no_confidence(self) -> None:
        empty = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)

        motion = estimate_motion(empty, empty)

        assert motion.is_known is False
        assert (motion.dy, motion.dx) == (0.0, 0.0)

    def test_nodata_is_not_read_as_rain(self) -> None:
        """NaN cells must not create a phantom echo for the tracker to lock onto."""
        previous = rain_blob(centre=(120, 120))
        current = rain_blob(centre=(125, 120))
        previous[0:20, 0:20] = np.nan
        current[0:20, 0:20] = np.nan

        motion = estimate_motion(previous, current)

        assert round(motion.dy) == 5
        assert round(motion.dx) == 0

    def test_mismatched_shapes_raise(self) -> None:
        with pytest.raises(ValueError, match="different shapes"):
            estimate_motion(np.zeros((10, 10)), np.zeros((12, 12)))


class TestBuildField:
    def test_uses_median_of_pairwise_estimates(self, geometry) -> None:
        frames = make_frames(geometry, motion=(3, -2))

        field = build_field(frames, now=BASE_TIME + timedelta(minutes=27))

        assert round(field.motion.dy) == 3
        assert round(field.motion.dx) == -2
        assert field.latest is frames[-1]

    def test_one_corrupt_frame_does_not_move_the_forecast(self, geometry) -> None:
        """A single bad scan should be outvoted, not averaged in."""
        frames = make_frames(geometry, motion=(3, 0))
        clean = build_field(frames, now=BASE_TIME).motion

        corrupted = list(frames)
        corrupted[2] = RadarFrame(
            timestamp=frames[2].timestamp,
            filename=frames[2].filename,
            data=rain_blob(centre=(20, 200)),
            geometry=geometry,
        )
        noisy = build_field(corrupted, now=BASE_TIME).motion

        assert round(noisy.dy) == round(clean.dy)

    def test_requires_two_frames(self, geometry) -> None:
        with pytest.raises(ValueError, match="At least two frames"):
            build_field(make_frames(geometry, motion=(1, 1), count=1))


class TestSampleWindow:
    def test_outside_the_grid_is_unknown_not_dry(self) -> None:
        grid = rain_blob()

        assert math.isnan(sample_window(grid, -5, 10, 2))
        assert math.isnan(sample_window(grid, 10, GRID_SIZE + 5, 2))

    def test_all_nodata_is_unknown(self) -> None:
        grid = np.full((50, 50), np.nan, dtype=np.float32)

        assert math.isnan(sample_window(grid, 25, 25, 2))

    def test_averages_the_box(self) -> None:
        grid = np.zeros((50, 50), dtype=np.float32)
        grid[24:27, 24:27] = 9.0

        assert sample_window(grid, 25, 25, 1) == pytest.approx(9.0)


class TestForecastLocation:
    def _field(self, geometry, motion: Motion, blob_centre=(120, 120)) -> NowcastField:
        frame = RadarFrame(
            timestamp=BASE_TIME,
            filename="comp.20260807160000.CAP.h5",
            data=rain_blob(centre=blob_centre),
            geometry=geometry,
        )
        return NowcastField(latest=frame, motion=motion, generated_at=BASE_TIME)

    def test_rain_arriving_from_the_north(self, geometry) -> None:
        """Blob sits north of the target and moves south: rain must be forecast."""
        target_y, target_x = 120, 120
        latitude, longitude = self._latlon(geometry, target_y, target_x)
        field = self._field(
            geometry, Motion(dy=6.0, dx=0.0, confidence=0.5), blob_centre=(40, 120)
        )

        forecast = forecast_location(field, latitude, longitude, **FORECAST_KWARGS)

        assert forecast.raining_now is False
        assert forecast.rain_starts_in_minutes is not None
        assert forecast.state == "starting_soon"
        assert forecast.event is not None
        assert forecast.event.total_mm > 0

    def test_rain_overhead_and_moving_away(self, geometry) -> None:
        target_y, target_x = 120, 120
        latitude, longitude = self._latlon(geometry, target_y, target_x)
        field = self._field(geometry, Motion(dy=12.0, dx=0.0, confidence=0.5))

        forecast = forecast_location(field, latitude, longitude, **FORECAST_KWARGS)

        assert forecast.raining_now is True
        assert forecast.rain_ends_in_minutes <= 30
        assert forecast.state == "ending_soon"

    def test_long_lasting_rain_is_not_reported_as_ending(self, geometry) -> None:
        """A dry pixel somewhere in the 90 minute horizon is not "about to stop"."""
        latitude, longitude = self._latlon(geometry, 120, 120)
        field = self._field(geometry, Motion(dy=1.0, dx=0.0, confidence=0.5))

        forecast = forecast_location(field, latitude, longitude, **FORECAST_KWARGS)

        assert forecast.raining_now is True
        # Slow-moving rain never clears inside the horizon at all.
        assert forecast.rain_ends_in_minutes is None
        assert forecast.state == "raining"

    def test_location_outside_the_composite_has_no_coverage(self, geometry) -> None:
        """NaN everywhere must read as "unknown", never as "dry"."""
        frame = RadarFrame(
            timestamp=BASE_TIME,
            filename="comp.20260807160000.CAP.h5",
            data=np.full((geometry.ysize, geometry.xsize), np.nan, dtype=np.float32),
            geometry=geometry,
        )
        field = NowcastField(frame, Motion(0.0, 0.0, 0.0), BASE_TIME)
        latitude, longitude = self._latlon(geometry, 120, 120)

        forecast = forecast_location(field, latitude, longitude, **FORECAST_KWARGS)

        assert forecast.has_radar_coverage is False
        assert forecast.rain_rate_mm_h is None
        assert forecast.raining_now is False

    def test_clear_sky_stays_clear(self, geometry) -> None:
        latitude, longitude = self._latlon(geometry, 20, 20)
        field = self._field(geometry, Motion(dy=0.0, dx=0.0, confidence=0.0))

        forecast = forecast_location(field, latitude, longitude, **FORECAST_KWARGS)

        assert forecast.state == "dry"
        assert forecast.event is None
        assert forecast.rain_starts_in_minutes is None

    def test_series_length_follows_the_horizon(self, geometry) -> None:
        latitude, longitude = self._latlon(geometry, 120, 120)
        field = self._field(geometry, Motion(dy=1.0, dx=0.0, confidence=0.3))

        forecast = forecast_location(
            field,
            latitude,
            longitude,
            rain_threshold=0.1,
            window_radius=2,
            forecast_minutes=30,
        )

        assert len(forecast.series_mm_h) == 6
        assert len(forecast.series_with_time()) == 6

    def test_frame_age_is_subtracted_from_lead_time(self, geometry) -> None:
        """A frame published eight minutes ago must not promise rain in 25 minutes."""
        latitude, longitude = self._latlon(geometry, 120, 120)
        frame = RadarFrame(
            timestamp=BASE_TIME,
            filename="comp.20260807160000.CAP.h5",
            data=rain_blob(centre=(40, 120)),
            geometry=geometry,
        )
        fresh = NowcastField(frame, Motion(6.0, 0.0, 0.5), BASE_TIME)
        stale = NowcastField(frame, Motion(6.0, 0.0, 0.5), BASE_TIME + timedelta(minutes=8))

        early = forecast_location(fresh, latitude, longitude, **FORECAST_KWARGS)
        late = forecast_location(stale, latitude, longitude, **FORECAST_KWARGS)

        assert late.rain_starts_in_minutes < early.rain_starts_in_minutes

    @staticmethod
    def _latlon(geometry, y: int, x: int) -> tuple[float, float]:
        lon = geometry.ll_lon + x / (geometry.xsize - 1) * (geometry.ur_lon - geometry.ll_lon)
        lat = geometry.ur_lat - y / (geometry.ysize - 1) * (geometry.ur_lat - geometry.ll_lat)
        return lat, lon


@pytest.mark.parametrize(
    ("peak", "expected"),
    [
        (0.0, "very_light"),
        (0.49, "very_light"),
        (0.5, "light"),
        (1.99, "light"),
        (2.0, "moderate"),
        (6.99, "moderate"),
        (7.0, "heavy"),
        (14.99, "heavy"),
        (15.0, "extreme"),
        (120.0, "extreme"),
    ],
)
def test_severity_bands(peak: float, expected: str) -> None:
    assert classify_severity(peak) == expected
