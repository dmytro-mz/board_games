"""The General: determinized two-turn search.

It never sees hidden troops. For each decision it deals several *worlds* consistent with its own view (the
opponent's rack, both reserves and the 4 removed troops shuffled from the troops it hasn't seen), and for each
candidate action:

1. plays the action and finishes its own turn (later effect decisions picked greedily by the evaluator),
2. lets the opponent answer with every first action (deduplicated), keeps the most dangerous ones by a quick
   look, finishes those turns greedily for the opponent, and takes the worst for itself,
3. scores the position reached with `Evaluator` (which also looks one placement further: an immediate win for
   the side to move, or a threat it can't parry).

The candidate with the best average over the worlds is played. Effects that can only help (draws, the magnet,
the sandpit pin) are always taken without searching.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from toybattle.bots.base import Bot
from toybattle.bots.evaluate import WIN, Evaluator, Weights
from toybattle.game.engine import TAKE, Action, Game, Phase, View
from toybattle.game.troops import ARMY, COPIES

Key = tuple[str, int, int, int]


def action_key(a: Action) -> Key:
    """Actions that differ only in which copy of a kind is used are the same move."""
    kind = (a.troop % ARMY) // COPIES if a.troop >= 0 else -1
    return (a.type, kind, a.node, a.to)


def dedup(actions: list[Action] | tuple[Action, ...], prefer: frozenset[int] | set[int] = frozenset()) -> list[Action]:
    """One action per key; for placements prefer a troop the opponent already knows about."""
    out: dict[Key, Action] = {}
    for a in actions:
        k = action_key(a)
        old = out.get(k)
        if old is None or (a.troop in prefer and old.troop not in prefer):
            out[k] = a
    return list(out.values())


class Searcher:
    """The search machinery, shared by the General and the baseline bot."""

    def __init__(self, weights: Weights | None = None) -> None:
        self.eval = Evaluator(weights)

    # -------------------------------------------------------------- one side's turn
    def finish_turn(self, g: Game, side: int, me: int) -> None:
        """Resolve the rest of `side`'s turn: every pending effect is chosen greedily (for `side`)."""
        while g.result is None and g.current == side and g.phase == Phase.EFFECT:
            g.step(side, self.pick_effect(g, side, me))

    def pick_effect(self, g: Game, side: int, me: int) -> Action:
        options = g.legal_actions(side)
        if TAKE in options:
            return TAKE
        if len(options) == 1:
            return options[0]
        best: Action = options[-1]
        best_v = -float("inf")
        sign = 1.0 if side == me else -1.0
        for a in dedup(options, g.known[side]):
            h = g.clone()
            h.step(side, a)
            v = sign * self.eval(h, me)
            if v > best_v:
                best, best_v = a, v
        return best

    def play(self, g: Game, side: int, me: int, action: Action) -> None:
        g.step(side, action)
        self.finish_turn(g, side, me)

    # -------------------------------------------------------------- the following turns
    def value(self, g: Game, me: int, beams: tuple[int, ...]) -> float:
        """Value for `me` at the start of a turn, searching one whole turn per entry of `beams` (each turn looks
        at every first action quickly, then finishes the `beam` most promising ones)."""
        if g.result is not None or not beams:
            return self.eval(g, me)
        side = g.current
        sign = 1.0 if side == me else -1.0
        first = dedup(g.legal_actions(side), g.known[side])
        quick: list[tuple[float, int, Game]] = []
        for i, a in enumerate(first):
            h = g.clone()
            h.step(side, a)
            if h.result is not None and h.result.winner == side:
                return self.eval(h, me)
            quick.append((sign * self.eval(h, me), i, h))
        quick.sort(key=lambda x: (-x[0], x[1]))
        best = -float("inf")
        rest = beams[1:]
        for v, _, h in quick[: beams[0]]:
            if h.phase == Phase.EFFECT:
                self.finish_turn(h, side, me)
                if not rest:
                    v = sign * self.eval(h, me)
            if rest:
                v = sign * self.value(h, me, rest)
            best = max(best, v)
        return sign * best


class GeneralBot(Bot):
    """The strong bot (the only one offered in the lobby)."""

    def __init__(
        self,
        seed: int | None = None,
        *,
        budget: float | None = 1.2,
        worlds: int = 12,
        min_worlds: int = 2,
        top: int = 8,
        weights: Weights | None = None,
        beams: tuple[int, ...] = (5, 3),
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        super().__init__(seed)
        self.search = Searcher(weights)
        self.beams = beams
        self.budget = budget
        self.worlds = worlds
        self.min_worlds = min_worlds
        self.top = top
        self.clock = clock

    def act(self, view: View) -> Action:
        legal = list(view.legal)
        if len(legal) == 1:
            return legal[0]
        if TAKE in legal:
            return TAKE
        me = view.seat
        cands = dedup(legal, view.my_known)
        if len(cands) == 1:
            return cands[0]
        start = self.clock()
        s = self.search
        # quick look on one world: keep the most promising candidates
        w0 = Game.from_view(view, self.rng)
        quick: list[tuple[float, int, Action]] = []
        for i, a in enumerate(cands):
            h = w0.clone()
            s.play(h, me, me, a)
            v = s.eval(h, me)
            if h.result is not None and h.result.winner == me:
                return a
            quick.append((v, -i, a))
        quick.sort(reverse=True)
        keep = [a for _, _, a in quick[: self.top]]
        if len(keep) == 1:
            return keep[0]
        totals = dict.fromkeys(range(len(keep)), 0.0)
        n = 0
        while n < self.worlds:
            world = w0 if n == 0 else Game.from_view(view, self.rng)
            seed = self.rng.random()
            for i, a in enumerate(keep):
                h = world.clone()
                h.rng = random.Random(seed)  # same luck for every candidate in this world
                s.play(h, me, me, a)
                totals[i] += s.value(h, me, self.beams)
            n += 1
            if self.budget is not None and n >= self.min_worlds and self.clock() - start > self.budget:
                break
        best = max(range(len(keep)), key=lambda i: (totals[i], -i))
        return keep[best]


class GreedyBot(Bot):
    """Baseline for tests and tuning (not offered in the lobby): one world, its own turn only."""

    def __init__(self, seed: int | None = None, weights: Weights | None = None) -> None:
        super().__init__(seed)
        self.search = Searcher(weights)

    def act(self, view: View) -> Action:
        legal = list(view.legal)
        if len(legal) == 1:
            return legal[0]
        if TAKE in legal:
            return TAKE
        me = view.seat
        world = Game.from_view(view, self.rng)
        best: Action = legal[0]
        best_v = -float("inf")
        for a in dedup(legal, view.my_known):
            h = world.clone()
            self.search.play(h, me, me, a)
            v = self.search.eval(h, me)
            if v > best_v:
                best, best_v = a, v
        return best


__all__ = ["WIN", "GeneralBot", "GreedyBot", "Searcher", "action_key", "dedup"]
