"""Thin wrapper over cyndilib for source discovery and per-tile receiving.

Everything here is polled from the Qt main thread. NDI's frame-sync API is
non-blocking (it always hands back the latest frame), so a timer per tile is
enough and keeps the UI code free of locking.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import cyndilib as ndi


@dataclass
class Frame:
    data: np.ndarray  # flat uint8 RGBA, `stride` bytes per row
    width: int
    height: int
    stride: int


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

    def set_source(self, name: str | None) -> None:
        """Choose the source for this tile. It connects as soon as the source is discovered."""
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
        # get_array() copies the frame, so it is safe to keep after the next capture.
        data = self._frame.get_array()
        stride = self._frame.get_line_stride()
        if data.size < stride * h:
            return None
        return Frame(data, w, h, stride)

    def close(self) -> None:
        self._recv.disconnect()
