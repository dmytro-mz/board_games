from __future__ import annotations

from toybattle.bots.base import Bot
from toybattle.game.engine import Action, View


class RandomBot(Bot):
    """Uniformly random legal actions (smoke tests only)."""

    def act(self, view: View) -> Action:
        return self.rng.choice(view.legal)
