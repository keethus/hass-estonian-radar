"""Client for the Estonian Environment Agency open data repository (KAIA).

The repository exposes radar products as ZIP archives selected by a JSON filter. The
filter matches on the item title, so asking for ``comp.<YYYYMMDDHH>`` returns just the
twelve frames of one hour instead of the whole day — which by late evening would be
hundreds of megabytes fetched every few minutes.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    KAIA_CONTENT_TYPE,
    KAIA_PAGE_SIZE,
    KAIA_PHENOMENON,
    KAIA_PRODUCT_MARKER,
    KAIA_ZIP_URL,
    PAST_FRAME_COUNT,
)
from .models import RadarFrame
from .odim import OdimDecodeError, decode_frame, timestamp_from_filename

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 120
HOUR_FORMAT = "%Y%m%d%H"


class KaiaError(Exception):
    """Base error for problems talking to the KAIA repository."""


class KaiaUnavailable(KaiaError):
    """The repository could not be reached or returned something unusable."""


class NoRadarData(KaiaError):
    """The repository responded, but held no usable composite frames."""


def build_filter(hour_prefix: str) -> dict[str, Any]:
    """Build the KAIA query for one hour of multi-radar composite CAP products."""
    return {
        "filter": {
            "and": {
                "children": [
                    {"isEqual": {"field": "$contentType", "value": KAIA_CONTENT_TYPE}},
                    {"isEqual": {"field": "Phenomenon", "value": KAIA_PHENOMENON}},
                    {"contains": {"field": "RMTitle", "value": f"comp.{hour_prefix}"}},
                    {"contains": {"field": "RMTitle", "value": KAIA_PRODUCT_MARKER}},
                ]
            }
        },
        "pageSize": KAIA_PAGE_SIZE,
    }


class KaiaClient:
    """Fetches radar archives. Networking only — decoding happens elsewhere."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def async_fetch_archives(
        self, *, frames_needed: int = PAST_FRAME_COUNT, now: datetime | None = None
    ) -> list[bytes]:
        """Download enough hourly archives to cover ``frames_needed`` frames.

        Normally one hour is plenty. Just after the top of the hour it is not, so the
        previous hour is fetched as well.
        """
        moment = now or datetime.now(UTC)
        archives: list[bytes] = []
        collected = 0

        for offset in (0, 1):
            prefix = (moment - timedelta(hours=offset)).strftime(HOUR_FORMAT)
            try:
                payload = await self._async_fetch_hour(prefix)
            except NoRadarData:
                _LOGGER.debug("No composite frames for hour %s", prefix)
                continue

            archives.append(payload)
            collected += _count_members(payload)
            if collected >= frames_needed:
                break

        if not archives:
            raise NoRadarData("KAIA returned no composite frames for the last two hours")
        return archives

    async def _async_fetch_hour(self, hour_prefix: str) -> bytes:
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                async with self._session.post(
                    KAIA_ZIP_URL,
                    json=build_filter(hour_prefix),
                    timeout=ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
                ) as response:
                    response.raise_for_status()

                    content_type = response.headers.get("Content-Type", "")
                    if "zip" not in content_type.lower():
                        raise KaiaUnavailable(
                            f"KAIA returned {content_type!r} instead of a ZIP archive"
                        )

                    payload = await response.read()

                if _count_members(payload) == 0:
                    raise NoRadarData(f"Empty archive for hour {hour_prefix}")
                return payload

            except NoRadarData:
                raise
            except (ClientError, TimeoutError, zipfile.BadZipFile) as err:
                last_error = err
                if attempt < 2:
                    await asyncio.sleep(2 + attempt * 2)

        raise KaiaUnavailable(f"Could not download radar data: {last_error}")


def decode_latest_frames(
    archives: list[bytes], count: int = PAST_FRAME_COUNT
) -> list[RadarFrame]:
    """Decode the ``count`` most recent composite frames across all archives.

    Blocking and CPU-bound — call this from an executor, never from the event loop.
    """
    candidates: list[tuple[datetime, int, str]] = []
    # Each archive is opened once and kept open: the day's composites can be tens of
    # megabytes, and reopening them per member would re-read the central directory.
    handles = [zipfile.ZipFile(io.BytesIO(payload)) for payload in archives]

    try:
        for index, handle in enumerate(handles):
            for name in handle.namelist():
                if not _is_composite_member(name):
                    continue
                try:
                    candidates.append((timestamp_from_filename(name), index, name))
                except OdimDecodeError:
                    _LOGGER.debug("Skipping unrecognised archive member %s", name)

        if not candidates:
            raise NoRadarData("No composite CAP files found in the downloaded archives")

        candidates.sort(key=lambda item: item[0])
        frames = [
            decode_frame(handles[archive_index].read(name), name)
            for _, archive_index, name in candidates[-count:]
        ]
    finally:
        for handle in handles:
            handle.close()

    if len(frames) < 2:
        raise NoRadarData(f"Need at least two frames to compute motion, decoded {len(frames)}")
    return frames


def _is_composite_member(name: str) -> bool:
    basename = os.path.basename(name).lower()
    return (
        basename.startswith("comp.")
        and KAIA_PRODUCT_MARKER.lower() in basename
        and basename.endswith(".h5")
    )


def _count_members(payload: bytes) -> int:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return sum(1 for name in archive.namelist() if _is_composite_member(name))
    except zipfile.BadZipFile:
        return 0
