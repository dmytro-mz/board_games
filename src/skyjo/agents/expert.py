"""Rule-based expert: the EV heuristic plus five changes, each measured in tournaments vs `ev`.

1. Setup: the two opening cards are revealed in different columns.
2. Pair credit: a column (v, v, hidden) with v > 0 is credited with the chance that another v
   turns up within `pair_horizon` seen cards times the points the clear saves (minus a turn's
   worth, `pair_cost`), instead of a flat `pair_weight * v`. Pairs whose third copies are
   gone get no credit.
3. Discard denial: every action is charged `deny` x the next player's gain from the card it
   leaves on top of the discard pile (taking it vs. drawing blind, in the same EV terms).
4. Finishing: P(doubled) uses the exact distribution of each opponent's round score (hidden
   cards drawn from the unseen multiset, column clears included), shifted by
   `opponent_turn_gain`, instead of a logistic around their mean.
5. Stall breaker: with one face-down card left, each non-finishing move costs `stall_rate`
   per round turn beyond `stall_after`, so two cautious players can't swap cards forever.
   Turns are counted per player (normalised to a 2-player table), so 8 players aren't rushed.

Tables of 3+ players use `multi_reveal_bonus` instead of `reveal_bonus`: with more opponents
someone else ends the round sooner, so face-down cards are a bigger liability.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from skyjo.agents.expected_value import Column, ExpectedValueAgent, _columns, _Context, resolve
from skyjo.game.actions import DRAW_DECK, FLIP_BASE, TAKE_DISCARD, Phase
from skyjo.game.cards import HIDDEN, REMOVED, VALUES, column_of, is_visible
from skyjo.game.observation import Observation

Pmf = list[tuple[int, float]]


def _convolve(a: dict[int, float], b: Iterable[tuple[int, float]]) -> dict[int, float]:
    b = list(b)
    out: dict[int, float] = {}
    for x, px in a.items():
        for y, py in b:
            out[x + y] = out.get(x + y, 0.0) + px * py
    return out


def column_score_pmf(col: Column, probs: Pmf) -> dict[int, float]:
    """Score distribution of a column at the final reveal (hidden cards iid, column clear applied)."""
    if col[0] == REMOVED:
        return {0: 1.0}
    visible = [s for s in col if is_visible(s)]
    k = 3 - len(visible)
    pmf: dict[int, float] = {sum(visible): 1.0}
    for _ in range(k):
        pmf = _convolve(pmf, probs)
    if k == 0:
        return {0: 1.0} if visible[0] == visible[1] == visible[2] else pmf
    clearing = probs if not visible else [(visible[0], dict(probs).get(visible[0], 0.0))]
    if all(v == visible[0] for v in visible):
        for v, pv in clearing:
            mass = pv**k
            if mass:
                pmf[3 * v] -= mass
                pmf[0] = pmf.get(0, 0.0) + mass
    return pmf


class ScoreCdf:
    def __init__(self, pmf: dict[int, float]) -> None:
        self.lo, self.hi = min(pmf), max(pmf)
        acc = 0.0
        self.cdf: list[float] = []
        for x in range(self.lo, self.hi + 1):
            acc += pmf.get(x, 0.0)
            self.cdf.append(acc)

    def at_most(self, t: float) -> float:
        t = math.floor(t)
        if t < self.lo:
            return 0.0
        if t >= self.hi:
            return 1.0
        return self.cdf[t - self.lo]


def board_score_cdf(board: tuple[int, ...], probs: Pmf) -> ScoreCdf:
    pmf: dict[int, float] = {0: 1.0}
    for col in _columns(board):
        pmf = _convolve(pmf, column_score_pmf(col, probs).items())
    return ScoreCdf(pmf)


class _PairContext(_Context):
    __slots__ = ("_col_cache", "_flip_cache", "cost", "horizon")

    def __init__(self, obs: Observation, horizon: float, cost: float) -> None:
        super().__init__(obs, 0.0)
        self.horizon = horizon
        self.cost = cost
        self._col_cache: dict[Column, float] = {}
        self._flip_cache: dict[tuple[Column, int], float] = {}

    def column_cost(self, col: Column) -> float:
        cost = self._col_cache.get(col)
        if cost is None:
            cost = self._col_cache[col] = self._column_cost(col)
        return cost

    def flip_cost(self, col: Column, idx: int) -> float:
        key = (col, idx)
        cost = self._flip_cache.get(key)
        if cost is None:
            cost = self._flip_cache[key] = super().flip_cost(col, idx)
        return cost

    def _column_cost(self, col: Column) -> float:
        visible = [s for s in col if is_visible(s)]
        hidden = sum(1 for s in col if s == HIDDEN)
        cost = sum(visible) + hidden * self.mean
        if len(visible) == 2 and visible[0] == visible[1]:
            v = visible[0]
            pv = self.p.get(v, 0.0)
            cost -= 3 * v * pv
            saving = 2 * v + self.mean - self.cost
            if v > 0 and self.horizon > 0 and saving > 0:
                cost -= (1.0 - (1.0 - pv) ** self.horizon) * saving
        return cost


class ExpertAgent(ExpectedValueAgent):
    name = "expert"

    def __init__(
        self,
        deny: float = 1.5,
        pair_horizon: float = 15.0,
        pair_cost: float = 4.0,
        stall_rate: float = 0.5,
        stall_after: int = 50,
        reveal_bonus: float = 0.75,
        multi_reveal_bonus: float = 1.5,
        opponent_turn_gain: float = 4.0,
        finish_bonus: float = 2.0,
        seed: int | None = None,
    ) -> None:
        super().__init__(
            reveal_bonus=reveal_bonus,
            opponent_turn_gain=opponent_turn_gain,
            finish_bonus=finish_bonus,
            seed=seed,
        )
        self.multi_reveal_bonus = multi_reveal_bonus
        self.deny = deny
        self.pair_horizon = pair_horizon
        self.pair_cost = pair_cost
        self.stall_rate = stall_rate
        self.stall_after = stall_after

    def act(self, obs: Observation, legal: Sequence[int]) -> int:
        if obs.phase == Phase.SETUP:
            return self.rng.choice(self._spread_flips(obs, legal))
        if obs.phase == Phase.CHOOSE_SOURCE and DRAW_DECK not in legal:
            return TAKE_DISCARD
        values = self.action_values(obs, legal)
        if obs.phase == Phase.CHOOSE_SOURCE:
            return TAKE_DISCARD if values[TAKE_DISCARD] >= values[DRAW_DECK] else DRAW_DECK
        return max((v, a) for a, v in values.items())[1]

    @staticmethod
    def _spread_flips(obs: Observation, legal: Sequence[int]) -> list[int]:
        shown = [p for p, s in enumerate(obs.board) if is_visible(s)]
        spread = [a for a in legal if not shown or column_of(a - FLIP_BASE) != column_of(shown[0])]
        return spread or list(legal)

    def action_values(self, obs: Observation, legal: Sequence[int]) -> dict[int, float]:
        """The expert's estimate (in points, higher is better) for every legal action.

        Setup flips get 0 for the preferred (spread) positions and -1 for the rest.
        """
        if obs.phase == Phase.SETUP:
            spread = set(self._spread_flips(obs, legal))
            return {a: 0.0 if a in spread else -1.0 for a in legal}

        final = obs.is_final_turn
        nxt = (obs.player + 1) % obs.n_players
        ctx = _PairContext(obs, 0.0 if final else self.pair_horizon, self.pair_cost)
        board = obs.board
        cols = _columns(board)
        col_costs = [ctx.column_cost(c) for c in cols]
        base_cost = sum(col_costs)
        n_hidden = sum(1 for s in board if s == HIDDEN)
        table_reveal_bonus = self.reveal_bonus if obs.n_players == 2 else self.multi_reveal_bonus
        reveal_bonus = 0.0 if final else table_reveal_bonus
        finishing_possible = n_hidden == 1 and not final
        # stall_after is in 2-player round turns, i.e. a fixed number of own turns at any table size.
        turns = 2 * obs.turn / obs.n_players
        stall = self.stall_rate * max(0, turns - self.stall_after) if finishing_possible else 0.0
        deny = 0.0 if obs.finisher == nxt else self.deny
        gain = self._next_player_gain(obs.boards[nxt], ctx, table_reveal_bonus) if deny else {}
        opp_cdfs: list[ScoreCdf] = []

        def denial(top: Pmf) -> float:
            return deny * sum(p * gain[v] for v, p in top) if deny else 0.0

        def finish_value(outcomes: Pmf | list[tuple[float, float]]) -> float:
            if not opp_cdfs:
                probs = obs.value_probabilities()
                opp_cdfs.extend(board_score_cdf(b, probs) for i, b in enumerate(obs.boards) if i != obs.player)
            total = 0.0
            for score, p in outcomes:
                p_doubled = 0.0
                if score > 0:
                    p_safe = 1.0
                    for cdf in opp_cdfs:
                        p_safe *= 1.0 - cdf.at_most(score + self.opponent_turn_gain)
                    p_doubled = 1.0 - p_safe
                total += p * (-score * (1.0 + p_doubled) + self.finish_bonus * (1.0 - p_doubled))
            return total

        def replace_value(pos: int, card: int) -> float:
            ci = column_of(pos)
            new = list(cols[ci])
            old = new[pos % 3]
            new[pos % 3] = card
            col = resolve((new[0], new[1], new[2]))
            after = base_cost - col_costs[ci] + ctx.column_cost(col)
            if old == HIDDEN and finishing_possible:
                val = finish_value([(after, 1.0)])
            elif old == HIDDEN:
                val = -after + reveal_bonus
            else:
                val = -after - stall
            top = [(card, 1.0)] if col[0] == REMOVED else ctx.probs if old == HIDDEN else [(old, 1.0)]
            return val - denial(top)

        def flip_value(pos: int, hand: int) -> float:
            ci = column_of(pos)
            col = cols[ci]
            if finishing_possible:
                rest = base_cost - col_costs[ci]
                outcomes = []
                for v, pv in ctx.probs:
                    new = list(col)
                    new[pos % 3] = v
                    outcomes.append((rest + ctx.column_cost(resolve((new[0], new[1], new[2]))), pv))
                val = finish_value(outcomes)
            else:
                val = -(base_cost - col_costs[ci] + ctx.flip_cost(col, pos % 3)) + reveal_bonus
            a, b = (col[i] for i in range(3) if i != pos % 3)
            if a == b and is_visible(a):
                pa = ctx.p.get(a, 0.0)
                top = [(a, pa), (hand, 1.0 - pa)]
            else:
                top = [(hand, 1.0)]
            return val - denial(top)

        active = [p for p, s in enumerate(board) if s != REMOVED]
        hidden = [p for p, s in enumerate(board) if s == HIDDEN]

        if obs.phase == Phase.CHOOSE_SOURCE:
            assert obs.discard_top is not None
            values = {TAKE_DISCARD: max(replace_value(p, obs.discard_top) for p in active)}
            if DRAW_DECK in legal:
                draw = 0.0
                for v, prob in ctx.probs:
                    best_flip = max((flip_value(p, v) for p in hidden), default=-math.inf)
                    draw += prob * max(best_flip, max(replace_value(p, v) for p in active))
                values[DRAW_DECK] = draw
            return values

        assert obs.hand is not None
        values = {p: replace_value(p, obs.hand) for p in active}
        if obs.phase == Phase.PLACE_DRAWN:
            values.update({FLIP_BASE + p: flip_value(p, obs.hand) for p in hidden})
        return values

    def _next_player_gain(self, board: tuple[int, ...], ctx: _Context, rb: float) -> dict[int, float]:
        """How much more the next player values taking card v than drawing blind (>= 0)."""
        cols = _columns(board)
        costs = [ctx.column_cost(c) for c in cols]
        base = sum(costs)

        def take(pos: int, card: int) -> float:
            ci = column_of(pos)
            new = list(cols[ci])
            was_hidden = new[pos % 3] == HIDDEN
            new[pos % 3] = card
            after = base - costs[ci] + ctx.column_cost(resolve((new[0], new[1], new[2])))
            return -after + (rb if was_hidden else 0.0)

        active = [p for p, s in enumerate(board) if s != REMOVED]
        best_flip = max(
            (
                -(base - costs[column_of(p)] + ctx.flip_cost(cols[column_of(p)], p % 3)) + rb
                for p, s in enumerate(board)
                if s == HIDDEN
            ),
            default=-math.inf,
        )
        best_take = {v: max(take(p, v) for p in active) for v in VALUES}
        draw = sum(prob * max(best_flip, best_take[v]) for v, prob in ctx.probs)
        return {v: max(0.0, best_take[v] - draw) for v in VALUES}
