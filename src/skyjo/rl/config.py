"""Training configuration: dataclasses <-> YAML, with dotted CLI overrides."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from skyjo.rl.env import EnvConfig


@dataclass
class PPOConfig:
    total_timesteps: int = 20_000_000
    num_envs: int = 128
    num_steps: int = 128  # rollout length per env per update
    num_workers: int = 8  # env processes; 0/1 = in-process
    learning_rate: float = 2.5e-4
    anneal_lr: bool = True
    gamma: float = 0.995
    gae_lambda: float = 0.95
    num_minibatches: int = 8
    update_epochs: int = 4
    clip_coef: float = 0.2
    clip_vloss: bool = True
    ent_coef: float = 0.01
    ent_coef_final: float | None = 0.002  # linearly annealed to this if set
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    target_kl: float | None = None
    hidden: list[int] = field(default_factory=lambda: [256, 256])
    residual_prior: bool = False  # logits = MLP + scale * expert prior block (obs v3+)
    prior_scale: float = 20.0  # initial scale; 20 = softmax temperature of 0.5 points
    critic_warmup_updates: int = 0  # train only the critic for the first N updates

    @property
    def batch_size(self) -> int:
        return self.num_envs * self.num_steps

    @property
    def minibatch_size(self) -> int:
        return self.batch_size // self.num_minibatches


@dataclass
class EvalConfig:
    every_updates: int = 20
    games: int = 400
    opponents: list[str] = field(default_factory=lambda: ["random", "greedy", "ev"])
    workers: int = 8
    best_metric_opponent: str = "ev"
    # Lineups of 1 policy + (n - 1) opponents; None = env.n_players. Sizes other than
    # env.n_players log under eval/<opponent>_<n>p/*.
    table_sizes: list[int] | None = None
    # Metric that picks policy_best; default eval/<best_metric_opponent>/win_rate. With several
    # table sizes, eval/<opponent>/mean_win_vs_fair (mean of win rate x n) is also logged.
    best_metric: str | None = None


@dataclass
class TrainConfig:
    name: str = "ppo"
    seed: int = 0
    device: str = "cpu"  # "cpu" | "mps" | "auto"
    torch_threads: int = 4
    snapshot_every_updates: int = 10
    save_every_updates: int = 50
    run_root: str = "runs"
    init_checkpoint: str | None = None  # start from these weights (fresh optimizer and schedule)
    env: EnvConfig = field(default_factory=EnvConfig)
    ppo: PPOConfig = field(default_factory=PPOConfig)
    eval: EvalConfig = field(default_factory=EvalConfig)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _build(cls: type, data: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {}
    fields = {f.name: f for f in dataclasses.fields(cls)}
    for key, value in data.items():
        if key not in fields:
            raise KeyError(f"unknown config key {cls.__name__}.{key}")
        ftype = str(fields[key].type)
        sub = {"EnvConfig": EnvConfig, "PPOConfig": PPOConfig, "EvalConfig": EvalConfig}.get(ftype)
        if sub and isinstance(value, dict):
            value = _build(sub, value)
        elif isinstance(value, str) and ftype.split(" |")[0] in ("float", "int"):
            # YAML 1.1 reads "1e-3" as a string
            value = float(value) if ftype.startswith("float") else int(float(value))
        kwargs[key] = value
    return cls(**kwargs)


def _set_dotted(data: dict[str, Any], dotted: str, value: Any) -> None:
    *parents, leaf = dotted.split(".")
    node = data
    for p in parents:
        node = node.setdefault(p, {})
    node[leaf] = value


# Mappings that a YAML file replaces wholesale instead of merging into defaults.
_REPLACE_KEYS = {"opponents"}


def _merge(base: dict[str, Any], update: dict[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict) and key not in _REPLACE_KEYS:
            _merge(base[key], value)
        else:
            base[key] = value


def load_config(path: str | Path | None = None, overrides: list[str] | None = None) -> TrainConfig:
    data: dict[str, Any] = TrainConfig().to_dict()
    if path is not None:
        _merge(data, yaml.safe_load(Path(path).read_text()) or {})
    for item in overrides or []:
        key, sep, raw = item.partition("=")
        if not sep:
            raise ValueError(f"override must look like key=value, got {item!r}")
        _set_dotted(data, key.strip(), yaml.safe_load(raw))
    return _build(TrainConfig, data)
