"""Agent Avenue on the platform: its tile, its table and the bot list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from avenue.web.room import MAX_SEATS, Room, RoomError, bots_public
from boardgames.games import GameSpec


class Backend:
    def __init__(self, delay_scale: float = 1.0, think: float = 1.0) -> None:
        """`think`: the most seconds the Mastermind bot may think per decision."""
        self.delay_scale = delay_scale
        self.think = think

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale, bot_budget=self.think)

    def config(self) -> dict[str, Any]:
        return {"bots": bots_public()}


GAME = GameSpec(
    key="avenue",
    title="Agent Avenue",
    tagline="Bluff with face-up and face-down cards, recruit spies and chase the rival agent.",
    min_players=2,
    max_players=MAX_SEATS,
    bots=True,
    kind="versus",
    minutes="15–30",
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#d9822b",
)
