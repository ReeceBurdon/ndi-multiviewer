"""Qt user interface: the tile grid, the per-tile source picker, and layout controls."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QRect, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QImage, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSpinBox,
    QToolBar,
    QWidget,
)

from . import layout as layouts
from .layout import Layout
from .ndi_backend import Frame, SourceFinder, TileReceiver

FRAME_INTERVAL_MS = 33  # ~30 fps redraw
DISCOVERY_INTERVAL_MS = 1000
NO_SIGNAL_AFTER_S = 2.0


def default_layout_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation) or str(Path.home() / ".ndi-multiviewer")
    return Path(base) / "layout.json"


class TileWidget(QWidget):
    """Draws one input: the video, its tile number and source name, and status text."""

    source_chosen = Signal(int, object)  # tile index, source name or None
    solo_toggled = Signal(int)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.source_name: str | None = None
        self.available: list[str] = []
        self.show_labels = True
        self._image: QImage | None = None
        self._frame: Frame | None = None  # keeps the pixel buffer alive for _image
        self._last_frame_at = 0.0
        self.setMinimumSize(80, 45)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to choose a source, double-click to solo")

    def set_frame(self, frame: Frame | None) -> None:
        if frame is not None:
            self._frame = frame
            self._image = QImage(frame.data.data, frame.width, frame.height, frame.stride, QImage.Format_RGBA8888)
            self._last_frame_at = time.monotonic()
        self.update()

    def clear_frame(self) -> None:
        self._frame = None
        self._image = None
        self.update()

    def status_text(self) -> str:
        if not self.source_name:
            return "NO SOURCE"
        if self.source_name not in self.available:
            return "SOURCE OFFLINE"
        if self._image is None:
            return "CONNECTING"
        if time.monotonic() - self._last_frame_at > NO_SIGNAL_AFTER_S:
            return "NO SIGNAL"
        return ""

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(12, 12, 12))
        status = self.status_text()

        if self._image is not None and not status:
            target = self._fit(self._image.width(), self._image.height())
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(target, self._image)
        elif status:
            p.setPen(QColor(150, 150, 150))
            f = QFont(self.font())
            f.setPointSizeF(max(8.0, self.height() / 18))
            f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, status)

        if self.show_labels:
            label = f"{self.index + 1}  {display_name(self.source_name) if self.source_name else ''}".rstrip()
            f = QFont(self.font())
            f.setPointSizeF(max(8.0, min(14.0, self.height() / 22)))
            p.setFont(f)
            h = p.fontMetrics().height() + 6
            bar = QRect(0, self.height() - h, self.width(), h)
            p.fillRect(bar, QColor(0, 0, 0, 170))
            p.setPen(QColor(235, 235, 235))
            p.drawText(bar.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, label)

        p.setPen(QColor(60, 60, 60))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _fit(self, w: int, h: int) -> QRect:
        """Largest rect with the frame's aspect ratio that fits the tile, centred."""
        scale = min(self.width() / w, self.height() / h)
        tw, th = int(w * scale), int(h * scale)
        return QRect((self.width() - tw) // 2, (self.height() - th) // 2, tw, th)

    def mousePressEvent(self, event) -> None:
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._show_source_menu(event.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, _event) -> None:
        self.solo_toggled.emit(self.index)

    def _show_source_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addSection(f"Input {self.index + 1}")
        none = menu.addAction("None")
        none.setCheckable(True)
        none.setChecked(self.source_name is None)
        none.triggered.connect(lambda: self.source_chosen.emit(self.index, None))
        names = list(self.available)
        if self.source_name and self.source_name not in names:
            names.append(self.source_name)  # keep an offline assignment visible
        if not names:
            menu.addAction("No NDI sources found").setEnabled(False)
        for name in names:
            text = name if name in self.available else f"{name} (offline)"
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(name == self.source_name)
            act.triggered.connect(lambda _=False, n=name: self.source_chosen.emit(self.index, n))
        menu.exec(pos)


def display_name(ndi_name: str) -> str:
    """NDI names look like 'MACHINE (Source)'; show 'Source  ·  MACHINE'."""
    if ndi_name.endswith(")") and " (" in ndi_name:
        machine, _, rest = ndi_name.partition(" (")
        return f"{rest[:-1]}  ·  {machine}"
    return ndi_name


class MainWindow(QMainWindow):
    def __init__(self, layout_path: Path | None = None, bandwidth: str = "lowest") -> None:
        super().__init__()
        self.setWindowTitle("NDI Multiviewer")
        self.resize(1280, 760)
        self.layout_path = layout_path or default_layout_path()
        self.bandwidth = bandwidth

        self.finder = SourceFinder()
        self.available: list[str] = []
        self.receivers: dict[int, TileReceiver] = {}
        self.tiles: list[TileWidget] = []
        self.solo: int | None = None

        self.layout_model = self._load_initial_layout()

        self.grid_host = QWidget()
        self.grid_host.setStyleSheet("background: #050505;")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(2)
        self.setCentralWidget(self.grid_host)

        self.source_count = QLabel()
        self.statusBar().addPermanentWidget(self.source_count)
        self._build_toolbar()
        self._rebuild_tiles()

        self.discovery_timer = QTimer(self, interval=DISCOVERY_INTERVAL_MS, timeout=self._poll_sources)
        self.discovery_timer.start()
        self.frame_timer = QTimer(self, interval=FRAME_INTERVAL_MS, timeout=self._pull_frames)
        self.frame_timer.start()
        self._poll_sources()

    # ---- layout persistence -------------------------------------------------

    def _load_initial_layout(self) -> Layout:
        if self.layout_path.exists():
            try:
                return layouts.load(self.layout_path)
            except (ValueError, KeyError, TypeError) as e:
                print(f"Ignoring unreadable layout {self.layout_path}: {e}")
        return Layout.from_dict(layouts.PRESETS["2x2"].to_dict())

    def _autosave(self) -> None:
        try:
            layouts.save(self.layout_model, self.layout_path)
        except OSError as e:
            self.statusBar().showMessage(f"Could not save layout: {e}", 5000)

    # ---- toolbar ------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = QToolBar("Layout")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.toolbar = tb

        tb.addWidget(QLabel(" Layout "))
        self.preset_box = QComboBox()
        self.preset_box.addItems(list(layouts.PRESETS) + ["Custom"])
        self.preset_box.textActivated.connect(self._on_preset)
        tb.addWidget(self.preset_box)

        tb.addWidget(QLabel("   Rows "))
        self.rows_spin = QSpinBox(minimum=1, maximum=8)
        tb.addWidget(self.rows_spin)
        tb.addWidget(QLabel(" Cols "))
        self.cols_spin = QSpinBox(minimum=1, maximum=8)
        tb.addWidget(self.cols_spin)
        self.rows_spin.valueChanged.connect(self._on_custom_grid)
        self.cols_spin.valueChanged.connect(self._on_custom_grid)
        tb.addSeparator()

        self.labels_action = QAction("Labels", self, checkable=True, checked=True)
        self.labels_action.toggled.connect(self._on_labels)
        tb.addAction(self.labels_action)

        clear = QAction("Clear all", self)
        clear.triggered.connect(self._clear_all)
        tb.addAction(clear)
        tb.addSeparator()

        save = QAction("Save layout…", self, shortcut=QKeySequence.Save)
        save.triggered.connect(self._save_as)
        tb.addAction(save)
        load = QAction("Load layout…", self, shortcut=QKeySequence.Open)
        load.triggered.connect(self._load_from)
        tb.addAction(load)
        tb.addSeparator()

        full = QAction("Fullscreen", self, shortcut=QKeySequence("F11"), checkable=True)
        full.toggled.connect(self._on_fullscreen)
        tb.addAction(full)
        self.fullscreen_action = full
        self.addAction(full)  # keeps F11 working while the toolbar is hidden

        esc = QAction(self, shortcut=QKeySequence("Escape"))
        esc.triggered.connect(lambda: self.fullscreen_action.setChecked(False))
        self.addAction(esc)

        self._sync_toolbar()

    def _sync_toolbar(self) -> None:
        for w in (self.preset_box, self.rows_spin, self.cols_spin):
            w.blockSignals(True)
        name = self.layout_model.name
        self.preset_box.setCurrentText(name if name in layouts.PRESETS else "Custom")
        self.rows_spin.setValue(self.layout_model.rows)
        self.cols_spin.setValue(self.layout_model.cols)
        for w in (self.preset_box, self.rows_spin, self.cols_spin):
            w.blockSignals(False)

    def _on_preset(self, name: str) -> None:
        if name in layouts.PRESETS:
            self.set_layout(self.layout_model.with_cells_of(layouts.PRESETS[name]))
        else:
            self._on_custom_grid()

    def _on_custom_grid(self) -> None:
        geometry = layouts.uniform(self.rows_spin.value(), self.cols_spin.value())
        self.set_layout(self.layout_model.with_cells_of(geometry))

    def _on_labels(self, on: bool) -> None:
        for t in self.tiles:
            t.show_labels = on
            t.update()

    def _on_fullscreen(self, on: bool) -> None:
        self.toolbar.setVisible(not on)
        self.statusBar().setVisible(not on)
        self.showFullScreen() if on else self.showNormal()

    def _clear_all(self) -> None:
        for i in range(self.layout_model.tile_count):
            self.assign(i, None)

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save layout", str(self.layout_path.parent), "Layout (*.json)")
        if path:
            layouts.save(self.layout_model, Path(path))

    def _load_from(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load layout", str(self.layout_path.parent), "Layout (*.json)")
        if not path:
            return
        try:
            self.set_layout(layouts.load(Path(path)))
        except (OSError, ValueError, KeyError, TypeError) as e:
            QMessageBox.warning(self, "Load layout", f"Could not load {path}:\n{e}")

    # ---- tiles and receivers ------------------------------------------------

    def set_layout(self, new_layout: Layout) -> None:
        self.layout_model = new_layout
        self.solo = None
        self._rebuild_tiles()
        self._sync_toolbar()
        self._autosave()

    def assign(self, index: int, source: str | None) -> None:
        if source:
            self.layout_model.assignments[index] = source
        else:
            self.layout_model.assignments.pop(index, None)
        if index < len(self.tiles):
            tile = self.tiles[index]
            tile.source_name = source
            tile.clear_frame()
            self.receivers[index].set_source(source)
            self.receivers[index].ensure_connected(set(self.available))
        self._autosave()

    def _rebuild_tiles(self) -> None:
        for t in self.tiles:
            self.grid.removeWidget(t)
            t.hide()  # otherwise it lingers behind the new tiles until deleted
            t.deleteLater()
        self.tiles.clear()
        for r in range(self.grid.rowCount()):
            self.grid.setRowStretch(r, 0)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 0)

        # Receivers for tiles that no longer exist are closed; the rest are reused
        # so changing layout does not drop connections.
        count = self.layout_model.tile_count
        for i in [i for i in self.receivers if i >= count]:
            self.receivers.pop(i).close()

        for i, cell in enumerate(self.layout_model.cells):
            tile = TileWidget(i)
            tile.available = self.available
            tile.show_labels = self.labels_action.isChecked()
            tile.source_name = self.layout_model.assignments.get(i)
            tile.source_chosen.connect(self.assign)
            tile.solo_toggled.connect(self._toggle_solo)
            self.grid.addWidget(tile, cell.row, cell.col, cell.row_span, cell.col_span)
            self.tiles.append(tile)

            recv = self.receivers.get(i)
            if recv is None:
                recv = self.receivers[i] = TileReceiver(self.finder, self.bandwidth)
            recv.set_source(tile.source_name)
            recv.ensure_connected(set(self.available))

        for r in range(self.layout_model.rows):
            self.grid.setRowStretch(r, 1)
        for c in range(self.layout_model.cols):
            self.grid.setColumnStretch(c, 1)
        self.statusBar().showMessage(f"{self.layout_model.name or 'Custom'}: {count} inputs", 3000)

    def _toggle_solo(self, index: int) -> None:
        self.solo = None if self.solo == index else index
        for i, t in enumerate(self.tiles):
            t.setVisible(self.solo is None or i == self.solo)
        if self.solo is not None:
            # A hidden-sibling tile keeps its grid cell; span it over the whole grid while soloed.
            self.grid.addWidget(self.tiles[index], 0, 0, self.layout_model.rows, self.layout_model.cols)
        else:
            cell = self.layout_model.cells[index]
            self.grid.addWidget(self.tiles[index], cell.row, cell.col, cell.row_span, cell.col_span)

    def _poll_sources(self) -> None:
        names = self.finder.poll()
        if names != self.available:
            self.available[:] = names  # tiles share this list object
            for t in self.tiles:
                t.update()
        avail = set(names)
        for recv in self.receivers.values():
            recv.ensure_connected(avail)
        self.source_count.setText(f"{len(names)} NDI source(s) on the network  ")

    def _pull_frames(self) -> None:
        for i, tile in enumerate(self.tiles):
            if not tile.isVisible():
                continue
            recv = self.receivers.get(i)
            frame = recv.latest_frame() if recv else None
            tile.set_frame(frame)

    def closeEvent(self, event) -> None:
        self.frame_timer.stop()
        self.discovery_timer.stop()
        self._autosave()
        for r in self.receivers.values():
            r.close()
        self.finder.close()
        super().closeEvent(event)
