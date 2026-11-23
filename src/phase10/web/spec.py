"""Phase 10 on the platform: its tile, its table and the static data its client needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from phase10.game.model import phases_public
from phase10.web.room import MAX_SEATS, Room, RoomError, bots_public


def catalogue() -> dict[str, Any]:
    """Static game data the client needs to draw and explain things."""
    return {"bots": bots_public(), "phases": phases_public(), "reactions": list(Room.REACTIONS), "max_seats": MAX_SEATS}


class Backend:
    def __init__(self, delay_scale: float = 1.0) -> None:
        self.delay_scale = delay_scale

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return catalogue()


GAME = GameSpec(
    key="phase10",
    title="Phase 10",
    tagline="Collect sets, runs and colours and lay down all ten phases before anyone else.",
    min_players=2,
    max_players=MAX_SEATS,
    bots=True,
    kind="versus",
    minutes="45–90",
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#e0533d",
)
