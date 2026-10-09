"""Thin wrapper over cyndilib for source discovery and per-tile receiving.

Everything here is polled from the Qt main thread. NDI's frame-sync API is
non-blocking (it always hands back the latest frame), so a timer per tile is
enough and keeps the UI code free of locking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import cyndilib as ndi


@dataclass
class Frame:
    data: np.ndarray  # flat uint8 RGBA, `stride` bytes per row
    width: int
    height: int
    stride: int


@dataclass
class VideoFormat:
    """What the sender reports: full resolution, frame rate and scan type."""

    width: int
    height: int
    frame_rate: Fraction
    progressive: bool

    def label(self) -> str:
        """Broadcast-style label, e.g. '1920×1080p59.94' or '1920×1080i50'."""
        # NDI reports frames per second; interlaced formats are conventionally named by field rate.
        rate = float(self.frame_rate) * (1 if self.progressive else 2)
        rate_text = f"{rate:.2f}".rstrip("0").rstrip(".")
        return f"{self.width}×{self.height}{'p' if self.progressive else 'i'}{rate_text}"


PROBE_INTERVAL_S = 10.0
PROBE_TIMEOUT_S = 5.0


class SourceFinder:
    """Keeps an up-to-date list of NDI source names on the network."""

    def __init__(self) -> None:
        self._finder = ndi.Finder()
        self._finder.open()

    def poll(self) -> list[str]:
        self._finder.wait_for_sources(0)
        self._finder.update_sources()
        return sorted(self._finder.get_source_names())

    def get_source(self, name: str):
        return self._finder.get_source(name)

    def close(self) -> None:
        self._finder.close()


class TileReceiver:
    """One NDI receiver feeding one tile.

    `bandwidth="lowest"` asks senders for their preview stream, which is what
    hardware multiviewers do and keeps CPU and network load low with many tiles.
    """

    def __init__(self, finder: SourceFinder, bandwidth: str = "lowest") -> None:
        self._finder = finder
        bw = ndi.RecvBandwidth.lowest if bandwidth == "lowest" else ndi.RecvBandwidth.highest
        self._recv = ndi.Receiver(color_format=ndi.RecvColorFormat.RGBX_RGBA, bandwidth=bw)
        self._frame = ndi.VideoFrameSync()
        self._recv.frame_sync.set_video_frame(self._frame)
        self.source_name: str | None = None
        self._connected_to: str | None = None
        self._last_timestamp = None
        self._full_bandwidth = bw == ndi.RecvBandwidth.highest
        self.format: VideoFormat | None = None
        # In preview mode the frames we receive are scaled down (e.g. 640x360 for a
        # 1080p source), so a short-lived full-quality receiver periodically checks
        # the sender's real resolution.
        self._probe: ndi.Receiver | None = None
        self._probe_frame: ndi.VideoFrameSync | None = None
        self._probe_started = 0.0
        self._next_probe_at = 0.0
        self._full_size: tuple[int, int] | None = None

    def set_source(self, name: str | None) -> None:
        """Choose the source for this tile. It connects as soon as the source is discovered."""
        if name != self.source_name:
            self._reset_format()
        self.source_name = name
        if self._connected_to is not None and name != self._connected_to:
            self._recv.disconnect()
            self._connected_to = None

    def ensure_connected(self, available: set[str]) -> None:
        name = self.source_name
        if name and name != self._connected_to and name in available:
            self._recv.set_source(self._finder.get_source(name))
            self._connected_to = name

    @property
    def connected(self) -> bool:
        return self._connected_to is not None and self._recv.is_connected()

    def latest_frame(self) -> Frame | None:
        """Return the newest RGBA frame, or None if there is no new frame since the last call."""
        if self._connected_to is None:
            return None
        self._recv.frame_sync.capture_video()
        w, h = self._frame.xres, self._frame.yres
        if not w or not h:
            return None
        # Frame sync repeats the last frame forever; only hand back new ones so the
        # UI can tell a frozen source from a live one, and skip needless copies.
        ts = self._frame.get_timestamp_posix()
        if ts == self._last_timestamp:
            return None
        self._last_timestamp = ts
        self._update_format(w, h)
        # get_array() copies the frame, so it is safe to keep after the next capture.
        data = self._frame.get_array()
        stride = self._frame.get_line_stride()
        if data.size < stride * h:
            return None
        return Frame(data, w, h, stride)

    def _update_format(self, w: int, h: int) -> None:
        if self._full_bandwidth:
            self._full_size = (w, h)
        else:
            self._probe_step()
        if self._full_size is None:
            self.format = None
            return
        fps = self._frame.get_frame_rate()
        self.format = VideoFormat(*self._full_size, Fraction(fps.numerator, fps.denominator), bool(self._frame.is_progressive))

    def _probe_step(self) -> None:
        now = time.monotonic()
        if self._probe is None:
            if now >= self._next_probe_at and self._connected_to:
                self._probe = ndi.Receiver(
                    color_format=ndi.RecvColorFormat.fastest,
                    bandwidth=ndi.RecvBandwidth.highest,
                    recv_name="multiviewer-format-probe",
                )
                self._probe_frame = ndi.VideoFrameSync()
                self._probe.frame_sync.set_video_frame(self._probe_frame)
                self._probe.set_source(self._finder.get_source(self._connected_to))
                self._probe_started = now
            return
        self._probe.frame_sync.capture_video()
        if self._probe_frame.xres and self._probe_frame.yres:
            self._full_size = (self._probe_frame.xres, self._probe_frame.yres)
            self._close_probe(now + PROBE_INTERVAL_S)
        elif now - self._probe_started > PROBE_TIMEOUT_S:
            self._close_probe(now + PROBE_INTERVAL_S)

    def _close_probe(self, next_at: float) -> None:
        if self._probe is not None:
            self._probe.disconnect()
        self._probe = None
        self._probe_frame = None
        self._next_probe_at = next_at

    def _reset_format(self) -> None:
        self._close_probe(0.0)
        self._full_size = None
        self.format = None

    def close(self) -> None:
        self._close_probe(0.0)
        self._recv.disconnect()
