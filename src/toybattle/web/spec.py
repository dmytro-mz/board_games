"""Toy Battle on the platform: its tile, its table and the static data its client needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from toybattle.web.room import Room, RoomError, catalogue


class Backend:
    def __init__(self, delay_scale: float = 1.0) -> None:
        self.delay_scale = delay_scale

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return catalogue()


GAME = GameSpec(
    key="toybattle",
    title="Toy Battle",
    tagline="Two toy armies, one playroom. Out-stack your rival, grab the medals or storm their H.Q.",
    min_players=2,
    max_players=2,
    bots=True,
    kind="versus",
    minutes="15–25",
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#e0533d",
)
