"""Lost Cities on the platform: its tile, its table and the static data its client needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from lostcities.game.cards import BONUS_CARDS, BONUS_POINTS, COLORS, EXPEDITION_COST, HAND_SIZE, SITES
from lostcities.web.room import MAX_SEATS, Room, RoomError, bots_public


def catalogue() -> dict[str, Any]:
    """Static game data the client needs to draw and explain things."""
    return {
        "bots": bots_public(),
        "colors": list(COLORS),
        "sites": SITES,
        "hand_size": HAND_SIZE,
        "cost": EXPEDITION_COST,
        "bonus_cards": BONUS_CARDS,
        "bonus_points": BONUS_POINTS,
        "max_seats": MAX_SEATS,
        "reactions": list(Room.REACTIONS),
    }


class Backend:
    def __init__(self, delay_scale: float = 1.0) -> None:
        self.delay_scale = delay_scale

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return catalogue()


GAME = GameSpec(
    key="lostcities",
    title="Lost Cities",
    tagline="Fund five daring expeditions and push them deep, card by card. A tense duel.",
    min_players=2,
    max_players=2,
    bots=True,
    kind="versus",
    minutes="20–40",
    weight=1.47,
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#c9a14a",
)
