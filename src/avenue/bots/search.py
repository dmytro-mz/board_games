"""The strong bot: determinised Monte Carlo search over the information a player really has.

The bot receives `Game.redacted(player)` — other hands, the deck order, others' discards, a face-down card it
didn't play and the black market deck are all HIDDEN. For every iteration it samples a full game consistent with
what it saw (`determinize`), tries each legal action in that same sample, plays a few turns on with the heuristic
policy (which itself never peeks) and scores the end position. When the bot plays its two cards, both possible
recruit answers are simulated and combined robustly: a model of the opponent's choice, blended with the worst
case, so a bluff that only works against a careless opponent isn't overrated.
"""

from __future__ import annotations

import random
import time

from avenue.bots.heuristic import (
    down_weights,
    heuristic_action,
    recruit_scores,
    sigmoid,
    split_value,
    static_eval,
    unseen,
)
from avenue.game.cards import DECK_COUNTS, N_AGENTS, N_MARKET
from avenue.game.engine import HIDDEN, Action, Game, Phase


def _sample(weights: list[float], rng: random.Random) -> int:
    total = sum(weights)
    r = rng.random() * total
    for i, w in enumerate(weights):
        r -= w
        if r < 0:
            return i
    return max(range(len(weights)), key=weights.__getitem__)


def determinize(view: Game, player: int, rng: random.Random, down_belief: list[float] | None = None) -> Game:
    """Fill every HIDDEN card of a redacted game with a random assignment consistent with what is known."""
    g = view.clone()
    pool = list(DECK_COUNTS)
    for t in g.tableau:
        for c in range(N_AGENTS):
            pool[c] -= t[c]
    for hand in g.hands:
        for c in hand:
            if c != HIDDEN:
                pool[c] -= 1
    for d in g.discards:
        for c in d:
            if c != HIDDEN:
                pool[c] -= 1
    if g.up is not None:
        pool[g.up[1]] -= 1
    if g.down is not None and g.down[1] != HIDDEN:
        pool[g.down[1]] -= 1
    # Known cards in other hands can be wrong (discarded face down since) — never let the pool go negative.
    for c in range(N_AGENTS):
        if pool[c] < 0:
            for hand in g.hands:
                while pool[c] < 0 and c in hand and hand is not g.hands[player]:
                    hand[hand.index(c)] = HIDDEN
                    pool[c] += 1
            pool[c] = max(0, pool[c])
    if g.down is not None and g.down[1] == HIDDEN:
        weights = [float(n) for n in pool]
        if down_belief is not None:
            weights = [w * b for w, b in zip(weights, down_belief, strict=True)]
            if sum(weights) <= 0:
                weights = [float(n) for n in pool]
        card = _sample(weights, rng)
        pool[card] -= 1
        g.down = (g.down[0], card)
    cards = [c for c in range(N_AGENTS) for _ in range(pool[c])]
    rng.shuffle(cards)
    for hand in g.hands:
        for i, c in enumerate(hand):
            if c == HIDDEN:
                hand[i] = cards.pop()
    for d in g.discards:
        for i, c in enumerate(d):
            if c == HIDDEN:
                d[i] = cards.pop()
    g.deck = [cards.pop() if c == HIDDEN else c for c in g.deck]
    if g.market_deck:
        seen = set(g.supply) | set(g.owned[0]) | set(g.owned[1]) | set(g.market_discard)
        if g.choice is not None:
            seen.add(g.choice["card"])
        rest = [m for m in range(N_MARKET) if m not in seen]
        rng.shuffle(rest)
        g.market_deck = rest[: len(g.market_deck)]
    g.rng = random.Random(rng.random())
    return g


