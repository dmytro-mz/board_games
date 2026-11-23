from __future__ import annotations

from collections.abc import Sequence

from skyjo.agents.base import Agent
from skyjo.game.observation import Observation


class RandomAgent(Agent):
    """Uniform over legal actions. Lower bound for any sensible strategy."""

    name = "random"

    def act(self, obs: Observation, legal: Sequence[int]) -> int:
        return self.rng.choice(legal)
