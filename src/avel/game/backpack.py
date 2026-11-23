"""Backpack fitting: the backpack is a BACKPACK_W x BACKPACK_H grid, every token covers a rectangle of cells
(rotation allowed) and every coin covers one cell. Tokens cannot be stacked."""

from __future__ import annotations

from functools import lru_cache

from avel.game.model import BACKPACK_H, BACKPACK_W, FOOTPRINT, Kind

Placement = tuple[int, int, int, int]  # x, y, w, h

CELLS = BACKPACK_W * BACKPACK_H


def _shapes(kind: Kind) -> list[tuple[int, int]]:
    w, h = FOOTPRINT[kind]
    return [(w, h)] if w == h else [(w, h), (h, w)]


@lru_cache(maxsize=4096)
def _pack(kinds: tuple[Kind, ...]) -> tuple[Placement, ...] | None:
    """Place every token (largest first) in the grid, or None. Coins fill the remaining cells."""
    grid = [[False] * BACKPACK_W for _ in range(BACKPACK_H)]
    out: list[Placement] = []

    def fits(x: int, y: int, w: int, h: int) -> bool:
        if x + w > BACKPACK_W or y + h > BACKPACK_H:
            return False
        return not any(grid[y + j][x + i] for j in range(h) for i in range(w))

    def mark(x: int, y: int, w: int, h: int, value: bool) -> None:
        for j in range(h):
            for i in range(w):
                grid[y + j][x + i] = value

    def go(i: int) -> bool:
        if i == len(kinds):
            return True
        for w, h in _shapes(kinds[i]):
            for y in range(BACKPACK_H):
                for x in range(BACKPACK_W):
                    if fits(x, y, w, h):
                        mark(x, y, w, h, True)
                        out.append((x, y, w, h))
                        if go(i + 1):
                            return True
                        out.pop()
                        mark(x, y, w, h, False)
        return False

    return tuple(out) if go(0) else None


def _area(kind: Kind) -> int:
    w, h = FOOTPRINT[kind]
    return w * h


def arrange(kinds: list[Kind], coins: int) -> list[Placement] | None:
    """Placements for `kinds` (same order as given) or None if they and the coins don't fit together."""
    used = sum(_area(k) for k in kinds)
    if used + coins > CELLS:
        return None
    order = sorted(range(len(kinds)), key=lambda i: (-_area(kinds[i]), kinds[i].value))
    packed = _pack(tuple(kinds[i] for i in order))
    if packed is None:
        return None
    result: list[Placement] = [(0, 0, 0, 0)] * len(kinds)
    for slot, i in enumerate(order):
        result[i] = packed[slot]
    return result


def fits(kinds: list[Kind], coins: int) -> bool:
    return arrange(kinds, coins) is not None


def free_cells(kinds: list[Kind]) -> int:
    """How many coins still fit next to these tokens (0 if the tokens alone don't fit)."""
    if arrange(kinds, 0) is None:
        return 0
    return CELLS - sum(_area(k) for k in kinds)


def coin_cells(placements: list[Placement], coins: int) -> list[tuple[int, int]]:
    """Grid cells for the coins: the free cells, row by row."""
    taken = {(x + i, y + j) for x, y, w, h in placements for j in range(h) for i in range(w)}
    free = [(x, y) for y in range(BACKPACK_H) for x in range(BACKPACK_W) if (x, y) not in taken]
    return free[:coins]
