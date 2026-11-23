"""Agent interface. Agents must be picklable so tournaments can fan out to processes."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Sequence

from skyjo.game.observation import Observation


class Agent(ABC):
    name: str = "agent"

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def seed(self, seed: int | None) -> None:
        self.rng.seed(seed)

    @abstractmethod
    def act(self, obs: Observation, legal: Sequence[int]) -> int:
        """Return one action id from `legal`."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"
