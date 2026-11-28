from __future__ import annotations

from toybattle.bots import Bot
from toybattle.game.engine import Game, Phase


def play_game(
    bots: list[Bot],
    terrain: str = "rug",
    special: bool = True,
    seed: int | None = None,
    starter: int | None = None,
    max_steps: int = 2000,
) -> Game:
    """A bot-only match, start to finish. Bots only ever get their own `View`."""
    game = Game(terrain, special=special, seed=seed, starter=starter)
    steps = 0
    while game.phase != Phase.OVER:
        seat = game.current
        game.step(seat, bots[seat].act(game.view(seat)))
        steps += 1
        if steps > max_steps:
            raise RuntimeError("game did not finish")
    return game
