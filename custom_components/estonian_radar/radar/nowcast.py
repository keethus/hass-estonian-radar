"""Motion estimation and point nowcasting.

The pipeline is deliberately split in two halves with very different costs:

* :func:`build_field` runs once per radar update. It estimates how the precipitation
  field is moving, which is the only genuinely expensive step.
* :func:`forecast_location` runs once per configured location and is essentially free,
  because advecting the field and sampling a point is the same as sampling the
  *unadvected* field at a back-tracked pixel.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime

import numpy as np

from .const import (
    FRAME_STEP_MINUTES,
    MASS_THRESHOLD_MM_H,
    MAX_MOTION_SHIFT_PX,
    MIN_MOTION_CONFIDENCE,
    SEVERITY_BANDS,
    SEVERITY_EXTREME,
)
from .geo import (
    coverage_quality,
    latlon_to_pixel,
    motion_to_speed_bearing,
    nearest_radar,
    pixel_size_km,
)
from .models import (
    LocationForecast,
    Motion,
    NowcastField,
    RadarFrame,
    RainEvent,
)

_LOGGER = logging.getLogger(__name__)


# --- motion estimation --------------------------------------------------------------


def estimate_motion(
    previous: np.ndarray,
    current: np.ndarray,
    max_shift: int = MAX_MOTION_SHIFT_PX,
) -> Motion:
    """Estimate the displacement from ``previous`` to ``current`` in pixels.

    Uses phase correlation: the normalised cross-power spectrum of the two frames has
    a sharp peak at their relative shift. This replaces an exhaustive search over every
    candidate shift, which costs ``O(N²·S²)`` and is roughly 25x slower for the same
    answer on a full composite grid.
    """
    a = _clean(previous)
    b = _clean(current)

    if a.shape != b.shape:
        raise ValueError("Cannot estimate motion between grids of different shapes")
    if max(float(a.max()), float(b.max())) < MASS_THRESHOLD_MM_H:
        # Nothing on the radar to track. Reporting "no motion" with zero confidence is
        # honest; pretending to know a direction is not.
        return Motion(dy=0.0, dx=0.0, confidence=0.0)

    window = np.hanning(a.shape[0])[:, None] * np.hanning(a.shape[1])[None, :]
    spectrum_a = np.fft.rfft2(a * window)
    spectrum_b = np.fft.rfft2(b * window)

    cross = spectrum_b * np.conj(spectrum_a)
    magnitude = np.abs(cross)
    magnitude[magnitude == 0.0] = 1e-12
    correlation = np.fft.fftshift(np.fft.irfft2(cross / magnitude, s=a.shape))

    centre_y, centre_x = a.shape[0] // 2, a.shape[1] // 2
    search = correlation[
        centre_y - max_shift : centre_y + max_shift + 1,
        centre_x - max_shift : centre_x + max_shift + 1,
    ]
    peak_y, peak_x = np.unravel_index(int(np.argmax(search)), search.shape)
    confidence = float(search[peak_y, peak_x])

    if confidence < MIN_MOTION_CONFIDENCE:
        _LOGGER.debug("Motion peak too weak (%.4f), treating field as stationary", confidence)
        return Motion(dy=0.0, dx=0.0, confidence=0.0)

    dy, dx = _refine_subpixel(search, int(peak_y), int(peak_x))
    return Motion(dy=dy - max_shift, dx=dx - max_shift, confidence=confidence)


def _clean(grid: np.ndarray) -> np.ndarray:
    return np.nan_to_num(grid, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def _refine_subpixel(surface: np.ndarray, y: int, x: int) -> tuple[float, float]:
    """Parabolic interpolation around the correlation peak.

    Storms rarely move a whole number of pixels per five minutes; keeping the fraction
    means the error does not accumulate over an 18-step forecast.
    """
    return _parabolic(surface, y, x, axis=0), _parabolic(surface, y, x, axis=1)


def _parabolic(surface: np.ndarray, y: int, x: int, axis: int) -> float:
    index = y if axis == 0 else x
    limit = surface.shape[axis] - 1
    if index <= 0 or index >= limit:
        return float(index)

    if axis == 0:
        low, mid, high = surface[y - 1, x], surface[y, x], surface[y + 1, x]
    else:
        low, mid, high = surface[y, x - 1], surface[y, x], surface[y, x + 1]

    denominator = low - 2.0 * mid + high
    if denominator == 0:
        return float(index)
    return float(index) + 0.5 * float(low - high) / float(denominator)


def build_field(frames: list[RadarFrame], now: datetime | None = None) -> NowcastField:
    """Estimate a single storm motion vector from a sequence of frames.

    The median of the per-pair estimates is used rather than the mean so that one bad
    frame — a partial scan, a burst of clutter — cannot drag the forecast off course.
    """
    if len(frames) < 2:
        raise ValueError("At least two frames are required to estimate motion")

    ordered = sorted(frames, key=lambda frame: frame.timestamp)
    estimates = [
        estimate_motion(ordered[index - 1].data, ordered[index].data)
        for index in range(1, len(ordered))
    ]
    confident = [motion for motion in estimates if motion.is_known]

    if confident:
        motion = Motion(
            dy=float(np.median([m.dy for m in confident])),
            dx=float(np.median([m.dx for m in confident])),
            confidence=float(np.median([m.confidence for m in confident])),
        )
    else:
        motion = Motion(dy=0.0, dx=0.0, confidence=0.0)

    return NowcastField(
        latest=ordered[-1],
        motion=motion,
        generated_at=now or datetime.now(UTC),
    )


# --- point forecasting ---------------------------------------------------------------


def sample_window(grid: np.ndarray, y: int, x: int, radius: int) -> float:
    """Mean rain rate in a box around ``(y, x)``.

    Returns ``NaN`` when the box falls outside the grid or holds no valid data. A point
    that has drifted off the edge of the composite is unknown, not dry.
    """
    if not (0 <= y < grid.shape[0] and 0 <= x < grid.shape[1]):
        return math.nan

    block = grid[
        max(0, y - radius) : min(grid.shape[0], y + radius + 1),
        max(0, x - radius) : min(grid.shape[1], x + radius + 1),
    ]
    if block.size == 0 or bool(np.all(np.isnan(block))):
        return math.nan
    return float(np.nanmean(block))


def forecast_location(
    field: NowcastField,
    latitude: float,
    longitude: float,
    *,
    rain_threshold: float,
    window_radius: int,
    forecast_minutes: int,
) -> LocationForecast:
    """Produce the full nowcast for one location."""
    geometry = field.latest.geometry
    y, x = latlon_to_pixel(geometry, latitude, longitude)

    steps = max(1, forecast_minutes // FRAME_STEP_MINUTES)
    grid = field.latest.data

    now_value = sample_window(grid, y, x, window_radius)
    series = tuple(
        sample_window(grid, *field.source_pixel(y, x, step), window_radius)
        for step in range(1, steps + 1)
    )

    raining_now = not math.isnan(now_value) and now_value >= rain_threshold
    is_wet = [not math.isnan(value) and value >= rain_threshold for value in series]

    starts_in = ends_in = None
    if raining_now:
        first_dry = next((i for i, wet in enumerate(is_wet) if not wet), None)
        if first_dry is not None:
            ends_in = _minutes_from_now(first_dry, field)
    else:
        first_wet = next((i for i, wet in enumerate(is_wet) if wet), None)
        if first_wet is not None:
            starts_in = _minutes_from_now(first_wet, field)

    event = _analyse_event(series, rain_threshold, field)

    radar_name, radar_km = nearest_radar(latitude, longitude)
    cell_km = pixel_size_km(geometry)
    if field.motion.is_known:
        speed, bearing = motion_to_speed_bearing(
            field.motion.dy, field.motion.dx, cell_km, FRAME_STEP_MINUTES
        )
    else:
        speed = bearing = None

    return LocationForecast(
        generated_at=field.generated_at,
        frame_time=field.latest.timestamp,
        frame_age_minutes=round(field.frame_age_minutes, 1),
        pixel=(y, x),
        raining_now=raining_now,
        rain_rate_mm_h=None if math.isnan(now_value) else round(now_value, 3),
        rain_starts_in_minutes=starts_in,
        rain_ends_in_minutes=ends_in,
        event=event,
        series_mm_h=tuple(None if math.isnan(value) else round(value, 3) for value in series),
        step_minutes=FRAME_STEP_MINUTES,
        motion=field.motion,
        motion_kmh=None if speed is None else round(speed, 1),
        motion_bearing=None if bearing is None else round(bearing, 0),
        nearest_radar=radar_name,
        nearest_radar_km=round(radar_km, 1),
        coverage=coverage_quality(radar_km),
        has_radar_coverage=not math.isnan(now_value),
    )


def _minutes_from_now(index: int, field: NowcastField) -> int:
    """Convert a forecast step index into minutes from *now*.

    Steps are anchored to the radar frame, which is already a few minutes old by the
    time it is published, so the frame age has to be subtracted.
    """
    minutes_from_frame = (index + 1) * FRAME_STEP_MINUTES
    return max(0, round(minutes_from_frame - field.frame_age_minutes))


def _analyse_event(
    series: tuple[float, ...], rain_threshold: float, field: NowcastField
) -> RainEvent | None:
    """Describe the first continuous stretch of rain in the point forecast."""
    start = next(
        (
            index
            for index, value in enumerate(series)
            if not math.isnan(value) and value >= rain_threshold
        ),
        None,
    )
    if start is None:
        return None

    end = len(series) - 1
    for index in range(start + 1, len(series)):
        value = series[index]
        if math.isnan(value) or value < rain_threshold:
            end = index - 1
            break

    values = series[start : end + 1]
    peak = max(values)

    return RainEvent(
        starts_in_minutes=_minutes_from_now(start, field),
        duration_minutes=len(values) * FRAME_STEP_MINUTES,
        peak_mm_h=round(peak, 2),
        mean_mm_h=round(sum(values) / len(values), 2),
        total_mm=round(sum(values) * FRAME_STEP_MINUTES / 60.0, 2),
        severity=classify_severity(peak),
    )


def classify_severity(peak_mm_h: float) -> str:
    for bound, label in SEVERITY_BANDS:
        if peak_mm_h < bound:
            return label
    return SEVERITY_EXTREME
