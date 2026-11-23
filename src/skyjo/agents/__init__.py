"""Agent registry. Build agents from CLI-friendly specs.

Spec grammar: ``name[:key=value[,key=value...]]``. A bare token without ``=`` is
passed as ``path`` (handy for learned policies: ``ppo:runs/x/policy_best.npz``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from skyjo.agents.base import Agent
from skyjo.agents.expected_value import ExpectedValueAgent
from skyjo.agents.expert import ExpertAgent
from skyjo.agents.greedy import GreedyAgent
from skyjo.agents.random_agent import RandomAgent


def _make_policy(**kwargs: Any) -> Agent:
    from skyjo.rl.policy_agent import PolicyAgent

    return PolicyAgent.from_file(**kwargs)


REGISTRY: dict[str, Callable[..., Agent]] = {
    "random": RandomAgent,
    "greedy": GreedyAgent,
    "ev": ExpectedValueAgent,
    "expert": ExpertAgent,
    "ppo": _make_policy,
}


def _coerce(value: str) -> Any:
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def parse_spec(spec: str) -> tuple[str, dict[str, Any]]:
    name, _, rest = spec.partition(":")
    kwargs: dict[str, Any] = {}
    for token in filter(None, rest.split(",")):
        key, sep, value = token.partition("=")
        if sep:
            kwargs[key.strip()] = _coerce(value.strip())
        else:
            kwargs["path"] = token.strip()
    return name.strip(), kwargs


def make_agent(spec: str, seed: int | None = None) -> Agent:
    name, kwargs = parse_spec(spec)
    if name not in REGISTRY:
        raise KeyError(f"unknown agent {name!r}; choose from {sorted(REGISTRY)}")
    agent = REGISTRY[name](seed=seed, **kwargs)
    agent.name = spec if kwargs else name
    return agent


__all__ = [
    "REGISTRY",
    "Agent",
    "ExpectedValueAgent",
    "ExpertAgent",
    "GreedyAgent",
    "RandomAgent",
    "make_agent",
    "parse_spec",
]
