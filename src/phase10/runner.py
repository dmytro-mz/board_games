from __future__ import annotations

from collections.abc import Sequence

from phase10.bots.base import Bot
from phase10.game.engine import Game, RulesConfig, Step


def play_game(
    bots: Sequence[Bot], seed: int | None = None, rules: RulesConfig | None = None, max_turns: int = 20_000
) -> Game:
    game = Game(len(bots), seed=seed, rules=rules)
    while game.step != Step.GAME_OVER:
        if game.step == Step.HAND_OVER:
            game.next_hand()
            continue
        seat = game.current
        game.play(seat, bots[seat].act(game.view(seat)))
        if game.turn > max_turns:
            raise RuntimeError("the game did not finish")
    return game
