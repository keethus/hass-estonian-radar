"""Decoding of ODIM_H5 radar composite files.

Only the small subset of the ODIM specification that the Estonian composite actually
uses is handled here: a single ``dataset1/data1`` image plus the ``where`` group that
georeferences it.
"""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime

import numpy as np

from .models import GridGeometry, RadarFrame

FILENAME_TIME_FORMAT = "%Y%m%d%H%M%S"


class OdimDecodeError(ValueError):
    """Raised when a member of the archive is not a usable composite frame."""


def timestamp_from_filename(name: str) -> datetime:
    """Extract the UTC frame time from a ``comp.<YYYYMMDDhhmmss>.CAP...`` filename."""
    parts = os.path.basename(name).split(".")
    if len(parts) < 2:
        raise OdimDecodeError(f"Unrecognised radar filename: {name}")
    try:
        return datetime.strptime(parts[1], FILENAME_TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError as err:
        raise OdimDecodeError(f"Unrecognised radar filename: {name}") from err


def decode_frame(payload: bytes, filename: str) -> RadarFrame:
    """Decode one ODIM_H5 composite into a rain-rate grid.

    ``undetect`` cells (the radar looked and saw nothing) become ``0.0``; ``nodata``
    cells (the radar could not look at all) become ``NaN`` and stay distinguishable
    from dry weather for the rest of the pipeline.
    """
    import h5py

    with h5py.File(io.BytesIO(payload), "r") as handle:
        try:
            where = handle["where"].attrs
            what = handle["dataset1"]["what"].attrs
            raw = handle["dataset1"]["data1"]["data"][()]
        except KeyError as err:
            raise OdimDecodeError(f"{filename}: unexpected ODIM layout ({err})") from err

        gain = float(what.get("gain", 1.0))
        offset = float(what.get("offset", 0.0))
        nodata = float(what.get("nodata", 65535.0))
        undetect = float(what.get("undetect", 0.0))

        values = raw.astype(np.float32)
        is_nodata = values == nodata
        is_undetect = values == undetect

        grid = values * gain + offset
        grid[is_undetect] = 0.0
        grid[is_nodata] = np.nan

        geometry = _geometry(where)

    return RadarFrame(
        timestamp=timestamp_from_filename(filename),
        filename=filename,
        data=grid,
        geometry=geometry,
    )


def _geometry(where) -> GridGeometry:
    projdef = where.get("projdef")
    if isinstance(projdef, bytes):
        projdef = projdef.decode("utf-8")

    ur_lat = float(where["UR_lat"])
    ll_lon = float(where["LL_lon"])

    return GridGeometry(
        xsize=int(where["xsize"]),
        ysize=int(where["ysize"]),
        ll_lat=float(where["LL_lat"]),
        ll_lon=ll_lon,
        ur_lat=ur_lat,
        ur_lon=float(where["UR_lon"]),
        # Rectangular grids in a projected CRS do not always publish the upper-left
        # corner; for those the north edge shares UR_lat and the west edge LL_lon.
        ul_lat=float(where.get("UL_lat", ur_lat)),
        ul_lon=float(where.get("UL_lon", ll_lon)),
        projdef=projdef,
    )
