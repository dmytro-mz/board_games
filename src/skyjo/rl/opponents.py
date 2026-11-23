"""Opponent mixture for training: fixed heuristics plus frozen self-play snapshots."""

from __future__ import annotations

import random
from collections.abc import Mapping

from skyjo.agents import make_agent
from skyjo.agents.base import Agent
from skyjo.rl.encoding import OBS_VERSION
from skyjo.rl.policy_agent import Layers, PolicyAgent

SELF = "self"


class OpponentPool:
    """Samples an opponent per seat per episode.

    `weights` maps agent specs (``"ev"``, ``"greedy"``...) or ``"self"`` to sampling
    weights. ``"self"`` picks a uniformly random stored snapshot; until the first
    snapshot arrives its weight is redistributed to the other entries.
    """

    def __init__(
        self,
        weights: Mapping[str, float],
        n_players: int,
        max_snapshots: int = 20,
        sample_snapshots: bool = True,
        seed: int | None = None,
        obs_version: int = OBS_VERSION,
    ) -> None:
        self.obs_version = obs_version
        self.rng = random.Random(seed)
        self.weights = {k: float(v) for k, v in weights.items() if v > 0}
        if not self.weights:
            raise ValueError("opponent pool needs at least one positive weight")
        self.n_players = n_players
        self.max_snapshots = max_snapshots
        self.sample_snapshots = sample_snapshots
        self.fixed: dict[str, Agent] = {
            spec: make_agent(spec, seed=self.rng.randrange(2**31)) for spec in self.weights if spec != SELF
        }
        self.snapshots: list[PolicyAgent] = []

    def add_snapshot(self, layers: Layers, prior_scale: float | None = None) -> None:
        agent = PolicyAgent(
            layers,
            self.n_players,
            greedy=not self.sample_snapshots,
            seed=self.rng.randrange(2**31),
            obs_version=self.obs_version,
            prior_scale=prior_scale,
        )
        agent.name = "self"
        self.snapshots.append(agent)
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots.pop(0)

    def sample(self) -> Agent:
        keys = [k for k in self.weights if k != SELF or self.snapshots]
        if not keys:
            raise RuntimeError("only 'self' opponents configured but no snapshot was added")
        key = self.rng.choices(keys, weights=[self.weights[k] for k in keys])[0]
        if key == SELF:
            return self.rng.choice(self.snapshots)
        return self.fixed[key]
