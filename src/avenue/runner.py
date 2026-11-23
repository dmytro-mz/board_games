"""Play bot-only games (tournaments, tests)."""

from __future__ import annotations

from avenue.bots import Bot
from avenue.game.engine import Game


def play_game(bots: list[Bot], teams: list[int] | None = None, *, advanced: bool = False, seed: int = 0) -> Game:
    game = Game(teams or [0, 1], advanced=advanced, seed=seed, first=seed % 2)
    while game.result is None:
        player = game.waiting()[0]
        game.step(player, bots[player].act(game.redacted(player), player))
    return game
