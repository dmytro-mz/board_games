from __future__ import annotations

from collections.abc import Sequence

from pandemic.bots.base import Bot
from pandemic.game.engine import Game, IllegalMove, RulesConfig, Step


def reactions(game: Game, bots: Sequence[Bot | None], open_hands: bool = True) -> bool:
    """Let the seats that aren't being waited for play an event card; True if one did."""
    waiting = game.waiting_for()
    if waiting is None or game.step not in (Step.EPIDEMIC, Step.INFECT) or game.forecast is not None:
        return False
    for i in range(1, game.n):
        seat = (waiting + i) % game.n
        bot = bots[seat]
        if bot is None:
            continue
        action = bot.react(game.view(seat, open_hands))
        if action is None:
            continue
        try:
            game.play(seat, action)
        except IllegalMove:
            continue
        return True
    return False


def play_game(
    bots: Sequence[Bot],
    seed: int | None = None,
    rules: RulesConfig | None = None,
    open_hands: bool = True,
    max_moves: int = 20_000,
) -> Game:
    game = Game(len(bots), seed=seed, rules=rules)
    game.track_undo = False
    moves = 0
    while game.result is None:
        moves += 1
        if moves > max_moves:
            raise RuntimeError("the game did not finish")
        if reactions(game, bots, open_hands):
            continue
        seat = game.waiting_for()
        assert seat is not None
        game.play(seat, bots[seat].act(game.view(seat, open_hands)))
    return game
