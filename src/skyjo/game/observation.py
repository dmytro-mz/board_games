"""What a player is allowed to know. Agents only ever see an `Observation`."""

from __future__ import annotations

from dataclasses import dataclass

from skyjo.game.actions import Phase
from skyjo.game.cards import HIDDEN, VALUES, value_index


@dataclass(frozen=True, slots=True)
class Observation:
    player: int
    n_players: int
    phase: Phase
    # boards[i][p]: card value if face up, else HIDDEN / REMOVED. Absolute seat order.
    boards: tuple[tuple[int, ...], ...]
    discard_top: int | None
    hand: int | None  # card held by `player` (only during PLACE_* phases)
    deck_size: int
    # Count of each value (index = value_index(v)) not visible to this player:
    # composition minus face-up board cards, the discard pile and own hand.
    unknown_counts: tuple[int, ...]
    finisher: int | None  # seat that triggered the final turns, if any
    totals: tuple[int, ...]  # cumulative scores before the current round
    round_index: int
    turn: int

    @property
    def board(self) -> tuple[int, ...]:
        return self.boards[self.player]

    @property
    def is_final_turn(self) -> bool:
        return self.finisher is not None

    def expected_unknown_value(self) -> float:
        total = sum(self.unknown_counts)
        if total == 0:
            return 0.0
        return sum(v * c for v, c in zip(VALUES, self.unknown_counts, strict=True)) / total

    def value_probabilities(self) -> list[tuple[int, float]]:
        total = sum(self.unknown_counts)
        if total == 0:
            return [(0, 1.0)]
        return [(v, c / total) for v, c in zip(VALUES, self.unknown_counts, strict=True) if c]

    def hidden_count(self, seat: int) -> int:
        return sum(1 for s in self.boards[seat] if s == HIDDEN)

    def unknown_count_of(self, value: int) -> int:
        return self.unknown_counts[value_index(value)]
