"""Bots only see a redacted game, play legal moves, and the search bot beats the heuristic."""

from __future__ import annotations

import random

from avenue.bots import HeuristicBot, RandomBot, SearchBot
from avenue.bots.search import determinize
from avenue.game.cards import DECK_COUNTS, N_AGENTS
from avenue.game.engine import HIDDEN, Game
from avenue.runner import play_game


class Spy:
    """Wraps a bot and checks that what it is given contains no hidden card."""

    def __init__(self, bot) -> None:
        self.bot = bot

    def act(self, view: Game, player: int):
        for p, hand in enumerate(view.hands):
            if p != player:
                assert all(c == HIDDEN for c in hand[len(view.known[p]) :])
        assert all(c == HIDDEN for c in view.deck)
        if view.down is not None and view.down[0] != player:
            assert view.down[1] == HIDDEN
        action = self.bot.act(view, player)
        assert action in view.legal(player)
        return action


def test_bots_get_only_redacted_views():
    for adv in (False, True):
        bots = [Spy(SearchBot(seed=1, budget=0.005, max_iters=4)), Spy(HeuristicBot(seed=2))]
        g = play_game(bots, advanced=adv, seed=4)
        assert g.result is not None


def test_determinize_is_consistent():
    rng = random.Random(0)
    g = Game([0, 1, 0, 1], advanced=True, seed=9, first=0)
    g.step(0, ("discard", g.hands[0][0]))
    for _ in range(30):
        view = g.redacted(0)
        world = determinize(view, 0, rng)
        counts = [0] * N_AGENTS
        for pile in (*world.hands, *world.discards, world.deck):
            for c in pile:
                counts[c] += 1
        assert counts == list(DECK_COUNTS)
        assert world.hands[0] == g.hands[0] and world.discards[0] == g.discards[0]
        assert sorted(world.market_deck) == sorted(g.market_deck)


def test_heuristic_beats_random():
    wins = 0
    for seed in range(40):
        swap = seed % 2
        bots = [RandomBot(seed), HeuristicBot(seed)] if swap else [HeuristicBot(seed), RandomBot(seed)]
        g = play_game(bots, seed=seed)
        wins += (g.result["winner"] == 1) == bool(swap)
    assert wins >= 30
