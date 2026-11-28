from __future__ import annotations

import random
from abc import ABC, abstractmethod

from sumo.game.engine import Move, View


class Bot(ABC):
    """A player that decides from a `View` (the whole position: this game has no hidden information)."""

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    @abstractmethod
    def act(self, view: View) -> Move: ...


class RandomBot(Bot):
    def act(self, view: View) -> Move:
        from sumo.game.engine import gen_moves

        return Move.of(self.rng.choice(gen_moves(list(view.cells), view.side)))
