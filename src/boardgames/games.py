"""The game catalogue: what the platform knows about each game and how it creates the game's table.

Every game is its own top-level package with a `web/spec.py` that defines `GAME = GameSpec(...)`. Adding a game
means adding that module and its key to `GAME_KEYS`; nothing else in the platform changes.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

# Order of the tiles on the game selection screen.
GAME_KEYS = (
    "ttr",
    "pandemic",
    "karak",
    "codenames",
    "skyjo",
    "phase10",
    "lostcities",
    "toybattle",
    "avenue",
    "skyteam",
)
# Games that are in the repo (code, tests, `bg <game>` tools) but not finished: not offered in rooms unless the
# server runs with `bg serve --unfinished`.
UNFINISHED_KEYS = ("avel",)


class GameRoom(Protocol):
    """What the platform needs from a game's table (each game's `web/room.py` `Room`)."""

    id: str
    status: str  # "lobby" while the table sits in the game's own lobby
    host_id: str | None
    members: dict[str, Any]

    def join(self, token: str, name: object, origin: str = "") -> Any: ...
    def connect(self, listener: Any) -> None: ...
    def disconnect(self, listener: Any) -> None: ...
    def handle(self, member_id: str, msg: dict[str, Any]) -> dict[str, Any] | None: ...
    def set_host(self, member_id: str) -> None: ...
    def describe(self) -> str: ...
    async def drive(self) -> None: ...
    def close(self) -> None: ...


class Backend(Protocol):
    """A game's server side, built once at startup (bot catalogues, decks, progress files…).

    Optional extras, looked up with getattr:
      mounts() -> {name: folder}                 static folders served under /g/<key>/<name>/
      routes(router)                             extra HTTP endpoints under /g/<key>/
      on_connect(room, conn)                     a member's table socket just opened (test tools)
      on_message(room, conn, msg) -> bool        handle a socket message instead of the room (test tools)
    """

    def new_room(self, code: str) -> GameRoom: ...
    def config(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GameSpec:
    key: str  # package name and URL segment: /g/<key>/
    title: str
    tagline: str
    min_players: int
    max_players: int
    bots: bool  # bots can fill empty seats
    kind: str  # "versus" | "teams" | "coop"
    minutes: str  # typical play time, e.g. "30–60"
    static: Path  # the game's web client
    backend: Callable[..., Backend]  # (delay_scale=..., **game options) -> Backend
    error: type[Exception]  # the game's RoomError: its message is shown to the player
    accent: str = "#888888"  # tile colour
    weight: float = 0.0  # BoardGameGeek "weight" (complexity), 0–5

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "tagline": self.tagline,
            "min_players": self.min_players,
            "max_players": self.max_players,
            "bots": self.bots,
            "kind": self.kind,
            "minutes": self.minutes,
            "accent": self.accent,
            "weight": self.weight,
        }

    def fits(self, people: int) -> bool:
        """Can this many people play it together (bots fill the missing seats)?"""
        return people <= self.max_players and (people >= self.min_players or self.bots)


def load_games(keys: tuple[str, ...] = GAME_KEYS) -> dict[str, GameSpec]:
    games: dict[str, GameSpec] = {}
    for key in keys:
        spec: GameSpec = importlib.import_module(f"{key}.web.spec").GAME
        assert spec.key == key, f"{key}.web.spec defines {spec.key!r}"
        games[key] = spec
    return games
