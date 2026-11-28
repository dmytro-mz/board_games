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

Everything here is synchronous and runs on the event loop thread, like the rest of a room. The one exception is a
bot's thinking: `think(key, compute)` inside `plan()` or a step runs `compute` in a worker thread when the room is
driven by `drive()`, so a slow bot never stalls the other rooms (called directly, e.g. in tests, it computes inline).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import multiprocessing
import os
import random
import secrets
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any, Protocol

from boardgames import worker

MAX_NAME = 20
MAX_CHAT = 240
CHAT_INTERVAL = 0.4
REACTIONS = ("👍", "😂", "😱", "😡", "🎉", "🤔", "😭", "🔥", "👏", "🙈")

Plan = tuple[float, Callable[[], None]]


class _Pending(Exception):
    """`think` needs `compute()` run off the event loop before the step can go on."""

    def __init__(self, key: tuple[Any, ...], compute: Callable[[], Any]) -> None:
        self.key = key
        self.compute = compute


# ---------------------------------------------------------------------- bots that think for whole seconds
# Search bots with a time budget (Avenue, Sumo, Toy Battle) burn a full core for a second or more per move. In a
# thread they hold the GIL against the event loop, so every message of every room waits (tens of ms per message,
# measured) and several of them share one core, each searching less. In a worker process each gets its own core and
# the loop stays free; the bot object travels both ways, so its random generator continues exactly as in-process.
POOL_IDLE = 120.0  # seconds without bot work before the worker processes exit (they come back on demand)
_pool: ProcessPoolExecutor | None = None
_pool_busy = 0
_pool_last = 0.0
_warming: Any = None  # the prewarm task's future while the first worker boots
_pool_log = logging.getLogger("boardgames.table")


def _pool_get() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        workers = max(1, min(8, (os.cpu_count() or 2) - 1))
        _pool = ProcessPoolExecutor(
            workers,
            mp_context=multiprocessing.get_context("spawn"),  # a clean interpreter: no forked event loop or sockets
            initializer=worker.watch_owner,
            initargs=(os.getpid(),),
        )
    return _pool


def shutdown_bots() -> None:
    """Stop the worker processes (the server is shutting down)."""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def _pool_idle_check() -> None:
    if _pool is not None and _pool_busy == 0 and time.monotonic() - _pool_last >= POOL_IDLE:
        shutdown_bots()


async def think_apart(agent: Any, method: str, *args: Any) -> tuple[Any, Any]:
    """`agent.<method>(*args)` in a worker process. Returns (result, the agent as it is after thinking): the room
    keeps that copy in place of the original (`Table._keep_agent`). Falls back to a thread if processes fail."""
    global _pool, _pool_busy, _pool_last
    loop = asyncio.get_running_loop()
    _pool_busy += 1
    try:
        if _warming is not None and not _warming.done():  # reuse the worker that is booting, don't start a second
            with contextlib.suppress(Exception):
                await asyncio.wrap_future(_warming)
        try:
            return await loop.run_in_executor(_pool_get(), worker.decide, agent, method, args)
        except (BrokenProcessPool, OSError, RuntimeError) as e:
            _pool_log.warning("bot worker processes failed (%s); thinking in a thread", e)
            _pool = None
            return await asyncio.to_thread(worker.decide, agent, method, args)
    finally:
        _pool_busy -= 1
        _pool_last = time.monotonic()
        loop.call_later(POOL_IDLE + 1, _pool_idle_check)


def prewarm_bots() -> None:
    """A search bot just sat down: start a worker now, so the game's first move doesn't wait for one."""
    global _pool_last, _warming
    if _pool is None:
        with contextlib.suppress(Exception):
            _warming = _pool_get().submit(worker.ready)
            _pool_last = time.monotonic()
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().call_later(POOL_IDLE + 1, _pool_idle_check)


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
        self._offload = False  # inside drive(): think() hands its work to a worker thread
        self._thought: tuple[tuple[Any, ...], Any] | None = None
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

    def think(self, key: tuple[Any, ...], compute: Callable[[], Any]) -> Any:
        """A bot's decision for the game position `key` (the same key always means the same position and seat).

        `compute` must only read what it closed over: build the bot's view before, on the loop. Under `drive()` it
        runs in a worker thread and the driver plans again; the step that asked gets the result when it runs again
        for the same key. Code before `think` in a step must therefore have no side effects."""
        if self._thought is not None and self._thought[0] == key:
            result = self._thought[1]
            self._thought = None
            return result
        if self._offload:
            raise _Pending(key, compute)
        return compute()

    async def _think(self, pending: _Pending) -> None:
        try:
            result = await asyncio.to_thread(pending.compute)
        except Exception:
            self._log.exception("room %s: a bot failed to think", self.id)
            self._crashed()
            return
        self._thought = (pending.key, result)

    def _run(self, fn: Callable[[], Any]) -> Any:
        self._offload = True
        try:
            return fn()
        finally:
            self._offload = False

    async def drive(self) -> None:
        """Run bot moves, timeouts and round transitions (`plan()`) until the room is closed."""
        while not self.closed:
            self._wake.clear()
            try:
                plan = self._run(self.plan)
            except _Pending as pending:
                await self._think(pending)
                continue
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
                self._run(step)
            except _Pending as pending:
                await self._think(pending)
                continue
            except Exception:
                self._log.exception("room %s: automatic step failed", self.id)
                self._crashed()
            await asyncio.sleep(0)

    def _keep_agent(self, old: Any, new: Any) -> None:
        """A bot that thought in a worker process comes back as a copy (`think_apart`): keep it where the original
        was (a seat, or the autopilot)."""
        if new is old:
            return
        for seat in self.seats:
            if getattr(seat, "agent", None) is old:
                seat.agent = new
        if getattr(self, "_autopilot", None) is old:
            self._autopilot = new

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
