from __future__ import annotations

import random

from avel.bots.base import Bot, BotType
from avel.bots.hero import HeroBot
from avel.game import actions as A
from avel.game.actions import Action
from avel.game.engine import View


class RandomBot(Bot):
    """Picks any legal action, but rolls the dice and ends turns instead of shuffling items forever."""

    def __init__(self, seed: int | None = None) -> None:
        super().__init__(seed)
        self.rng = random.Random(seed)

    def act(self, view: View) -> Action:
        busy = [a for a in view.legal if not isinstance(a, A.Discard | A.Give | A.Take | A.Equip | A.Unequip)]
        if busy and self.rng.random() < 0.9:
            return self.rng.choice(busy)
        return self.rng.choice(view.legal)


BOT_TYPES: dict[str, BotType] = {
    b.key: b
    for b in (
        BotType(
            "knight",
            "Knight",
            3,
            "Plans every move: gears up, clears lairs, builds walls and traps, then hunts the Beast.",
            lambda seed: HeroBot(seed),
        ),
        BotType(
            "squire",
            "Squire",
            1,
            "Wanders about and does whatever comes to mind.",
            lambda seed: RandomBot(seed),
        ),
    )
}
DEFAULT_BOT = "knight"

__all__ = ["BOT_TYPES", "DEFAULT_BOT", "Bot", "BotType", "HeroBot", "RandomBot"]
