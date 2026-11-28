"""Pandemic on the platform: its tile, its table and the static data its client needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from pandemic.game import model
from pandemic.web.room import BOT_SPEEDS, MAX_SEATS, MIN_SEATS, REACTIONS, Room, RoomError, bots_public


def catalogue() -> dict[str, Any]:
    """Static game data the client needs to draw and explain things."""
    return {
        "bots": bots_public(),
        **model.catalogue(),
        "reactions": list(REACTIONS),
        "max_seats": MAX_SEATS,
        "min_seats": MIN_SEATS,
        "bot_speeds": list(BOT_SPEEDS),
    }


class Backend:
    def __init__(self, delay_scale: float = 1.0) -> None:
        self.delay_scale = delay_scale
        self._catalogue = catalogue()

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return self._catalogue


GAME = GameSpec(
    key="pandemic",
    title="Pandemic",
    tagline="Travel the world as a team and cure four diseases before outbreaks take over.",
    min_players=MIN_SEATS,
    max_players=MAX_SEATS,
    bots=True,
    kind="coop",
    minutes="45–60",
    weight=2.39,
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#3f8fd2",
)
