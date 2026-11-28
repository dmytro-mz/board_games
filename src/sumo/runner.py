from __future__ import annotations

from sumo.bots import Bot
from sumo.game.engine import Game


def play_game(bots: list[Bot], layout: str = "classic", move_limit: int = 150) -> Game:
    """A bot-only match, start to finish (the move limit keeps two cautious bots from shuffling forever)."""
    game = Game(layout, move_limit=move_limit)
    while not game.over:
        seat = game.current
        game.step(seat, bots[seat].act(game.view()))
    return game
