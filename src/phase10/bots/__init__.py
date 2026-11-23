"""Bot registry. Every entry shows up in the web lobby and in `phase10 eval`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from phase10.bots.base import Bot
from phase10.bots.planner import PlannerBot, PlannerConfig


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
            "Plays by feel: keeps pairs, often throws away the wrong card and skips someone at random.",
            lambda seed: PlannerBot(seed, PlannerConfig(smart_draw=False, deny=False, skip_leader=False, noise=0.35)),
        ),
        BotType(
            "regular",
            "Regular",
            3,
            "Knows what its phase needs and takes useful discards, but doesn't watch the other players.",
            lambda seed: PlannerBot(seed, PlannerConfig(deny=False, skip_leader=False)),
        ),
        BotType(
            "pro",
            "Pro",
            5,
            "Counts what it still needs, never feeds the next player and skips whoever is about to go out.",
            lambda seed: PlannerBot(seed),
        ),
    )
}


def make_bot(key: str, seed: int | None = None) -> Bot:
    return REGISTRY[key].make(seed)


__all__ = ["REGISTRY", "Bot", "BotType", "PlannerBot", "PlannerConfig", "make_bot"]
