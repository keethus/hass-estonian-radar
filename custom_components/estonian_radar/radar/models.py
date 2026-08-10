"""Value objects passed between the stages of the nowcast pipeline.

This package deliberately imports nothing from Home Assistant so that it can be
unit-tested on its own and, if it ever proves useful elsewhere, extracted into a
standalone library.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from .const import ENDING_SOON_MINUTES


@dataclass(frozen=True, slots=True)
class GridGeometry:
    """Georeferencing metadata of an ODIM composite grid."""

    xsize: int
    ysize: int
    ll_lat: float
    ll_lon: float
    ur_lat: float
    ur_lon: float
    ul_lat: float
    ul_lon: float
    projdef: str | None


@dataclass(frozen=True, slots=True)
class RadarFrame:
    """A single decoded composite frame.

    ``data`` holds rain rate in mm/h as float32. ``NaN`` means the radar network has
    no measurement for that cell — which is *not* the same as "no rain" and must never
    be silently treated as zero.
    """

    timestamp: datetime
    filename: str
    data: np.ndarray
    geometry: GridGeometry

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Motion:
    """Estimated displacement of the precipitation field, in pixels per frame step."""

    dy: float
    dx: float
    confidence: float

    @property
    def is_known(self) -> bool:
        return self.confidence > 0.0


@dataclass(frozen=True, slots=True)
class RainEvent:
    """The first contiguous run of rain found in a point forecast."""

    starts_in_minutes: int
    duration_minutes: int
    peak_mm_h: float
    mean_mm_h: float
    total_mm: float
    severity: str


@dataclass(frozen=True, slots=True)
class NowcastField:
    """A motion-corrected view of the radar composite.

    The forecast is never materialised as a stack of shifted grids. Advecting the
    field by ``k`` steps and sampling at pixel ``(y, x)`` is identical to sampling the
    latest frame at ``(y - k·dy, x - k·dx)``, so a point forecast costs a handful of
    array slices no matter how many locations are configured.
    """

    latest: RadarFrame
    motion: Motion
    generated_at: datetime

    @property
    def frame_age_minutes(self) -> float:
        return max(0.0, (self.generated_at - self.latest.timestamp).total_seconds() / 60.0)

    def source_pixel(self, y: int, x: int, step: int) -> tuple[int, int]:
        """Return the pixel of the latest frame that will sit at ``(y, x)``.

        ``step`` is the number of frame intervals into the future (0 = now).
        """
        return (
            y - round(self.motion.dy * step),
            x - round(self.motion.dx * step),
        )


@dataclass(frozen=True, slots=True)
class LocationForecast:
    """Everything the integration exposes for one configured location."""

    generated_at: datetime
    frame_time: datetime
    frame_age_minutes: float
    pixel: tuple[int, int]
    raining_now: bool
    rain_rate_mm_h: float | None
    rain_starts_in_minutes: int | None
    rain_ends_in_minutes: int | None
    event: RainEvent | None
    series_mm_h: tuple[float | None, ...]
    step_minutes: int
    motion: Motion
    motion_kmh: float | None
    motion_bearing: float | None
    nearest_radar: str
    nearest_radar_km: float
    coverage: str
    has_radar_coverage: bool

    @property
    def state(self) -> str:
        """Coarse state used as the primary sensor value."""
        if self.raining_now:
            if (
                self.rain_ends_in_minutes is not None
                and self.rain_ends_in_minutes <= ENDING_SOON_MINUTES
            ):
                return "ending_soon"
            return "raining"
        if self.rain_starts_in_minutes is not None:
            return "starting_soon"
        return "dry"

    @property
    def usable_forecast_minutes(self) -> int:
        """How far ahead the radar can actually see from here, right now.

        Every forecast step samples the field *upwind* of the location. Once that
        sample point leaves the area the radars cover there is nothing left to
        extrapolate, so a location near the edge of the composite has a short usable
        horizon whenever the weather is arriving from outside it — and a full one when
        it is arriving from over the radars.
        """
        usable = 0
        for value in self.series_mm_h:
            if value is None:
                break
            usable += 1
        return usable * self.step_minutes

    def series_with_time(self) -> list[dict[str, object]]:
        """The point forecast as ``[{datetime, precipitation}]``, for charts."""
        return [
            {
                "datetime": (
                    self.frame_time + timedelta(minutes=(index + 1) * self.step_minutes)
                ).isoformat(),
                "precipitation": value,
            }
            for index, value in enumerate(self.series_mm_h)
        ]
