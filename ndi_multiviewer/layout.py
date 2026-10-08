"""Multiviewer layout model: a grid of tiles plus which NDI source feeds each tile."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass(frozen=True)
class Cell:
    """One tile's position on the grid. Spans let a tile cover several cells."""

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1


@dataclass
class Layout:
    rows: int
    cols: int
    cells: list[Cell]
    name: str = ""
    # tile index -> NDI source name ("MACHINE (Source)"). Missing means no source.
    assignments: dict[int, str] = field(default_factory=dict)

    @property
    def tile_count(self) -> int:
        return len(self.cells)

    def with_cells_of(self, other: "Layout") -> "Layout":
        """Return `other`'s geometry carrying over this layout's source assignments.

        Assignments for tiles that no longer exist are kept, so growing the grid
        back restores them.
        """
        return Layout(other.rows, other.cols, list(other.cells), other.name, dict(self.assignments))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rows": self.rows,
            "cols": self.cols,
            "cells": [asdict(c) for c in self.cells],
            "assignments": {str(k): v for k, v in self.assignments.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Layout":
        layout = cls(
            rows=int(d["rows"]),
            cols=int(d["cols"]),
            cells=[Cell(**c) for c in d["cells"]],
            name=d.get("name", ""),
            assignments={int(k): v for k, v in d.get("assignments", {}).items() if v},
        )
        layout.validate()
        return layout

    def validate(self) -> None:
        if self.rows < 1 or self.cols < 1:
            raise ValueError("grid must be at least 1x1")
        taken: set[tuple[int, int]] = set()
        for c in self.cells:
            if c.row_span < 1 or c.col_span < 1:
                raise ValueError(f"bad span in {c}")
            if c.row < 0 or c.col < 0 or c.row + c.row_span > self.rows or c.col + c.col_span > self.cols:
                raise ValueError(f"{c} is outside a {self.rows}x{self.cols} grid")
            for r in range(c.row, c.row + c.row_span):
                for k in range(c.col, c.col + c.col_span):
                    if (r, k) in taken:
                        raise ValueError(f"{c} overlaps another tile")
                    taken.add((r, k))


def uniform(rows: int, cols: int) -> Layout:
    cells = [Cell(r, c) for r in range(rows) for c in range(cols)]
    return Layout(rows, cols, cells, name=f"{rows}x{cols}")


def big_plus_small(big: int, grid: int) -> Layout:
    """One big tile in the top-left `big`x`big` cells, the rest of a `grid`x`grid` filled with small tiles.

    big_plus_small(2, 3) is the classic "1 + 5"; big_plus_small(3, 4) is "1 + 7".
    """
    cells = [Cell(0, 0, big, big)]
    for r in range(grid):
        for c in range(grid):
            if r < big and c < big:
                continue
            cells.append(Cell(r, c))
    return Layout(grid, grid, cells, name=f"1+{len(cells) - 1}")


def two_plus_small() -> Layout:
    """Two big tiles across the top half of a 4x4, eight small tiles below."""
    cells = [Cell(0, 0, 2, 2), Cell(0, 2, 2, 2)]
    cells += [Cell(r, c) for r in (2, 3) for c in range(4)]
    return Layout(4, 4, cells, name="2+8")


PRESETS: dict[str, Layout] = {
    "1x1": uniform(1, 1),
    "1x2": uniform(1, 2),
    "2x2": uniform(2, 2),
    "3x3": uniform(3, 3),
    "4x4": uniform(4, 4),
    "1+5": big_plus_small(2, 3),
    "1+7": big_plus_small(3, 4),
    "2+8": two_plus_small(),
    "5x5": uniform(5, 5),
}


def save(layout: Layout, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(layout.to_dict(), indent=2))


def load(path: Path) -> Layout:
    return Layout.from_dict(json.loads(path.read_text()))
