"""Torch-free inference for trained policies (used by env workers and tournaments)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from skyjo.agents.base import Agent
from skyjo.game.observation import Observation
from skyjo.rl.encoding import OBS_VERSION, SUPPORTED_VERSIONS, ObsEncoder

Layers = list[tuple[np.ndarray, np.ndarray]]  # (W[in, out], b[out])


def mlp_forward(layers: Layers, x: np.ndarray) -> np.ndarray:
    for i, (w, b) in enumerate(layers):
        x = x @ w + b
        if i < len(layers) - 1:
            np.maximum(x, 0.0, out=x)
    return x


class PolicyAgent(Agent):
    name = "ppo"

    def __init__(
        self,
        layers: Layers,
        n_players: int | None,
        greedy: bool = True,
        seed: int | None = None,
        obs_version: int = OBS_VERSION,
        prior_scale: float | None = None,
    ) -> None:
        super().__init__(seed)
        self.layers = [(w.astype(np.float32), b.astype(np.float32)) for w, b in layers]
        self.encoder = ObsEncoder(n_players, obs_version)
        self.greedy = greedy
        if self.layers[0][0].shape[0] != self.encoder.dim:
            raise ValueError("policy input size does not match the observation encoder")
        if prior_scale is not None and self.encoder.prior_offset is None:
            raise ValueError(f"obs version {obs_version} has no prior block for a residual policy")
        self.prior_scale = prior_scale

    def logits(self, obs: Observation) -> np.ndarray:
        if not self.encoder.supports(obs.n_players):
            raise ValueError(
                f"policy was trained for {self.encoder.n_players} players, game has {obs.n_players}; "
                "use an obs v4+ policy for other table sizes"
            )
        x = self.encoder.encode(obs)
        logits = mlp_forward(self.layers, x)
        if self.prior_scale is not None:
            start = self.encoder.prior_offset
            assert start is not None
            logits += self.prior_scale * x[start : start + len(logits)]
        return logits

    def act(self, obs: Observation, legal: Sequence[int]) -> int:
        logits = self.logits(obs)
        legal_logits = logits[list(legal)]
        if self.greedy:
            return legal[int(np.argmax(legal_logits))]
        z = legal_logits - legal_logits.max()
        p = np.exp(z)
        p /= p.sum()
        return legal[int(self.rng.choices(range(len(legal)), weights=p.tolist())[0])]

    # ------------------------------------------------------------------ io
    def save(self, path: str | Path) -> None:
        arrays: dict[str, np.ndarray] = {}
        for i, (w, b) in enumerate(self.layers):
            arrays[f"W{i}"] = w
            arrays[f"b{i}"] = b
        meta = {
            "n_players": self.encoder.n_players,
            "obs_version": self.encoder.version,
            "n_layers": len(self.layers),
            "prior_scale": self.prior_scale,
        }
        arrays["meta"] = np.array(json.dumps(meta))
        np.savez(Path(path), **arrays)  # type: ignore[arg-type]

    @classmethod
    def from_file(cls, path: str, greedy: bool = True, seed: int | None = None) -> PolicyAgent:
        data = np.load(path)
        meta = json.loads(str(data["meta"]))
        if meta["obs_version"] not in SUPPORTED_VERSIONS:
            raise ValueError(f"{path}: obs_version {meta['obs_version']} no longer supported")
        layers = [(data[f"W{i}"], data[f"b{i}"]) for i in range(meta["n_layers"])]
        return cls(
            layers,
            n_players=meta["n_players"],
            greedy=greedy,
            seed=seed,
            obs_version=meta["obs_version"],
            prior_scale=meta.get("prior_scale"),
        )
