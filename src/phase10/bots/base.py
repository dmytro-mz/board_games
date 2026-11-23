from __future__ import annotations

import random
from abc import ABC, abstractmethod

from phase10.game.actions import Action
from phase10.game.engine import View


class Bot(ABC):
    """A player that decides from a `View` only (never the full game)."""

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    @abstractmethod
    def act(self, view: View) -> Action: ...
