"""Card values, deck composition and board-slot sentinels."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

MIN_VALUE = -2
MAX_VALUE = 12
VALUES: tuple[int, ...] = tuple(range(MIN_VALUE, MAX_VALUE + 1))
N_VALUES = len(VALUES)  # 15

# Board slot sentinels. They sit just above MAX_VALUE so that `value - MIN_VALUE`
# yields a dense code in [0, 17): 0..14 visible values, 15 hidden, 16 removed.
HIDDEN = MAX_VALUE + 1
REMOVED = MAX_VALUE + 2
N_SLOT_CODES = N_VALUES + 2

ROWS = 3
COLS = 4
N_SLOTS = ROWS * COLS

# Official Skyjo deck: 150 cards.
STANDARD_COMPOSITION: Mapping[int, int] = MappingProxyType(
    {-2: 5, -1: 10, 0: 15, **{v: 10 for v in range(1, MAX_VALUE + 1)}}
)


def value_index(value: int) -> int:
    """Dense index of a card value (or slot sentinel) in [0, N_SLOT_CODES)."""
    return value - MIN_VALUE


def is_visible(slot: int) -> bool:
    return slot <= MAX_VALUE


def column_of(pos: int) -> int:
    """Positions are column-major: column c holds positions 3c, 3c+1, 3c+2."""
    return pos // ROWS


def column_positions(col: int) -> tuple[int, int, int]:
    base = col * ROWS
    return (base, base + 1, base + 2)


def build_deck(composition: Mapping[int, int] = STANDARD_COMPOSITION) -> list[int]:
    return [value for value, count in composition.items() for _ in range(count)]
