"""Bot registry. `REGISTRY` is what the web lobby offers (one strong bot); `ALL` adds the baselines used by
`bg toybattle eval` and the tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from toybattle.bots.base import Bot
from toybattle.bots.general import GeneralBot, GreedyBot
from toybattle.bots.randombot import RandomBot


@dataclass(frozen=True)
class BotType:
    key: str
    label: str
    stars: int
    description: str
    make: Callable[[int | None], Bot]


REGISTRY: dict[str, BotType] = {
    "general": BotType(
        "general",
        "The General",
        5,
        "Thinks three turns ahead, guards its H.Q. and never misses a winning move.",
        lambda seed: GeneralBot(seed),
    ),
}

ALL: dict[str, BotType] = {
    **REGISTRY,
    "general-fast": BotType(
        "general-fast", "General (fixed 3 worlds)", 5, "", lambda s: GeneralBot(s, budget=None, worlds=3)
    ),
    "general-6": BotType(
        "general-6", "General (fixed 6 worlds)", 5, "", lambda s: GeneralBot(s, budget=None, worlds=6)
    ),
    "deep": BotType(
        "deep", "General, 3 turns deep", 5, "", lambda s: GeneralBot(s, budget=None, worlds=3, top=8, beams=(5, 3))
    ),
    "greedy": BotType("greedy", "Greedy", 2, "", lambda seed: GreedyBot(seed)),
    "random": BotType("random", "Random", 0, "", lambda seed: RandomBot(seed)),
}


def make_bot(key: str, seed: int | None = None) -> Bot:
    """A registered bot, or a General with fixed settings for experiments: "g:w3:t8:b5-3" (3 worlds, top 8
    candidates, beams 5 then 3, no time budget)."""
    if key.startswith("g:"):
        opts: dict[str, object] = {"budget": None}
        for part in key.split(":")[1:]:
            if part[0] == "w":
                opts["worlds"] = int(part[1:])
            elif part[0] == "t":
                opts["top"] = int(part[1:])
            elif part[0] == "b":
                opts["beams"] = tuple(int(x) for x in part[1:].split("-"))
            elif part[0] == "s":
                opts["budget"] = float(part[1:])
                opts["min_worlds"] = 2
        return GeneralBot(seed, **opts)  # type: ignore[arg-type]
    return ALL[key].make(seed)


__all__ = ["ALL", "REGISTRY", "Bot", "BotType", "GeneralBot", "GreedyBot", "RandomBot", "make_bot"]
