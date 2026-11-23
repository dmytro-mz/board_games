from __future__ import annotations

from collections.abc import Sequence

from skyjo.agents.base import Agent
from skyjo.game.actions import DRAW_DECK, FLIP_BASE, TAKE_DISCARD, Phase
from skyjo.game.cards import COLS, HIDDEN, column_positions, is_visible
from skyjo.game.observation import Observation


def completing_slot(board: tuple[int, ...], card: int) -> int | None:
    """Slot where `card` would complete a column of three equal cards."""
    for col in range(COLS):
        slots = column_positions(col)
        matches = [p for p in slots if board[p] == card]
        if len(matches) == 2:
            (other,) = (p for p in slots if p not in matches)
            return other
    return None


class GreedyAgent(Agent):
    """Rule-of-thumb player: keep low cards, dump the highest visible card, else flip.

    Mirrors how a casual human plays: no card counting and no endgame awareness.
    """

    name = "greedy"

    def __init__(self, keep_threshold: int = 3, seed: int | None = None) -> None:
        super().__init__(seed)
        self.keep_threshold = keep_threshold

    def act(self, obs: Observation, legal: Sequence[int]) -> int:
        board = obs.board
        if obs.phase == Phase.SETUP:
            return self.rng.choice(legal)
        if obs.phase == Phase.CHOOSE_SOURCE:
            assert obs.discard_top is not None
            if self._worth_keeping(board, obs.discard_top) or DRAW_DECK not in legal:
                return TAKE_DISCARD
            return DRAW_DECK

        assert obs.hand is not None
        card = obs.hand
        hidden = [p for p, v in enumerate(board) if v == HIDDEN]
        if obs.phase == Phase.PLACE_DRAWN and not self._worth_keeping(board, card) and hidden:
            return FLIP_BASE + self.rng.choice(hidden)
        return self._best_slot(board, card, hidden)

    def _worth_keeping(self, board: tuple[int, ...], card: int) -> bool:
        if completing_slot(board, card) is not None or card <= self.keep_threshold:
            return True
        visible = [v for v in board if is_visible(v)]
        return bool(visible) and card < max(visible)

    def _best_slot(self, board: tuple[int, ...], card: int, hidden: list[int]) -> int:
        target = completing_slot(board, card)
        if target is not None:
            return target
        visible = [(v, p) for p, v in enumerate(board) if is_visible(v)]
        highest = max(visible, default=None)
        if highest is not None and (highest[0] > card or not hidden):
            return highest[1]
        return self.rng.choice(hidden)
