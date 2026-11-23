"""Single-learner Skyjo environment. The learner sits at a random seat each episode;
other seats are filled from an `OpponentPool` and play inside `step`.

Gymnasium-compatible (exposes `action_masks()` for sb3-contrib's MaskablePPO).
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import gymnasium as gym
import numpy as np

from skyjo.agents.base import Agent
from skyjo.game.actions import N_ACTIONS
from skyjo.game.config import RulesConfig
from skyjo.game.engine import Game, RoundResult
from skyjo.rl.encoding import OBS_VERSION, ObsEncoder, legal_mask
from skyjo.rl.opponents import OpponentPool

RewardMode = Literal["relative", "relative_best", "score"]
EpisodeMode = Literal["round", "game"]


@dataclass
class EnvConfig:
    n_players: int = 2
    # Sampling weights per table size, drawn every episode (overrides n_players; obs v4+).
    table_sizes: dict[int, float] | None = None
    episode: EpisodeMode = "round"
    reward: RewardMode = "relative"
    reward_scale: float = 10.0
    # game mode only: +bonus on a win, -bonus / (n - 1) otherwise (zero mean at a fair win share)
    win_bonus: float = 0.0
    opponents: dict[str, float] = field(default_factory=lambda: {"greedy": 0.2, "ev": 0.4, "self": 0.4})
    max_snapshots: int = 20
    obs_version: int = OBS_VERSION

    def __post_init__(self) -> None:
        if self.table_sizes is not None:
            self.table_sizes = {int(k): float(v) for k, v in self.table_sizes.items() if v > 0}
            if not self.table_sizes:
                raise ValueError("env.table_sizes needs at least one positive weight")
            if self.obs_version < 4 and set(self.table_sizes) != {self.n_players}:
                raise ValueError(f"obs version {self.obs_version} is fixed to {self.n_players} players")
            for n in self.table_sizes:
                RulesConfig(n_players=n)  # validates the range

    def rules(self, n_players: int | None = None) -> RulesConfig:
        return RulesConfig(n_players=n_players or self.n_players)


class SkyjoEnv(gym.Env[np.ndarray, int]):
    metadata: Mapping[str, Any] = {"render_modes": []}

    def __init__(self, config: EnvConfig | None = None, seed: int | None = None) -> None:
        self.config = config or EnvConfig()
        sizes = self.config.table_sizes or {self.config.n_players: 1.0}
        self._sizes, self._size_weights = list(sizes), list(sizes.values())
        self._rules = {n: self.config.rules(n) for n in self._sizes}
        self.encoder = ObsEncoder(self.config.n_players, self.config.obs_version)
        self.pool = OpponentPool(
            self.config.opponents,
            self.config.n_players,
            max_snapshots=self.config.max_snapshots,
            seed=seed,
            obs_version=self.config.obs_version,
        )
        self.rng = random.Random(seed)
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, shape=(self.encoder.dim,), dtype=np.float32)
        self.action_space = gym.spaces.Discrete(N_ACTIONS)
        self.game: Game | None = None
        self.seat = 0
        self.opponents: dict[int, Agent] = {}
        self._episode_return = 0.0
        self._episode_len = 0
        self._rounds: list[RoundResult] = []

    # ------------------------------------------------------------------ gym api
    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if seed is not None:
            self.rng.seed(seed)
        n = self._sizes[0] if len(self._sizes) == 1 else self.rng.choices(self._sizes, self._size_weights)[0]
        self.game = Game(self._rules[n], seed=self.rng.randrange(2**63))
        self.seat = self.rng.randrange(n)
        self.opponents = {s: self.pool.sample() for s in range(n) if s != self.seat}
        self._episode_return = 0.0
        self._episode_len = 0
        self._rounds = []
        reward, done = self._advance()
        assert not done and reward == 0.0
        return self._obs(), {}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        game = self.game
        assert game is not None and game.current_player == self.seat
        result = game.step(int(action))
        reward = self._on_round_end(result) if result else 0.0
        done = self._is_done()
        if not done:
            r, done = self._advance()
            reward += r
        self._episode_return += reward
        self._episode_len += 1
        info: dict[str, Any] = {}
        if done:
            info["episode"] = self._episode_info()
            return np.zeros(self.encoder.dim, dtype=np.float32), reward, True, False, info
        return self._obs(), reward, False, False, info

    def action_masks(self) -> np.ndarray:
        assert self.game is not None
        return legal_mask(self.game.legal_actions())

    # ------------------------------------------------------------------ internals
    def _obs(self) -> np.ndarray:
        assert self.game is not None
        return self.encoder.encode(self.game.observe(self.seat))

    def _is_done(self) -> bool:
        assert self.game is not None
        return self.game.is_over or (self.config.episode == "round" and bool(self._rounds))

    def _advance(self) -> tuple[float, bool]:
        """Let opponents play until it is the learner's turn or the episode ends."""
        game = self.game
        assert game is not None
        reward = 0.0
        while not self._is_done() and game.current_player != self.seat:
            seat = game.current_player
            action = self.opponents[seat].act(game.observe(seat), game.legal_actions())
            result = game.step(action)
            if result:
                reward += self._on_round_end(result)
        return reward, self._is_done()

    def _on_round_end(self, result: RoundResult) -> float:
        assert self.game is not None
        self._rounds.append(result)
        cfg = self.config
        mine = result.scores[self.seat]
        others = [s for i, s in enumerate(result.scores) if i != self.seat]
        if cfg.reward == "score":
            r = -mine
        elif cfg.reward == "relative_best":
            r = min(others) - mine
        else:
            r = sum(others) / len(others) - mine
        reward = r / cfg.reward_scale
        if cfg.episode == "game" and self.game.is_over and cfg.win_bonus:
            won = self.seat in self.game.result.winners  # type: ignore[union-attr]
            reward += cfg.win_bonus if won else -cfg.win_bonus / (len(result.scores) - 1)
        return reward

    def _episode_info(self) -> dict[str, float]:
        mine = [r.scores[self.seat] for r in self._rounds]
        others = [s for r in self._rounds for i, s in enumerate(r.scores) if i != self.seat]
        best_other = [min(s for i, s in enumerate(r.scores) if i != self.seat) for r in self._rounds]
        info = {
            "return": self._episode_return,
            "length": float(self._episode_len),
            "score": sum(mine) / len(mine),
            "opp_score": sum(others) / len(others),
            "round_win": sum(m < b for m, b in zip(mine, best_other, strict=True)) / len(mine),
            "finished": sum(r.finisher == self.seat for r in self._rounds) / len(mine),
            "doubled": sum(r.finisher == self.seat and r.doubled for r in self._rounds) / len(mine),
        }
        if self.game is not None and self.game.is_over:
            won = float(self.seat in self.game.result.winners)  # type: ignore[union-attr]
            n = self.game.rules.n_players
            info["game_win"] = won
            info["game_win_vs_fair"] = won * n  # 1.0 = fair share at any table size
            if len(self._sizes) > 1:
                info[f"game_win_{n}p"] = won
        return info
