"""A Marble Sumo table: members, two seats (humans or bots), lobby settings and the match.

All mutations are synchronous and run on the event loop thread; bots think in a worker thread on an immutable
`View` and their move is applied back on the loop. Every change is pushed to each listener as a full snapshot
(`state_for`) tagged with the events that caused it, so clients can animate them. Seat 0 plays Black (moves first),
seat 1 White. The game has no hidden information.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from dataclasses import dataclass
from typing import Any

from boardgames.table import MAX_NAME, Member, RoomError, Table, clean_text
from sumo.bots import REGISTRY, Bot, SearchBot
from sumo.game.board import DEFAULT_LAYOUT, LAYOUTS, public_board
from sumo.game.engine import MARBLES, SIDE_NAMES, TO_WIN, BadAction, Event, Game, IllegalMove, Move

log = logging.getLogger(__name__)

MAX_SEATS = 2
BOT_SPEEDS = {"slow": 1.7, "normal": 1.0, "fast": 0.45}
TURN_TIMERS = (0, 30, 60, 120, 300)
MOVE_LIMITS = (0, 50, 100, 150)
RANDOM_LAYOUT = "random"
SEAT_COLORS = ("black", "white")


@dataclass
class Settings:
    layout: str = DEFAULT_LAYOUT  # a layout key or "random"
    move_limit: int = 0  # moves per player, 0 = play until six are out
    turn_timer: int = 0  # seconds per human move, 0 = off
    bot_speed: str = "normal"

    def update(self, changes: dict[str, Any]) -> None:
        """All or nothing: an invalid entry leaves every setting unchanged."""
        trial = dataclasses.replace(self)
        trial._apply(changes)
        self.__dict__.update(trial.__dict__)

    def _apply(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "layout" and isinstance(value, str) and (value in LAYOUTS or value == RANDOM_LAYOUT):
                self.layout = value
            elif key == "move_limit" and value in MOVE_LIMITS and not isinstance(value, bool):
                self.move_limit = int(value)
            elif key == "turn_timer" and value in TURN_TIMERS and not isinstance(value, bool):
                self.turn_timer = int(value)
            elif key == "bot_speed" and value in BOT_SPEEDS:
                self.bot_speed = str(value)
            else:
                raise RoomError(f"invalid setting {key}={value!r}")


@dataclass
class Seat:
    name: str
    member_id: str | None = None  # None: a bot
    bot: str | None = None  # REGISTRY key
    agent: Bot | None = None
    autoplay: bool = False  # a human seat temporarily played by the autopilot

    @property
    def is_bot(self) -> bool:
        return self.member_id is None


def bots_public() -> list[dict[str, Any]]:
    return [{"key": b.key, "label": b.label, "stars": b.stars, "description": b.description} for b in REGISTRY.values()]


class Room(Table):
    MAX_SEATS = MAX_SEATS

    def __init__(
        self, room_id: str, delay_scale: float = 1.0, seed: int | None = None, bot_budget: float = 1.5
    ) -> None:
        super().__init__(room_id, delay_scale, seed)
        self.settings = Settings()
        self.game: Game | None = None
        self.game_no = 0
        self.bot_budget = bot_budget
        self._autopilot: Bot = SearchBot(self.rng.randrange(2**31), depth=2, spread=4)
        self._step = 0  # counts game steps: a bot's thought is thrown away if the game moved on meanwhile
        self._timed_out: tuple[int, int] | None = None  # (game_no, turn): the autopilot makes that move
        self.busy_until = 0.0

    # ------------------------------------------------------------------ members
    def _new_seat(self, member: Member) -> Seat:
        return Seat(name=member.name, member_id=member.id)

    def _welcome_extra(self) -> dict[str, Any]:
        return {"bots": bots_public()}

    def _lineup(self) -> str:
        return " vs ".join(f"{s.name} (bot)" if s.is_bot else s.name for s in self.seats) or "nobody seated"

    def describe(self) -> str:
        host = self.members.get(self.host_id or "")
        online = sum(1 for m in self.members.values() if m.connections)
        parts = [self.id, self.status.replace("_", " "), f"host {host.name if host else '-'}", self._lineup()]
        parts.append(f"{online} online")
        return " · ".join(parts)

    # ------------------------------------------------------------------ requests
    def handle(self, member_id: str, msg: dict[str, Any]) -> dict[str, Any] | None:
        member = self.members[member_id]
        kind = msg.get("type")
        self.last_activity = time.monotonic()
        host_only = {"add_bot", "remove_seat", "settings", "start", "play_again", "to_lobby", "autoplay", "swap"}
        if kind in host_only and member_id != self.host_id:
            raise RoomError("Only the host can do that")
        match kind:
            case "rename":
                name = clean_text(msg.get("name"), MAX_NAME)
                if name:
                    self._rename(member, name)
                    self._emit({"kind": "presence"})
            case "chat":
                self._chat(member, msg.get("text"))
            case "react":
                self._react(member, msg.get("emoji"))
            case "sit":
                self._sit(member)
            case "stand":
                self._stand(member)
            case "add_bot":
                self._add_bot(str(msg.get("bot")))
            case "remove_seat":
                self._remove_seat(msg.get("seat"))
            case "swap":
                self._require_lobby()
                self.seats.reverse()
                self._emit({"kind": "lobby"})
            case "settings":
                self._require_lobby()
                changes = msg.get("changes")
                if not isinstance(changes, dict):
                    raise RoomError("invalid settings")
                self.settings.update(changes)
                self._emit({"kind": "lobby"})
            case "start" | "play_again":
                self.start()
            case "to_lobby":
                self._to_lobby()
            case "action":
                self._human_action(member, msg.get("action"))
            case "resign":
                self._resign(member)
            case "autoplay":
                self._set_autoplay(msg.get("seat"), bool(msg.get("on")))
            case _:
                raise RoomError(f"unknown request {kind!r}")
        return None

    def _sit(self, member: Member) -> None:
        self._require_lobby()
        if self.seat_of(member.id) is not None:
            return
        if len(self.seats) >= MAX_SEATS:
            raise RoomError("Both seats are taken")
        self.seats.append(Seat(name=member.name, member_id=member.id))
        self._emit({"kind": "lobby"})

    def _stand(self, member: Member) -> None:
        self._require_lobby()
        seat = self.seat_of(member.id)
        if seat is not None:
            del self.seats[seat]
            self._emit({"kind": "lobby"})

    def _add_bot(self, key: str) -> None:
        self._require_lobby()
        bot = REGISTRY.get(key)
        if bot is None:
            raise RoomError("Unknown bot")
        if len(self.seats) >= MAX_SEATS:
            raise RoomError("Both seats are taken")
        names = {s.name for s in self.seats}
        name, n = bot.label, 1
        while name in names:
            n += 1
            name = f"{bot.label} {n}"
        self.seats.append(Seat(name=name, bot=key))
        self._emit({"kind": "lobby"})

    def _remove_seat(self, seat: object) -> None:
        self._require_lobby()
        if not isinstance(seat, int) or isinstance(seat, bool) or not 0 <= seat < len(self.seats):
            raise RoomError("No such seat")
        del self.seats[seat]
        self._emit({"kind": "lobby"})

    def _set_autoplay(self, seat: object, on: bool) -> None:
        if self.status != "playing" or not isinstance(seat, int) or isinstance(seat, bool):
            raise RoomError("No such seat")
        if not 0 <= seat < len(self.seats):
            raise RoomError("No such seat")
        target = self.seats[seat]
        if target.is_bot:
            raise RoomError("That seat is already a bot")
        member = self.members[target.member_id or ""]
        if on and member.connections:
            raise RoomError(f"{target.name} is still connected")
        target.autoplay = on
        self._say(f"The autopilot plays for {target.name}" if on else f"{target.name} plays again")
        self._emit({"kind": "presence"})

    # ------------------------------------------------------------------ game flow
    def start(self) -> None:
        if self.status == "playing":
            raise RoomError("A game is already running")
        if len(self.seats) < MAX_SEATS:
            raise RoomError("Two players are needed: invite someone or add a bot")
        for seat in self.seats:
            seed = self.rng.randrange(2**31)
            seat.agent = REGISTRY[seat.bot].make(seed, budget=self.bot_budget) if seat.bot else None
            seat.autoplay = False
        layout = self.settings.layout
        if layout == RANDOM_LAYOUT:
            layout = self.rng.choice(sorted(LAYOUTS))
        self.game = Game(layout, move_limit=self.settings.move_limit)
        self.game_no += 1
        self._step += 1
        self._timed_out = None
        self.status = "playing"
        log.info("table %s: game %d started (%s): %s", self.id, self.game_no, layout, self._lineup())
        limit = f" · {self.settings.move_limit} moves each" if self.settings.move_limit else ""
        self._say(f"⚫ Game {self.game_no}, {LAYOUTS[layout].name} opening: {self._lineup()}{limit}")
        self._say(f"Push {TO_WIN} rival marbles off the ring to win. {self.seats[0].name} (Black) moves first.", 0)
        self._emit({"kind": "game_start"})

    def _to_lobby(self) -> None:
        if self.status == "lobby":
            return
        self.status = "lobby"
        self.game = None
        self._step += 1
        for seat in self.seats:
            seat.agent = None
            seat.autoplay = False
        for member in self.members.values():
            if member.connections and self.seat_of(member.id) is None and len(self.seats) < MAX_SEATS:
                self.seats.append(Seat(name=member.name, member_id=member.id))
        self._say("Back to the lobby")
        self._emit({"kind": "lobby"})

    def _game(self) -> Game:
        if self.game is None or self.status != "playing":
            raise RoomError("No game in progress")
        return self.game

    def _is_auto(self, seat: int) -> bool:
        s = self.seats[seat]
        if s.is_bot or s.autoplay:
            return True
        game = self.game
        return game is not None and self._timed_out == (self.game_no, game.turn) and game.current == seat

    def _agent(self, seat: int) -> Bot:
        s = self.seats[seat]
        return s.agent if s.is_bot and s.agent is not None else self._autopilot

    def _human_action(self, member: Member, data: object) -> None:
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        game = self._game()
        if game.current != seat:
            raise RoomError("It's not your turn")
        if self._is_auto(seat) and not self.seats[seat].autoplay:
            raise RoomError("Time is up: the autopilot makes this move")
        try:
            move = Move.from_json(data)
        except BadAction as e:
            raise RoomError(str(e)) from None
        if self.seats[seat].autoplay:
            self.seats[seat].autoplay = False
        self._apply(seat, move)

    def _resign(self, member: Member) -> None:
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        game = self._game()
        events = game.resign(seat)
        self._finish(seat, events)

    def _apply(self, seat: int, move: Move) -> None:
        game = self._game()
        try:
            events = game.step(seat, move)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._finish(seat, events)

    def _finish(self, seat: int, events: list[Event]) -> None:
        game = self._game()
        self._step += 1
        for ev in events:
            self._narrate(ev)
        if game.over:
            self.status = "game_over"
        self.busy_until = time.monotonic() + self._animation_time(events) * self.delay_scale
        self._emit({"kind": "move", "seat": seat, "events": events})

    @staticmethod
    def _animation_time(events: list[Event]) -> float:
        """Roughly how long the browsers animate these events (bots wait for them)."""
        t = 0.0
        for ev in events:
            if ev["kind"] == "move":
                t += 0.45 + (0.7 if ev["out"] is not None else 0.0)
        return t

    # ------------------------------------------------------------------ narration
    def _name(self, seat: int | None) -> str:
        return self.seats[seat].name if seat is not None and 0 <= seat < len(self.seats) else ""

    def _narrate(self, ev: Event) -> None:
        seat = ev.get("seat")
        name = self._name(seat)
        game = self.game
        assert game is not None
        match ev["kind"]:
            case "move":
                n = len(ev["marbles"])
                pushed = len(ev["pushed"])
                if ev["out"] is not None:
                    assert seat is not None
                    lost = game.out[1 - seat]
                    self._say(
                        f"💥 {name} pushes a {SIDE_NAMES[1 - seat].lower()} marble out of the ring "
                        f"({lost} of {TO_WIN})",
                        seat,
                    )
                elif pushed:
                    self._say(f"{name} pushes {pushed} with {n}", seat)
            case "resign":
                self._say(f"🏳 {name} resigns", seat)
            case "game_over":
                winner = ev["winner"]
                out = ev["out"]
                if winner is None:
                    self._say(f"🤝 Move limit reached with {out[0]} to {out[1]} marbles out: a draw")
                    log.info("table %s: game %d drawn", self.id, self.game_no)
                    return
                reason = {
                    "push": f"pushes out the {TO_WIN}th marble",
                    "resign": "wins by resignation",
                    "limit": f"lost fewer marbles ({out[winner]} to {out[1 - winner]}) by the move limit",
                }[ev["reason"]]
                log.info("table %s: game %d won by %s (%s)", self.id, self.game_no, self._name(winner), ev["reason"])
                self._say(f"🏆 {self._name(winner)} {reason} and wins!", winner)

    # ------------------------------------------------------------------ automation
    def _bot_turn(self) -> int | None:
        if self.status != "playing" or self.game is None or self.game.over:
            return None
        seat = self.game.current
        return seat if self._is_auto(seat) else None

    def _bot_delay(self) -> float:
        return 0.6 * BOT_SPEEDS[self.settings.bot_speed] * self.delay_scale

    async def drive(self) -> None:
        """Run bot moves and turn timeouts until the room is closed. Bots think in a thread while browsers animate."""
        while not self.closed:
            self._wake.clear()
            seat = self._bot_turn()
            if seat is None:
                deadline = self._deadline
                if deadline is None:
                    await self._wake.wait()
                    continue
                wait = deadline[1] - time.monotonic()
                if wait > 0:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._wake.wait(), wait)
                    continue
                self._timeout()
                continue
            game = self.game
            assert game is not None
            step = self._step
            ready_at = max(self.busy_until, time.monotonic()) + self._bot_delay()
            view = game.view()
            try:
                move = await asyncio.to_thread(self._agent(seat).act, view)
            except Exception:
                log.exception("room %s: bot failed", self.id)
                self._crashed()
                continue
            while (wait := ready_at - time.monotonic()) > 0 and self._step == step and not self.closed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), wait)
                self._wake.clear()
            if self._step != step or self.game is not game or self.closed or self._bot_turn() != seat:
                continue
            try:
                self._apply(seat, move)
            except RoomError:
                log.exception("room %s: bot chose an illegal move", self.id)
                self._crashed()
            await asyncio.sleep(0)

    def step_bots(self, limit: int = 10_000) -> None:
        """Play all pending automatic moves synchronously (tests and scripted demos)."""
        for _ in range(limit):
            seat = self._bot_turn()
            if seat is None:
                return
            game = self.game
            assert game is not None
            self._apply(seat, self._agent(seat).act(game.view()))

    def _refresh_deadline(self) -> None:
        """With a turn timer, each human move gets its own deadline (counted from when the table is ready)."""
        timer = self.settings.turn_timer
        game = self.game
        key: tuple[Any, ...] | None = None
        if timer and self.status == "playing" and game is not None and not self._is_auto(game.current):
            key = (self.game_no, self._step, game.current)
        if key is None:
            self._deadline = None
        elif self._deadline is None or self._deadline[0] != key:
            self._deadline = (key, max(self.busy_until, time.monotonic()) + timer)

    def _timeout(self) -> None:
        game = self.game
        self._deadline = None
        if game is None or self.status != "playing":
            return
        seat = game.current
        self._timed_out = (self.game_no, game.turn)
        self._say(f"⏱ {self.seats[seat].name} ran out of time; the autopilot moves", seat)
        self._emit({"kind": "presence"})

    # ------------------------------------------------------------------ output
    def state_for(self, member_id: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
        you = self.seat_of(member_id)
        seats = []
        for i, s in enumerate(self.seats):
            member = self.members.get(s.member_id or "")
            seats.append(
                {
                    "seat": i,
                    "name": s.name,
                    "member": s.member_id,
                    "bot": s.bot,
                    "color": SEAT_COLORS[i],
                    "connected": True if member is None else member.connections > 0,
                    "autoplay": s.autoplay,
                }
            )
        seated = {s.member_id for s in self.seats}
        spectators = [
            {"member": m.id, "name": m.name, "connected": m.connections > 0}
            for m in self.members.values()
            if m.id not in seated
        ]
        return {
            "type": "state",
            "seq": self.seq,
            "event": event,
            "room": self.id,
            "status": self.status,
            "host": self.host_id,
            "you": {"member": member_id, "seat": you},
            "settings": dataclasses.asdict(self.settings),
            "seats": seats,
            "spectators": spectators,
            "game": self._game_state(you),
        }

    def _game_state(self, you: int | None) -> dict[str, Any] | None:
        game = self.game
        if game is None:
            return None
        mine = you is not None and you == game.current and not self._is_auto(you) and self.status == "playing"
        state: dict[str, Any] = {
            "layout": game.layout,
            "cells": list(game.cells),
            "ids": list(game.ids),
            "out": list(game.out),
            "lost": [list(x) for x in game.lost],
            "current": None if game.over else game.current,
            "turn": game.turn,
            "move_limit": game.move_limit,
            "last": game.last,
            "legal": [m.to_json() for m in game.legal_moves()] if mine else [],
            "result": {"winner": game.result.winner, "reason": game.result.reason, "out": list(game.result.out)}
            if game.result
            else None,
            "time_left": None,
        }
        if self._deadline is not None:
            state["time_left"] = round(max(0.0, self._deadline[1] - time.monotonic()), 2)
            state["time_total"] = self.settings.turn_timer
        return state


def catalogue() -> dict[str, Any]:
    """Static game data the client needs to draw and explain things."""
    return {
        "bots": bots_public(),
        "board": public_board(),
        "layouts": [lay.public() for lay in LAYOUTS.values()],
        "default_layout": DEFAULT_LAYOUT,
        "marbles": MARBLES,
        "to_win": TO_WIN,
        "sides": list(SIDE_NAMES),
        "max_seats": MAX_SEATS,
        "turn_timers": list(TURN_TIMERS),
        "move_limits": list(MOVE_LIMITS),
        "bot_speeds": list(BOT_SPEEDS),
        "reactions": list(Room.REACTIONS),
    }


__all__ = ["MAX_SEATS", "Room", "RoomError", "bots_public", "catalogue"]
