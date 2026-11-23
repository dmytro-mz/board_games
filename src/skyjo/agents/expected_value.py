"""Card-counting one-step expectimax heuristic.

Board quality is the expected round score of the grid, computed column by column:
hidden cards are worth the mean of the still-unknown cards, and a column holding a
pair plus one hidden card is credited with the exact probability that the hidden
card completes it. Drawing from the deck is valued by enumerating every possible
drawn value. Ending the round is valued with an estimated doubling risk.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from skyjo.agents.base import Agent
from skyjo.game.actions import DRAW_DECK, FLIP_BASE, TAKE_DISCARD, Phase
from skyjo.game.cards import COLS, HIDDEN, REMOVED, column_of, column_positions, is_visible
from skyjo.game.observation import Observation

Column = tuple[int, int, int]


def resolve(col: Column) -> Column:
    a, b, c = col
    if a == b == c and is_visible(a):
        return (REMOVED, REMOVED, REMOVED)
    return col


class _Context:
    """Per-decision constants shared by all evaluations."""

    __slots__ = ("mean", "p", "pair_weight", "probs")

    def __init__(self, obs: Observation, pair_weight: float) -> None:
        self.mean = obs.expected_unknown_value()
        self.probs = obs.value_probabilities()
        self.p = dict(self.probs)
        self.pair_weight = pair_weight

    def column_cost(self, col: Column) -> float:
        visible = [s for s in col if is_visible(s)]
        hidden = sum(1 for s in col if s == HIDDEN)
        cost = sum(visible) + hidden * self.mean
        if len(visible) == 2 and visible[0] == visible[1]:
            v = visible[0]
            if hidden == 1:
                cost -= 3 * v * self.p.get(v, 0.0)
            if v > 0:
                cost -= self.pair_weight * v
        return cost

    def flip_cost(self, col: Column, idx: int) -> float:
        """Expected column cost after revealing the hidden slot `idx`."""
        total = 0.0
        for value, prob in self.probs:
            new = list(col)
            new[idx] = value
            total += prob * self.column_cost(resolve((new[0], new[1], new[2])))
        return total


def _columns(board: tuple[int, ...]) -> list[Column]:
    return [tuple(board[p] for p in column_positions(c)) for c in range(COLS)]  # type: ignore[misc]


class ExpectedValueAgent(Agent):
    name = "ev"

    def __init__(
        self,
        reveal_bonus: float = 0.75,
        pair_weight: float = 0.5,
        opponent_turn_gain: float = 2.0,
        finish_bonus: float = 2.0,
        risk_temperature: float = 2.0,
        seed: int | None = None,
    ) -> None:
        super().__init__(seed)
        self.reveal_bonus = reveal_bonus
        self.pair_weight = pair_weight
        self.opponent_turn_gain = opponent_turn_gain
        self.finish_bonus = finish_bonus
        self.risk_temperature = risk_temperature

    # ------------------------------------------------------------------ policy
    def act(self, obs: Observation, legal: Sequence[int]) -> int:
        if obs.phase == Phase.SETUP:
            return self.rng.choice(legal)

        final = obs.is_final_turn
        ctx = _Context(obs, 0.0 if final else self.pair_weight)
        board = obs.board
        cols = _columns(board)
        col_costs = [ctx.column_cost(c) for c in cols]
        base_cost = sum(col_costs)
        n_hidden = sum(1 for s in board if s == HIDDEN)
        reveal_bonus = 0.0 if final else self.reveal_bonus

        def replace_value(pos: int, card: int) -> float:
            col_idx = column_of(pos)
            new = list(cols[col_idx])
            was_hidden = new[pos % 3] == HIDDEN
            new[pos % 3] = card
            after = base_cost - col_costs[col_idx] + ctx.column_cost(resolve((new[0], new[1], new[2])))
            if was_hidden and n_hidden == 1 and not final:
                return self._finish_value(obs, after)
            return -after + (reveal_bonus if was_hidden else 0.0)

        def flip_value(pos: int) -> float:
            col_idx = column_of(pos)
            after = base_cost - col_costs[col_idx] + ctx.flip_cost(cols[col_idx], pos % 3)
            if n_hidden == 1 and not final:
                return self._finish_value(obs, after)
            return -after + reveal_bonus

        active = [p for p, s in enumerate(board) if s != REMOVED]
        hidden = [p for p, s in enumerate(board) if s == HIDDEN]

        if obs.phase == Phase.CHOOSE_SOURCE:
            assert obs.discard_top is not None
            take = max(replace_value(p, obs.discard_top) for p in active)
            if DRAW_DECK not in legal:
                return TAKE_DISCARD
            best_flip = max((flip_value(p) for p in hidden), default=-math.inf)
            draw = sum(prob * max(best_flip, max(replace_value(p, v) for p in active)) for v, prob in ctx.probs)
            return TAKE_DISCARD if take >= draw else DRAW_DECK

        assert obs.hand is not None
        options: list[tuple[float, int]] = [(replace_value(p, obs.hand), p) for p in active]
        if obs.phase == Phase.PLACE_DRAWN:
            options += [(flip_value(p), FLIP_BASE + p) for p in hidden]
        return max(options)[1]

    # ------------------------------------------------------------------ helpers
    def _finish_value(self, obs: Observation, my_score: float) -> float:
        """Value of revealing my last card, accounting for the doubling rule."""
        mean = obs.expected_unknown_value()
        opp_best = min(
            sum(v for v in b if is_visible(v)) + mean * sum(1 for v in b if v == HIDDEN) - self.opponent_turn_gain
            for i, b in enumerate(obs.boards)
            if i != obs.player
        )
        if my_score <= 0:
            p_doubled = 0.0
        else:
            z = (my_score - opp_best) / self.risk_temperature
            p_doubled = 1.0 / (1.0 + math.exp(-max(min(z, 50.0), -50.0)))
        return -my_score * (1.0 + p_doubled) + self.finish_bonus * (1.0 - p_doubled)
