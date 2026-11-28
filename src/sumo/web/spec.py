"""Marble Sumo on the platform: its tile, its table and the static data its client needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from sumo.web.room import Room, RoomError, catalogue


class Backend:
    def __init__(self, delay_scale: float = 1.0) -> None:
        self.delay_scale = delay_scale

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return catalogue()


GAME = GameSpec(
    key="sumo",
    title="Marble Sumo",
    tagline="Fourteen marbles each on a hexagonal ring. Push in lines, outnumber, shove six of theirs off the edge.",
    min_players=2,
    max_players=2,
    bots=True,
    kind="versus",
    minutes="20–40",
    weight=2.14,
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#7a5cc0",
)
