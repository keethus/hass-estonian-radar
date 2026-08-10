"""Shared fixtures.

These tests exercise the ``radar`` package only, which has no Home Assistant imports,
so they run with nothing but numpy, h5py and pytest installed.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

# Import the pipeline package directly: it has no Home Assistant dependencies, so the
# tests stay fast and do not need a Home Assistant install.
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "estonian_radar")
)

from radar.models import GridGeometry, RadarFrame

GRID_SIZE = 240
BASE_TIME = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)


@pytest.fixture
def geometry() -> GridGeometry:
    """A plain lat/lon grid, which keeps pixel maths analytically checkable."""
    return GridGeometry(
        xsize=GRID_SIZE,
        ysize=GRID_SIZE,
        ll_lat=56.0,
        ll_lon=21.0,
        ur_lat=60.0,
        ur_lon=29.0,
        ul_lat=60.0,
        ul_lon=21.0,
        projdef=None,
    )


def rain_blob(
    size: int = GRID_SIZE,
    centre: tuple[int, int] = (120, 120),
    radius: float = 18.0,
    peak: float = 6.0,
) -> np.ndarray:
    """A single smooth precipitation cell, in mm/h."""
    yy, xx = np.mgrid[0:size, 0:size]
    cy, cx = centre
    field = peak * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2.0 * radius**2)))
    field[field < 0.01] = 0.0
    return field.astype(np.float32)


def make_frames(
    geometry: GridGeometry,
    motion: tuple[int, int],
    count: int = 6,
    centre: tuple[int, int] = (120, 120),
    **blob_kwargs,
) -> list[RadarFrame]:
    """A sequence of frames containing one blob translating at a constant rate."""
    frames = []
    for index in range(count):
        offset = (centre[0] + motion[0] * index, centre[1] + motion[1] * index)
        frames.append(
            RadarFrame(
                timestamp=BASE_TIME + timedelta(minutes=5 * index),
                filename=f"comp.{(BASE_TIME + timedelta(minutes=5 * index)):%Y%m%d%H%M%S}.CAP.h5",
                data=rain_blob(geometry.ysize, offset, **blob_kwargs),
                geometry=geometry,
            )
        )
    return frames
