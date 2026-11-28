"""Bot registry. `REGISTRY` is what the web lobby offers; `ALL` adds the baselines for `bg sumo eval` and tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sumo.bots.base import Bot, RandomBot
from sumo.bots.search import SearchBot


@dataclass(frozen=True)
class BotType:
    key: str
    label: str
    stars: int
    description: str
    make: Callable[..., Bot]  # (seed, budget=seconds) -> Bot


REGISTRY: dict[str, BotType] = {
    b.key: b
    for b in (
        BotType(
            "rookie",
            "Rookie",
            1,
            "Looks one move ahead and often picks a so-so one. Good for learning the pushes.",
            lambda seed, budget=None: SearchBot(seed, depth=1, spread=60),
        ),
        BotType(
            "ozeki",
            "Ozeki",
            3,
            "Looks two moves ahead, keeps its marbles together and heads for the middle.",
            lambda seed, budget=None: SearchBot(seed, depth=2, spread=6),
        ),
        BotType(
            "yokozuna",
            "Yokozuna",
            5,
            "Searches as deep as it can in a second and a half. Patient, tight and hard to push.",
            lambda seed, budget=1.5: SearchBot(seed, budget=budget),
        ),
    )
}

ALL: dict[str, BotType] = {
    **REGISTRY,
    "d3": BotType("d3", "Depth 3", 4, "", lambda seed, budget=None: SearchBot(seed, depth=3)),
    "random": BotType("random", "Random", 0, "", lambda seed, budget=None: RandomBot(seed)),
}


def make_bot(key: str, seed: int | None = None, budget: float | None = None) -> Bot:
    """A registered bot, or "d<N>" for a fixed-depth searcher, "t<seconds>" for a timed one."""
    if key in ALL:
        bot = ALL[key]
        return bot.make(seed) if budget is None else bot.make(seed, budget=budget)
    if key[0] == "d" and key[1:].isdigit():
        return SearchBot(seed, depth=int(key[1:]))
    if key[0] == "t":
        return SearchBot(seed, budget=float(key[1:]))
    raise KeyError(key)


__all__ = ["ALL", "REGISTRY", "Bot", "BotType", "RandomBot", "SearchBot", "make_bot"]
