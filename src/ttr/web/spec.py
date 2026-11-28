"""Ticket to Ride: Europe on the platform: its tile, its table, the map and the bot list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from ttr.game.europe import EUROPE
from ttr.web.room import MAX_SEATS, MIN_SEATS, Room, RoomError, bots_public


class Backend:
    def __init__(self, delay_scale: float = 1.0) -> None:
        self.delay_scale = delay_scale
        self.board = EUROPE.to_json()

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return {"bots": bots_public()}

    def routes(self, router: Any) -> None:
        @router.get("/api/map", constant=True)
        async def board_json() -> dict[str, Any]:
            return self.board


GAME = GameSpec(
    key="ttr",
    title="Ticket to Ride: Europe",
    tagline="Claim railway routes across Europe: tunnels, ferries, stations and secret tickets.",
    min_players=MIN_SEATS,
    max_players=MAX_SEATS,
    bots=True,
    kind="versus",
    minutes="45–90",
    weight=1.92,
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#b8342f",
)
