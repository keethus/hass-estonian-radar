"""Tests for ODIM_H5 decoding and archive selection."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

import numpy as np
import pytest
from radar.kaia import (
    NoRadarData,
    build_filter,
    decode_latest_frames,
)
from radar.odim import (
    OdimDecodeError,
    decode_frame,
    timestamp_from_filename,
)

h5py = pytest.importorskip("h5py")


def make_odim_file(raw: np.ndarray, *, gain=0.01, offset=0.0, nodata=255, undetect=0) -> bytes:
    """Build a minimal ODIM_H5 composite in memory."""
    buffer = io.BytesIO()
    with h5py.File(buffer, "w") as handle:
        where = handle.create_group("where")
        where.attrs["xsize"] = raw.shape[1]
        where.attrs["ysize"] = raw.shape[0]
        where.attrs["LL_lat"] = 56.0
        where.attrs["LL_lon"] = 21.0
        where.attrs["UR_lat"] = 60.0
        where.attrs["UR_lon"] = 29.0
        where.attrs["projdef"] = np.bytes_(b"+proj=longlat +datum=WGS84 +no_defs")

        dataset = handle.create_group("dataset1")
        what = dataset.create_group("what")
        what.attrs["gain"] = gain
        what.attrs["offset"] = offset
        what.attrs["nodata"] = nodata
        what.attrs["undetect"] = undetect
        dataset.create_group("data1").create_dataset("data", data=raw)
    return buffer.getvalue()


def make_archive(names_and_payloads: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in names_and_payloads:
            archive.writestr(name, payload)
    return buffer.getvalue()


class TestTimestampParsing:
    def test_parses_utc_timestamp(self) -> None:
        result = timestamp_from_filename("comp.20260807160500.CAP.h5")

        assert result == datetime(2026, 8, 7, 16, 5, 0, tzinfo=UTC)

    def test_ignores_directory_prefix(self) -> None:
        result = timestamp_from_filename("radar/2026/comp.20260807160500.CAP.h5")

        assert result.hour == 16

    @pytest.mark.parametrize("name", ["nonsense", "comp.notadate.CAP.h5", "single"])
    def test_rejects_garbage(self, name: str) -> None:
        with pytest.raises(OdimDecodeError):
            timestamp_from_filename(name)


class TestDecodeFrame:
    def test_applies_gain_and_offset(self) -> None:
        raw = np.full((8, 8), 250, dtype=np.uint8)
        payload = make_odim_file(raw, gain=0.02, offset=1.0, nodata=255, undetect=0)

        frame = decode_frame(payload, "comp.20260807160500.CAP.h5")

        assert frame.data[0, 0] == pytest.approx(250 * 0.02 + 1.0)
        assert frame.geometry.xsize == 8

    def test_undetect_becomes_zero_and_nodata_becomes_nan(self) -> None:
        raw = np.full((4, 4), 100, dtype=np.uint8)
        raw[0, 0] = 0  # undetect: radar looked, saw nothing
        raw[1, 1] = 255  # nodata: radar could not look
        payload = make_odim_file(raw)

        frame = decode_frame(payload, "comp.20260807160500.CAP.h5")

        assert frame.data[0, 0] == 0.0
        assert np.isnan(frame.data[1, 1])
        assert not np.isnan(frame.data[2, 2])

    def test_rejects_unexpected_layout(self) -> None:
        buffer = io.BytesIO()
        with h5py.File(buffer, "w") as handle:
            handle.create_group("where")

        with pytest.raises(OdimDecodeError, match="unexpected ODIM layout"):
            decode_frame(buffer.getvalue(), "comp.20260807160500.CAP.h5")


class TestArchiveSelection:
    def _payload(self) -> bytes:
        return make_odim_file(np.full((8, 8), 100, dtype=np.uint8))

    def test_picks_the_most_recent_frames_across_archives(self) -> None:
        payload = self._payload()
        older = make_archive(
            [
                ("comp.20260807190000.CAP.h5", payload),
                ("comp.20260807190500.CAP.h5", payload),
            ]
        )
        newer = make_archive(
            [
                ("comp.20260807200000.CAP.h5", payload),
                ("comp.20260807200500.CAP.h5", payload),
                ("comp.20260807201000.CAP.h5", payload),
            ]
        )

        frames = decode_latest_frames([older, newer], count=3)

        assert [frame.timestamp.strftime("%H%M") for frame in frames] == [
            "2000",
            "2005",
            "2010",
        ]

    def test_ignores_unrelated_members(self) -> None:
        payload = self._payload()
        archive = make_archive(
            [
                ("readme.txt", b"not radar"),
                ("comp.20260807160000.PPI.h5", payload),  # wrong product
                ("comp.20260807160000.CAP.h5", payload),
                ("comp.20260807160500.CAP.h5", payload),
            ]
        )

        frames = decode_latest_frames([archive], count=6)

        assert len(frames) == 2

    def test_empty_archive_raises(self) -> None:
        with pytest.raises(NoRadarData):
            decode_latest_frames([make_archive([("readme.txt", b"x")])])

    def test_single_frame_is_not_enough_for_motion(self) -> None:
        archive = make_archive([("comp.20260807160000.CAP.h5", self._payload())])

        with pytest.raises(NoRadarData, match="at least two frames"):
            decode_latest_frames([archive])


class TestFilter:
    def test_targets_one_hour_of_composites(self) -> None:
        query = build_filter("2026080716")
        conditions = query["filter"]["and"]["children"]
        titles = [item["contains"]["value"] for item in conditions if "contains" in item]

        assert "comp.2026080716" in titles
        assert ".CAP." in titles
