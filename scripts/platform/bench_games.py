"""How to set up a bot game at each table for the benchmarks: which bots fill the seats, and how to nudge the table
past steps that wait for humans (between rounds). Humans are seated and put on autopilot, so every seat's own view
is built and sent exactly as in a real game."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

DONE = {"game_over", "over"}


@dataclass
class Recipe:
    bot: str
    seats: int
    max_humans: int = 4
    options: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    after_start: Callable[[Any], None] | None = None

    def setup(self, room: Any, humans: list[str]) -> None:
        host = room.host_id
        if self.settings:
            room.handle(host, {"type": "settings", "changes": self.settings})
        while len(room.seats) < self.seats:
            room.handle(host, {"type": "add_bot", "bot": self.bot})
        room.handle(host, {"type": "start"})
        autopilot(room, humans)

    def nudge(self, room: Any, humans: list[str]) -> None:
        """Answer what a table waits for from its humans (ready between rounds), like a player clicking on."""
        if getattr(room, "status", "") in ("round_over", "hand_over", "scoring"):
            for mid in humans:
                for kind in ("ready", "continue"):
                    with contextlib.suppress(Exception):
                        room.handle(mid, {"type": kind})
        autopilot(room, humans)


def autopilot(room: Any, humans: list[str]) -> None:
    for seat in room.seats:
        if getattr(seat, "member_id", None) in humans and not seat.autoplay:
            seat.autoplay = True
            if hasattr(room, "_wake"):
                room._wake.set()


def finished(room: Any) -> bool:
    return getattr(room, "status", "") in DONE


RECIPES: dict[str, Recipe] = {
    "ttr": Recipe("expert", 4),
    "pandemic": Recipe("expert", 4),
    "karak": Recipe("champion", 4),
    "skyjo": Recipe("expert", 4),
    "phase10": Recipe("pro", 4),
    "lostcities": Recipe("veteran", 2, max_humans=1),
    "toybattle": Recipe("general", 2, max_humans=1),
    "sumo": Recipe("yokozuna", 2, max_humans=1),
    "avenue": Recipe("mastermind", 4),
}
