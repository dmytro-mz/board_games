"""Karak on the platform: its tile, its table and the static data its client needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from karak.game.model import ITEMS, MONSTERS, REGENT_ITEMS, REGENT_MONSTERS
from karak.web.room import MAX_SEATS, MIN_SEATS, Room, RoomError, bots_public, heroes_public


def catalogue() -> dict[str, Any]:
    """Static game data the client needs to draw and explain things."""
    return {
        "bots": bots_public(),
        "heroes": heroes_public(),
        "monsters": [
            {
                "key": m.key,
                "name": m.name,
                "strength": m.strength,
                "loot": m.loot,
                "count": m.count,
                "expansion": m.key in REGENT_MONSTERS,
            }
            for m in MONSTERS.values()
        ],
        "items": [
            {
                "key": i.key,
                "name": i.name,
                "slot": i.slot.value if i.slot else None,
                "power": i.power,
                "points": i.points,
                "expansion": i.key in REGENT_ITEMS,
            }
            for i in ITEMS.values()
        ],
    }


class Backend:
    def __init__(self, delay_scale: float = 1.0) -> None:
        self.delay_scale = delay_scale

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return catalogue()


GAME = GameSpec(
    key="karak",
    title="Karak",
    tagline="Explore the labyrinth tile by tile, fight monsters for loot and slay the Dragon.",
    min_players=MIN_SEATS,
    max_players=MAX_SEATS,
    bots=True,
    kind="versus",
    minutes="30–60",
    weight=1.29,
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#8a6d4b",
)
