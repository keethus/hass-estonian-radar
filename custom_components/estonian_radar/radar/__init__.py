"""Home-Assistant-independent radar nowcast pipeline.

Nothing in this package imports Home Assistant, which keeps it unit-testable on its
own and leaves the door open to publishing it as a standalone library.
"""

from .kaia import KaiaClient, KaiaError, KaiaUnavailable, NoRadarData, decode_latest_frames
from .models import (
    GridGeometry,
    LocationForecast,
    Motion,
    NowcastField,
    RadarFrame,
    RainEvent,
)
from .nowcast import build_field, classify_severity, estimate_motion, forecast_location

__all__ = [
    "GridGeometry",
    "KaiaClient",
    "KaiaError",
    "KaiaUnavailable",
    "LocationForecast",
    "Motion",
    "NoRadarData",
    "NowcastField",
    "RadarFrame",
    "RainEvent",
    "build_field",
    "classify_severity",
    "decode_latest_frames",
    "estimate_motion",
    "forecast_location",
]
