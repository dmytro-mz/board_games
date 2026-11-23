"""Rule configuration. Defaults follow the official Magilano rulebook."""

from __future__ import annotations

from dataclasses import dataclass, field

from skyjo.game.cards import STANDARD_COMPOSITION


@dataclass(frozen=True, slots=True)
class RulesConfig:
    n_players: int = 2
    setup_flips: int = 2
    end_score: int = 100
    # The round finisher's positive score is doubled unless strictly lowest.
    double_finisher_penalty: bool = True
    double_on_tie: bool = True
    # Three equal face-up cards in a column are discarded.
    column_clear: bool = True
    # Safety valves against degenerate policies that never reveal cards.
    max_turns_per_round: int = 400
    max_rounds: int = 60
    composition: dict[int, int] = field(default_factory=lambda: dict(STANDARD_COMPOSITION))

    def __post_init__(self) -> None:
        if not 2 <= self.n_players <= 8:
            raise ValueError(f"n_players must be in [2, 8], got {self.n_players}")
        if not 0 <= self.setup_flips <= 12:
            raise ValueError("setup_flips must be in [0, 12]")
        needed = 12 * self.n_players + 2
        if sum(self.composition.values()) < needed:
            raise ValueError(f"deck too small for {self.n_players} players")
