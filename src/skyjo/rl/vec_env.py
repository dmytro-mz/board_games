"""Batched environments with auto-reset. `SubprocVecEnv` shards envs across worker
processes (each worker steps its shard sequentially) to use all M-series cores.
"""

from __future__ import annotations

import contextlib
import multiprocessing as mp
from multiprocessing.connection import Connection
from typing import Any, Protocol

import numpy as np

from skyjo.rl.env import EnvConfig, SkyjoEnv
from skyjo.rl.policy_agent import Layers

Batch = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, float]]]


class VecEnv(Protocol):
    num_envs: int
    obs_dim: int

    def reset(self) -> tuple[np.ndarray, np.ndarray]: ...
    def step(self, actions: np.ndarray) -> Batch: ...
    def add_snapshot(self, layers: Layers, prior_scale: float | None = None) -> None: ...
    def close(self) -> None: ...


class _Shard:
    def __init__(self, config: EnvConfig, n_envs: int, seed: int) -> None:
        self.envs = [SkyjoEnv(config, seed=seed + i) for i in range(n_envs)]

    def reset(self) -> tuple[np.ndarray, np.ndarray]:
        obs = np.stack([env.reset()[0] for env in self.envs])
        masks = np.stack([env.action_masks() for env in self.envs])
        return obs, masks

    def step(self, actions: np.ndarray) -> Batch:
        n = len(self.envs)
        obs = np.empty((n, self.envs[0].encoder.dim), dtype=np.float32)
        masks = np.empty((n, self.envs[0].action_space.n), dtype=bool)  # type: ignore[attr-defined]
        rewards = np.empty(n, dtype=np.float32)
        dones = np.empty(n, dtype=bool)
        episodes: list[dict[str, float]] = []
        for i, (env, a) in enumerate(zip(self.envs, actions, strict=True)):
            o, r, term, trunc, info = env.step(int(a))
            if term or trunc:
                episodes.append(info["episode"])
                o, _ = env.reset()
            obs[i], rewards[i], dones[i] = o, r, term or trunc
            masks[i] = env.action_masks()
        return obs, masks, rewards, dones, episodes

    def add_snapshot(self, layers: Layers, prior_scale: float | None = None) -> None:
        for env in self.envs:
            env.pool.add_snapshot(layers, prior_scale)


class SyncVecEnv:
    def __init__(self, config: EnvConfig, num_envs: int, seed: int = 0) -> None:
        self.shard = _Shard(config, num_envs, seed)
        self.num_envs = num_envs
        self.obs_dim = self.shard.envs[0].encoder.dim

    def reset(self) -> tuple[np.ndarray, np.ndarray]:
        return self.shard.reset()

    def step(self, actions: np.ndarray) -> Batch:
        return self.shard.step(actions)

    def add_snapshot(self, layers: Layers, prior_scale: float | None = None) -> None:
        self.shard.add_snapshot(layers, prior_scale)

    def close(self) -> None:
        pass


def _worker(remote: Connection, config: EnvConfig, n_envs: int, seed: int) -> None:
    shard = _Shard(config, n_envs, seed)
    try:
        while True:
            cmd, payload = remote.recv()
            if cmd == "step":
                remote.send(shard.step(payload))
            elif cmd == "reset":
                remote.send(shard.reset())
            elif cmd == "add_snapshot":
                shard.add_snapshot(*payload)
            elif cmd == "close":
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        remote.close()


class SubprocVecEnv:
    def __init__(self, config: EnvConfig, num_envs: int, num_workers: int, seed: int = 0) -> None:
        if num_envs % num_workers:
            raise ValueError("num_envs must be divisible by num_workers")
        self.num_envs = num_envs
        self.obs_dim = SkyjoEnv(config).encoder.dim
        per = num_envs // num_workers
        ctx = mp.get_context("spawn")
        self.remotes: list[Connection] = []
        self.procs: list[Any] = []
        for w in range(num_workers):
            parent, child = ctx.Pipe()
            proc = ctx.Process(target=_worker, args=(child, config, per, seed + w * per), daemon=True)
            proc.start()
            child.close()
            self.remotes.append(parent)
            self.procs.append(proc)
        self.splits = np.cumsum([per] * num_workers)[:-1]

    def reset(self) -> tuple[np.ndarray, np.ndarray]:
        for r in self.remotes:
            r.send(("reset", None))
        results = [r.recv() for r in self.remotes]
        return np.concatenate([o for o, _ in results]), np.concatenate([m for _, m in results])

    def step(self, actions: np.ndarray) -> Batch:
        for r, a in zip(self.remotes, np.split(actions, self.splits), strict=True):
            r.send(("step", a))
        results = [r.recv() for r in self.remotes]
        episodes = [ep for res in results for ep in res[4]]
        return (
            np.concatenate([res[0] for res in results]),
            np.concatenate([res[1] for res in results]),
            np.concatenate([res[2] for res in results]),
            np.concatenate([res[3] for res in results]),
            episodes,
        )

    def add_snapshot(self, layers: Layers, prior_scale: float | None = None) -> None:
        for r in self.remotes:
            r.send(("add_snapshot", (layers, prior_scale)))

    def close(self) -> None:
        for r in self.remotes:
            with contextlib.suppress(BrokenPipeError, OSError):
                r.send(("close", None))
        for p in self.procs:
            p.join(timeout=5)


def make_vec_env(config: EnvConfig, num_envs: int, num_workers: int, seed: int = 0) -> VecEnv:
    if num_workers <= 1:
        return SyncVecEnv(config, num_envs, seed)
    return SubprocVecEnv(config, num_envs, num_workers, seed)
