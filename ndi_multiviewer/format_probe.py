"""Finds each source's real resolution without stalling the UI.

Tiles receive each sender's preview stream, which is scaled down (a 1080p source
arrives as 640x360), so the full resolution has to be read from the
full-quality stream. Connecting to and disconnecting from an NDI stream blocks
for a few hundred milliseconds while holding Python's GIL, which froze the whole
window when done in-process. So it happens in a separate helper process, which
connects briefly to one source at a time and reports the size back.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import time

PROBE_INTERVAL_S = 30.0
FIND_TIMEOUT_S = 5.0
FRAME_TIMEOUT_S = 5.0


def _worker(requests: mp.Queue, results: mp.Queue) -> None:
    import cyndilib as ndi

    finder = ndi.Finder()
    finder.open()
    parent = mp.parent_process()
    try:
        while parent is None or parent.is_alive():
            try:
                name = requests.get(timeout=1.0)
            except queue.Empty:
                continue
            if name is None:
                break
            results.put((name, _probe_one(ndi, finder, name)))
    finally:
        finder.close()


def _probe_one(ndi, finder, name: str) -> tuple[int, int] | None:
    deadline = time.monotonic() + FIND_TIMEOUT_S
    while name not in finder.get_source_names():
        if time.monotonic() > deadline:
            return None
        finder.wait_for_sources(0.5)
        finder.update_sources()
    recv = ndi.Receiver(color_format=ndi.RecvColorFormat.fastest, bandwidth=ndi.RecvBandwidth.highest)
    frame = ndi.VideoFrameSync()
    recv.frame_sync.set_video_frame(frame)
    recv.set_source(finder.get_source(name))
    try:
        deadline = time.monotonic() + FRAME_TIMEOUT_S
        while time.monotonic() < deadline:
            recv.frame_sync.capture_video()
            if frame.xres and frame.yres:
                return frame.xres, frame.yres
            time.sleep(0.02)
        return None
    finally:
        recv.disconnect()


class FormatProber:
    """Parent-side handle: ask for sources to be checked, read back their sizes."""

    def __init__(self) -> None:
        ctx = mp.get_context("spawn")  # fork is unsafe with Qt and NDI threads
        self._requests: mp.Queue = ctx.Queue()
        self._results: mp.Queue = ctx.Queue()
        self._process = ctx.Process(target=_worker, args=(self._requests, self._results), daemon=True)
        self._process.start()
        self.sizes: dict[str, tuple[int, int]] = {}
        self._last_requested: dict[str, float] = {}

    def is_alive(self) -> bool:
        return self._process.is_alive()

    def want(self, names: set[str]) -> None:
        """Keep these sources' sizes fresh. Call regularly (e.g. once a second)."""
        now = time.monotonic()
        for name in names:
            if now - self._last_requested.get(name, -PROBE_INTERVAL_S) >= PROBE_INTERVAL_S:
                self._last_requested[name] = now
                self._requests.put(name)
        while True:
            try:
                name, size = self._results.get_nowait()
            except queue.Empty:
                break
            if size:
                self.sizes[name] = size
            else:
                # Couldn't read it this time; try again sooner than a full interval.
                self._last_requested[name] = now - PROBE_INTERVAL_S + 5.0

    def close(self) -> None:
        try:
            self._requests.put(None)
            self._process.join(timeout=2.0)
        finally:
            if self._process.is_alive():
                self._process.terminate()