class SearchBot:
    key = "mastermind"
    label = "Mastermind"
    description = "Reads the table, counts cards and bluffs back. Plays to win."

    def __init__(
        self,
        seed: int | None = None,
        budget: float = 1.0,
        max_iters: int = 400,
        horizon: int = 3,
        robust: float = 0.35,
        noise: float = 0.03,
        discard_cost: float = 0.04,
    ) -> None:
        self.rng = random.Random(seed)
        self.budget = budget
        self.max_iters = max_iters
        self.horizon = horizon
        self.robust = robust
        self.noise = noise
        self.discard_cost = discard_cost  # a discard is a scarce resource the short playouts don't value

    # ------------------------------------------------------------------ playouts
    def _rollout(self, g: Game, side: int, end_turn: int) -> float:
        rng = self.rng
        while g.result is None:
            if g.turn > end_turn and g.phase == Phase.PLAY:
                break
            waiting = g.waiting()
            if not waiting:
                break
            p = waiting[0]
            g.step(p, heuristic_action(g, p, rng, self.noise))
        if g.result is not None:
            return 1.0 if g.result["winner"] == side else 0.0
        return static_eval(
            g, side, g.distance(side), g.tableau[side], g.tableau[1 - side], g.pos[side], g.pos[1 - side]
        )

    # ------------------------------------------------------------------ decision
    def act(self, view: Game, player: int) -> Action:
        legal = view.legal(player)
        if len(legal) == 1:
            return legal[0]
        side = view.side_of[player]
        if view.phase == Phase.PLAY:
            legal = self._prune_plays(view, player, legal)
            if len(legal) == 1:
                return legal[0]
        belief = None
        if view.phase == Phase.RECRUIT and view.up is not None and view.down is not None and view.down[1] == HIDDEN:
            belief = self._down_belief(view, player)
        branch = view.phase == Phase.PLAY and view.solo(side)
        end_turn = view.turn + self.horizon
        totals = {a: 0.0 for a in legal}
        split = {a: [0.0, 0.0, 0.0] for a in legal if branch and a[0] == "play"}  # v_up, v_down, p(take up)
        iters = 0
        deadline = time.perf_counter() + self.budget
        while iters < self.max_iters and (iters < 12 or time.perf_counter() < deadline):
            world = determinize(view, player, self.rng, belief)
            for a in legal:
                g = world.clone()
                g.step(player, a)
                if a in split and g.phase == Phase.RECRUIT:
                    recruiter = g.sides[1 - side][0]
                    up_s, down_s = recruit_scores(g, recruiter)
                    p_up = sigmoid((up_s - down_s) * 25)
                    g2 = g.clone()
                    g.step(recruiter, ("recruit", 0))
                    g2.step(recruiter, ("recruit", 1))
                    acc = split[a]
                    acc[0] += self._rollout(g, side, end_turn)
                    acc[1] += self._rollout(g2, side, end_turn)
                    acc[2] += p_up
                else:
                    totals[a] += self._rollout(g, side, end_turn)
            iters += 1
        for a, (vu, vd, pu) in split.items():
            vu, vd, pu = vu / iters, vd / iters, pu / iters
            pu = min(0.85, max(0.15, pu))
            totals[a] = (self.robust * min(vu, vd) + (1 - self.robust) * (pu * vu + (1 - pu) * vd)) * iters
        for a in legal:
            if a[0] == "discard":
                left = view.discards_left[player]
                totals[a] -= self.discard_cost * (1.5 if left <= 2 else 1.0) * iters
        return max(legal, key=lambda a: totals[a])

    def _prune_plays(self, view: Game, player: int, legal: list[Action]) -> list[Action]:
        """Keep the most promising plays (by the quick heuristic) so the search budget goes further."""
        plays = [a for a in legal if a[0] == "play"]
        others = [a for a in legal if a[0] != "play"]
        if len(plays) <= 8:
            return legal
        from avenue.bots.heuristic import play_scores

        scores = play_scores(view, player, plays)
        ranked = sorted(range(len(plays)), key=lambda i: -scores[i])
        return [plays[i] for i in ranked[:8]] + others

    def _down_belief(self, view: Game, player: int) -> list[float]:
        """How likely each face-down card is, assuming the opponent played sensibly (a soft best response)."""
        assert view.up is not None
        up = view.up[1]
        pool = unseen(view, player)
        base = down_weights(view, player, up, pool)
        active = view.active
        belief = [0.0] * N_AGENTS
        for c in range(N_AGENTS):
            if not base[c]:
                continue
            v_up = split_value(view, active, c, up)  # recruiter takes the face-up card
            v_down = split_value(view, active, up, c)
            quality = 0.55 * min(v_up, v_down) + 0.45 * (v_up + v_down) / 2
            # soft: a sensible player prefers good pairs, but not exclusively (and rarely repeats the face-up name)
            belief[c] = (base[c] / max(1, pool[c])) * (0.35 + quality)
        return belief
