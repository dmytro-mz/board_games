"""Bots. Each gets `Game.redacted(player)` — only what that player may see — and returns an action."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from avenue.bots.heuristic import heuristic_action
from avenue.bots.search import SearchBot
from avenue.game.engine import Action, Game


class Bot(Protocol):
    def act(self, view: Game, player: int) -> Action: ...


class HeuristicBot:
    """The quick rule-of-thumb player the search bot uses for its playouts (a sparring partner for tests)."""

    def __init__(self, seed: int | None = None, noise: float = 0.0) -> None:
        self.rng = random.Random(seed)
        self.noise = noise

    def act(self, view: Game, player: int) -> Action:
        return heuristic_action(view, player, self.rng, self.noise)


class RandomBot:
    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def act(self, view: Game, player: int) -> Action:
        return self.rng.choice(view.legal(player))


@dataclass(frozen=True)
class BotInfo:
    key: str
    label: str
    description: str


MASTERMIND = BotInfo(SearchBot.key, SearchBot.label, SearchBot.description)
REGISTRY = {MASTERMIND.key: MASTERMIND}


def make_bot(key: str, seed: int | None = None, **kwargs: float) -> Bot:
    if key == "mastermind":
        return SearchBot(seed=seed, **kwargs)  # type: ignore[arg-type]
    if key == "heuristic":
        return HeuristicBot(seed=seed)
    if key == "random":
        return RandomBot(seed=seed)
    raise KeyError(key)


__all__ = ["REGISTRY", "Bot", "BotInfo", "HeuristicBot", "RandomBot", "SearchBot", "make_bot"]
