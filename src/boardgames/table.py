"""What every game table shares: members, the host, chat, reactions, the table log and the bot driver loop.

A game's `Room` subclasses `Table` and keeps everything that is about its game: seats, settings, the game flow,
`state_for` snapshots, `plan()` for bots and timers. The host is decided by the platform (`set_host`: always the
party leader), so tables don't hand it over themselves.

Hooks a game provides:
  _new_seat(member)       the seat a member gets when they arrive in the lobby (games with seats)
  _welcome_extra()        extra fields for the welcome message, e.g. {"bots": bots_public()}
  _refresh_deadline()     recompute the turn timer before each snapshot (games with turn timers)
  plan()                  the next automatic step for `drive()`: (seconds to wait, step) or None
  state_for(member_id, event), _to_lobby()

Everything here is synchronous and runs on the event loop thread, like the rest of a room.
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

MAX_NAME = 20
MAX_CHAT = 240
CHAT_INTERVAL = 0.4
REACTIONS = ("👍", "😂", "😱", "😡", "🎉", "🤔", "😭", "🔥", "👏", "🙈")

Plan = tuple[float, Callable[[], None]]


class RoomError(Exception):
    """A rejected request; the message is shown to the user."""


class Listener(Protocol):
    member_id: str

    def send(self, message: dict[str, Any]) -> None: ...


@dataclass
class Member:
    id: str
    token: str
    name: str
    connections: int = 0
    disconnected_at: float | None = None
    last_chat: float = 0.0


def clean_text(text: object, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[:limit]


class Table:
    MAX_SEATS = 0  # games with seats set this
    REACTIONS: tuple[str, ...] = REACTIONS

    def __init__(self, room_id: str, delay_scale: float = 1.0, seed: int | None = None, log_size: int = 400) -> None:
        self.id = room_id
        self.delay_scale = delay_scale
        self.rng = random.Random(seed)
        self.members: dict[str, Any] = {}
        self.seats: list[Any] = []
        self.host_id: str | None = None
        self.status = "lobby"
        self.log: deque[dict[str, Any]] = deque(maxlen=log_size)
        self.listeners: set[Listener] = set()
        self.seq = 0
        self.last_activity = time.monotonic()
        self.closed = False
        self._wake = asyncio.Event()
        self._due: tuple[tuple[Any, ...], float] | None = None
        self._deadline: tuple[tuple[Any, ...], float] | None = None
        self._log = logging.getLogger(type(self).__module__)  # logs under the game's own name

    # ------------------------------------------------------------------ hooks
    def _new_seat(self, member: Member) -> Any:
        raise NotImplementedError

    def _welcome_extra(self) -> dict[str, Any]:
        return {}

    def _refresh_deadline(self) -> None:
        pass

    def plan(self) -> Plan | None:
        return None

    def state_for(self, member_id: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def _to_lobby(self) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------ members
    def join(self, token: str, name: object, origin: str = "") -> Member:
        name = clean_text(name, MAX_NAME)
        member = next((m for m in self.members.values() if m.token == token), None)
        if member is None:
            member = Member(id=secrets.token_hex(4), token=token, name=name or f"Player {len(self.members) + 1}")
            self.members[member.id] = member
            where = f" from {origin}" if origin else ""
            if self.host_id is None:
                self.host_id = member.id
                self._log.info("table %s opened by %s%s", self.id, member.name, where)
            else:
                self._log.info("table %s: %s joined%s", self.id, member.name, where)
            self._say(f"{member.name} joined the table")
            if self.status == "lobby" and len(self.seats) < self.MAX_SEATS:
                self.seats.append(self._new_seat(member))
        elif name and name != member.name:
            self._rename(member, name)
        return member

    def connect(self, listener: Listener) -> None:
        member = self.members[listener.member_id]
        if member.connections == 0 and member.disconnected_at is not None:
            self._log.info("table %s: %s is back", self.id, member.name)
        member.connections += 1
        member.disconnected_at = None
        self.listeners.add(listener)
        self.last_activity = time.monotonic()
        seat = self.seat_of(member.id)
        if seat is not None and self.seats[seat].autoplay:
            self.seats[seat].autoplay = False
            self._say(f"{member.name} is back and takes over from the autopilot")
        listener.send({"type": "welcome", "you": member.id, "log": list(self.log), **self._welcome_extra()})
        self._emit({"kind": "presence"})

    def disconnect(self, listener: Listener) -> None:
        self.listeners.discard(listener)
        member = self.members.get(listener.member_id)
        if member is None:
            return
        member.connections = max(0, member.connections - 1)
        if member.connections == 0:
            member.disconnected_at = time.monotonic()
            self._log.info("table %s: %s left", self.id, member.name)
        self.last_activity = time.monotonic()
        self._emit({"kind": "presence"})

    def set_host(self, member_id: str) -> None:
        """The platform decides who hosts this table: always the party leader."""
        if member_id in self.members and member_id != self.host_id:
            self.host_id = member_id
            self._emit({"kind": "presence"})

    def seat_of(self, member_id: str) -> int | None:
        for i, seat in enumerate(self.seats):
            if seat.member_id == member_id:
                return i
        return None

    @property
    def idle_for(self) -> float:
        return 0.0 if self.listeners else time.monotonic() - self.last_activity

    # ------------------------------------------------------------------ table talk
    def _rename(self, member: Member, name: str) -> None:
        self._log.info("table %s: %s is now called %s", self.id, member.name, name)
        self._say(f"{member.name} is now called {name}")
        member.name = name
        seat = self.seat_of(member.id)
        if seat is not None:
            self.seats[seat].name = name

    def _chat(self, member: Member, text: object) -> None:
        text = clean_text(text, MAX_CHAT)
        if not text:
            return
        now = time.monotonic()
        if now - member.last_chat < CHAT_INTERVAL:
            raise RoomError("Slow down a little")
        member.last_chat = now
        self._append_log({"kind": "chat", "member": member.id, "name": member.name, "text": text})

    def _react(self, member: Member, emoji: object) -> None:
        if emoji not in self.REACTIONS:
            raise RoomError("unknown reaction")
        message = {"type": "react", "member": member.id, "seat": self.seat_of(member.id), "emoji": emoji}
        for listener in list(self.listeners):
            listener.send(message)

    def _require_lobby(self) -> None:
        if self.status != "lobby":
            raise RoomError("Only possible in the lobby")

    # ------------------------------------------------------------------ automation
    def _wait(self, key: tuple[Any, ...], delay: float) -> float:
        now = time.monotonic()
        if self._due is None or self._due[0] != key:
            self._due = (key, now + delay * self.delay_scale)
        return max(0.0, self._due[1] - now)

    async def drive(self) -> None:
        """Run bot moves, timeouts and round transitions (`plan()`) until the room is closed."""
        while not self.closed:
            self._wake.clear()
            plan = self.plan()
            if plan is None:
                await self._wake.wait()
                continue
            delay, step = plan
            if delay > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), delay)
                    continue
                except TimeoutError:
                    pass
            try:
                step()
            except Exception:
                self._log.exception("room %s: automatic step failed", self.id)
                self._crashed()
            await asyncio.sleep(0)

    def _crashed(self) -> None:
        self._say("⚠️ A bot crashed; the game is back in the lobby")
        self._to_lobby()

    def close(self) -> None:
        self.closed = True
        self._wake.set()

    # ------------------------------------------------------------------ output
    def _append_log(self, entry: dict[str, Any]) -> None:
        entry["ts"] = time.time()
        self.log.append(entry)
        for listener in list(self.listeners):
            listener.send({"type": "log", "entry": entry})

    def _say(self, text: str, seat: int | None = None) -> None:
        self._append_log({"kind": "game", "text": text, "seat": seat})

    def _emit(self, event: dict[str, Any]) -> None:
        self._refresh_deadline()
        self.seq += 1
        event["seq"] = self.seq
        for listener in list(self.listeners):
            listener.send(self.state_for(listener.member_id, event))
        self._wake.set()
