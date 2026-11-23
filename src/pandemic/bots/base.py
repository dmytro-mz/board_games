from __future__ import annotations

import random
from abc import ABC, abstractmethod

from pandemic.game.actions import Action
from pandemic.game.engine import View


class Bot(ABC):
    """A player that decides from a `View` only (never the full game)."""

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    @abstractmethod
    def act(self, view: View) -> Action:
        """The game waits for this seat (`view.waiting_for == view.seat`): return a legal action."""

    def react(self, view: View) -> Action | None:
        """Someone else's decision is pending: optionally play an event card now."""
        return None
