"""Codenames on the platform: its tile, its table, the decks and the solo test mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from boardgames.games import GameSpec
from codenames.game.decks import PICTURES_DIR, load_decks
from codenames.web.room import MAX_MEMBERS, REACTIONS, TIMERS, Room, RoomError


class Backend:
    def __init__(self, delay_scale: float = 1.0, pictures: Path | None = None, test: bool = False) -> None:
        """`pictures`: a folder of your own images (at least 20), offered as an extra deck.
        `test`: solo testing, fake players you can switch between to take every seat yourself."""
        self.pictures = pictures
        self.test = test
        self.decks = load_decks(pictures)

    def new_room(self, code: str) -> Room:
        return Room(code, decks=self.decks)

    def config(self) -> dict[str, Any]:
        return {
            "decks": [d.public() for d in self.decks.values()],
            "timers": list(TIMERS),
            "reactions": list(REACTIONS),
            "test": self.test,
        }

    def mounts(self) -> dict[str, Path]:
        folders = {"deck-pictures": PICTURES_DIR}
        if self.pictures is not None:
            folders["pictures"] = self.pictures
        return folders

    # ------------------------------------------------------------------ test mode
    def on_connect(self, room: Room, conn: Any) -> None:
        if self.test and len(room.members) == 1:
            for _ in range(3):
                room.add_puppet()

    def on_message(self, room: Room, conn: Any, msg: dict[str, Any]) -> bool:
        if not self.test:
            return False
        if msg.get("type") == "test_add":
            room.add_puppet()
            return True
        if msg.get("type") == "test_switch":
            target = room.members.get(str(msg.get("member")))
            if target is None:
                raise RoomError("No such player")
            conn.member_id = target.id
            conn.send({"type": "welcome", "you": target.id, "log": list(room.log)})
            conn.send(room.state_for(target.id))
            return True
        return False


GAME = GameSpec(
    key="codenames",
    title="Codenames",
    tagline="Two teams, one-word clues: find all your agents and never touch the assassin.",
    min_players=4,
    max_players=MAX_MEMBERS,
    bots=False,
    kind="teams",
    minutes="15–30",
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#c0392b",
)
