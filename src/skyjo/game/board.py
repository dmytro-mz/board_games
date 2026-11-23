"""A single player's 3x4 grid."""

from __future__ import annotations

from skyjo.game.cards import COLS, HIDDEN, N_SLOTS, REMOVED, column_positions

FACE_DOWN = 0
FACE_UP = 1
GONE = 2


class Board:
    __slots__ = ("status", "values")

    def __init__(self, values: list[int]) -> None:
        if len(values) != N_SLOTS:
            raise ValueError(f"a board needs {N_SLOTS} cards")
        self.values = list(values)
        self.status = [FACE_DOWN] * N_SLOTS

    def view(self) -> tuple[int, ...]:
        """Public view: card value if face up, else HIDDEN / REMOVED sentinel."""
        return tuple(
            v if s == FACE_UP else (HIDDEN if s == FACE_DOWN else REMOVED)
            for v, s in zip(self.values, self.status, strict=True)
        )

    def hidden_positions(self) -> list[int]:
        return [p for p, s in enumerate(self.status) if s == FACE_DOWN]

    def active_positions(self) -> list[int]:
        return [p for p, s in enumerate(self.status) if s != GONE]

    def all_revealed(self) -> bool:
        return FACE_DOWN not in self.status

    def reveal(self, pos: int) -> None:
        if self.status[pos] != FACE_DOWN:
            raise ValueError(f"slot {pos} is not face down")
        self.status[pos] = FACE_UP

    def put(self, pos: int, card: int) -> int:
        """Place `card` face up at `pos`; return the card that was there."""
        if self.status[pos] == GONE:
            raise ValueError(f"slot {pos} was removed")
        old = self.values[pos]
        self.values[pos] = card
        self.status[pos] = FACE_UP
        return old

    def clear_column_if_matching(self, col: int) -> list[int]:
        """Remove the column if all three cards are face up and equal."""
        a, b, c = column_positions(col)
        st, vs = self.status, self.values
        if st[a] == st[b] == st[c] == FACE_UP and vs[a] == vs[b] == vs[c]:
            st[a] = st[b] = st[c] = GONE
            return [vs[a], vs[b], vs[c]]
        return []

    def reveal_all(self) -> None:
        self.status = [GONE if s == GONE else FACE_UP for s in self.status]

    def clear_all_matching_columns(self) -> list[int]:
        removed: list[int] = []
        for col in range(COLS):
            removed.extend(self.clear_column_if_matching(col))
        return removed

    def score(self) -> int:
        """Sum of all non-removed cards (face down ones included)."""
        return sum(v for v, s in zip(self.values, self.status, strict=True) if s != GONE)

    def visible_score(self) -> int:
        return sum(v for v, s in zip(self.values, self.status, strict=True) if s == FACE_UP)
