"""The hexagonal ring: 61 cells, their neighbours, names and the opening layouts.

Cells use axial coordinates (q, r) with |q|, |r|, |q + r| <= 4, r growing downwards (pointy-top hexagons). Black's
home rows are at the bottom (rows A, B, C), White's at the top. A cell's name is its row letter (A at the bottom
… I at the top) and its diagonal number (1 … 9 from the left), e.g. "E5" is the centre.
"""

from __future__ import annotations

from dataclasses import dataclass

RADIUS = 4
# The six directions, counter-clockwise from east; `(d + 3) % 6` is the opposite one.
DIRS: tuple[tuple[int, int], ...] = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
DIR_NAMES = ("E", "NE", "NW", "W", "SW", "SE")
ROWS = "ABCDEFGHI"

CELLS: tuple[tuple[int, int], ...] = tuple(
    (q, r)
    for r in range(-RADIUS, RADIUS + 1)
    for q in range(-RADIUS, RADIUS + 1)
    if abs(q) <= RADIUS and abs(r) <= RADIUS and abs(q + r) <= RADIUS
)
N_CELLS = len(CELLS)  # 61
INDEX: dict[tuple[int, int], int] = {c: i for i, c in enumerate(CELLS)}


def _neighbour(i: int, d: int) -> int:
    q, r = CELLS[i]
    dq, dr = DIRS[d]
    return INDEX.get((q + dq, r + dr), -1)


# NEIGHBOR[cell][dir] -> cell, or -1 off the board.
NEIGHBOR: tuple[tuple[int, ...], ...] = tuple(tuple(_neighbour(i, d) for d in range(6)) for i in range(N_CELLS))
# Rings: 0 for the centre … 4 for the edge.
RING: tuple[int, ...] = tuple(max(abs(q), abs(r), abs(q + r)) for q, r in CELLS)


def name(cell: int) -> str:
    q, r = CELLS[cell]
    return f"{ROWS[RADIUS - r]}{q + RADIUS + 1}"


def cell(label: str) -> int:
    """The cell called e.g. "E5"."""
    row = ROWS.index(label[0].upper())
    r = RADIUS - row
    q = int(label[1:]) - RADIUS - 1
    return INDEX[(q, r)]


def cells(labels: str) -> list[int]:
    return [cell(x) for x in labels.split()]


def _daisy(centre: str) -> list[int]:
    c = cell(centre)
    return [c, *(n for n in NEIGHBOR[c] if n >= 0)]


@dataclass(frozen=True)
class Layout:
    key: str
    name: str
    blurb: str
    black: tuple[int, ...]
    white: tuple[int, ...]

    def public(self) -> dict[str, object]:
        return {"key": self.key, "name": self.name, "blurb": self.blurb, "black": self.black, "white": self.white}


LAYOUTS: dict[str, Layout] = {
    lay.key: lay
    for lay in (
        Layout(
            "classic",
            "Classic",
            "Each team packed on its own side. Slow and careful: a good first game.",
            tuple(cells("A1 A2 A3 A4 A5 B1 B2 B3 B4 B5 B6 C3 C4 C5")),
            tuple(cells("I5 I6 I7 I8 I9 H4 H5 H6 H7 H8 H9 G5 G6 G7")),
        ),
        Layout(
            "daisy",
            "Twin flowers",
            "Two flowers of seven per team, face to face with the rival's. Contact at once.",
            tuple(_daisy("B2") + _daisy("H8")),
            tuple(_daisy("B5") + _daisy("H5")),
        ),
        Layout(
            "wide",
            "Wide flowers",
            "The flowers start a row further in, closer to the middle. Sharp and fast.",
            tuple(_daisy("C2") + _daisy("G8")),
            tuple(_daisy("C6") + _daisy("G4")),
        ),
    )
}
DEFAULT_LAYOUT = "classic"


def public_board() -> dict[str, object]:
    """The geometry the client draws with."""
    return {
        "cells": [list(c) for c in CELLS],
        "names": [name(i) for i in range(N_CELLS)],
        "dirs": [list(d) for d in DIRS],
    }
