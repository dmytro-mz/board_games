"""Bot registry. Every entry shows up in the web lobby and in `pandemic eval`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pandemic.bots.base import Bot
from pandemic.bots.planner import Planner


@dataclass(frozen=True)
class BotType:
    key: str
    label: str
    stars: int
    description: str
    make: Callable[[int | None], Bot]


REGISTRY: dict[str, BotType] = {
    b.key: b
    for b in (
        BotType(
            "rookie",
            "Rookie",
            1,
            "Treats what's in front of it and sometimes wanders off. Forgets its event cards.",
            lambda seed: Planner(seed, beam=1, noise=0.25, events=False),
        ),
        BotType(
            "expert",
            "Expert",
            3,
            "Plans the whole turn, collects cure sets, guards cities about to outbreak and times its events.",
            lambda seed: Planner(seed),
        ),
    )
}


def make_bot(key: str, seed: int | None = None) -> Bot:
    return REGISTRY[key].make(seed)


__all__ = ["REGISTRY", "Bot", "BotType", "Planner", "make_bot"]
