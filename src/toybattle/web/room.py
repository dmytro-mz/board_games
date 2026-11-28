"""A Toy Battle table: members, two seats (humans or bots), lobby settings and the match.

All mutations are synchronous and run on the event loop thread; bots think in a worker thread on an immutable
`View` and their action is applied back on the loop. Every change is pushed to each listener as a full per-viewer
snapshot (`state_for`) tagged with the events that caused it, so clients can animate them.

Hidden information: a rack is shown only to its owner (others get its size, how many troops are pinned and the
troops publicly known to be there). The troops drawn from a reserve, and the troop pinned on the Battlefield, are only
shown to the player they belong to. Seat 0 plays Blue, seat 1 plays Red.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from dataclasses import dataclass
from typing import Any

from boardgames.table import MAX_NAME, Member, RoomError, Table, clean_text, prewarm_bots, think_apart
from toybattle.bots import REGISTRY, Bot, GeneralBot
from toybattle.game.engine import Action, BadAction, Event, Game, IllegalMove, Phase
from toybattle.game.terrains import DEFAULT_TERRAIN, TERRAINS
from toybattle.game.troops import KIND_INFO, SIDE_NAMES, kind_of, side_of

log = logging.getLogger(__name__)

MAX_SEATS = 2
BOT_SPEEDS = {"slow": 1.7, "normal": 1.0, "fast": 0.45}
TURN_TIMERS = (0, 30, 60, 90, 180)
RANDOM_TERRAIN = "random"
SEAT_COLORS = ("blue", "red")


@dataclass
class Settings:
    terrain: str = DEFAULT_TERRAIN  # a terrain key or "random"
    special: bool = True  # special base effects (the rules suggest leaving them out of a first game)
    turn_timer: int = 0  # seconds per human decision, 0 = off
    bot_speed: str = "normal"

    def update(self, changes: dict[str, Any]) -> None:
        """All or nothing: an invalid entry leaves every setting unchanged."""
        trial = dataclasses.replace(self)
        trial._apply(changes)
        self.__dict__.update(trial.__dict__)

    def _apply(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "terrain" and isinstance(value, str) and (value in TERRAINS or value == RANDOM_TERRAIN):
                self.terrain = value
            elif key == "special" and isinstance(value, bool):
                self.special = value
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


def troop_tag(troop: int) -> str:
    """Log markup the client renders as a small troop chip: {t:side:kind}."""
    return f"{{t:{side_of(troop)}:{kind_of(troop)}}}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class Room(Table):
    MAX_SEATS = MAX_SEATS

    def __init__(
        self, room_id: str, delay_scale: float = 1.0, seed: int | None = None, bot_budget: float = 1.2
    ) -> None:
        super().__init__(room_id, delay_scale, seed)
        self.settings = Settings()
        self.game: Game | None = None
        self.game_no = 0
        self.bot_budget = bot_budget
        self._autopilot: Bot = GeneralBot(self.rng.randrange(2**31), budget=min(0.5, bot_budget))
        self._step = 0  # counts game steps: a bot's thought is thrown away if the game moved on meanwhile
        self._timed_out: tuple[int, int] | None = None  # (game_no, turn): the autopilot finishes that turn
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
        prewarm_bots()
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
            seat.agent = (
                GeneralBot(self.rng.randrange(2**31), budget=self.bot_budget)
                if seat.bot == "general"
                else REGISTRY[seat.bot].make(self.rng.randrange(2**31))
                if seat.bot
                else None
            )
            seat.autoplay = False
        terrain = self.settings.terrain
        if terrain == RANDOM_TERRAIN:
            terrain = self.rng.choice(sorted(TERRAINS))
        starter = self.rng.randrange(MAX_SEATS)
        self.game = Game(terrain, special=self.settings.special, seed=self.rng.randrange(2**63), starter=starter)
        self.game_no += 1
        self._step += 1
        self._timed_out = None
        self.status = "playing"
        t = self.game.terrain
        log.info("table %s: game %d started on %s: %s", self.id, self.game_no, t.key, self._lineup())
        effects = "" if self.settings.special else " · no special bases"
        self._say(f"🧸 Game {self.game_no} on {t.name}: {self._lineup()}{effects}")
        need = t.objective
        if need[0] == need[1]:
            self._say(f"Capture the enemy H.Q. or collect {need[0]} medals.")
        else:
            self._say(f"Capture an enemy H.Q., or collect medals: Blue needs {need[0]}, Red {need[1]}.")
        self._say(f"{self.seats[starter].name} ({SIDE_NAMES[starter]}) moves first.", starter)
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
            raise RoomError("Time is up: the autopilot finishes this turn")
        try:
            action = Action.from_json(data)
        except BadAction as e:
            raise RoomError(str(e)) from None
        if self.seats[seat].autoplay:
            self.seats[seat].autoplay = False
        self._apply(seat, action)

    def _apply(self, seat: int, action: Action) -> None:
        game = self._game()
        try:
            events = game.step(seat, action)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._step += 1
        for ev in events:
            self._narrate(ev)
        if game.phase == Phase.OVER:
            self.status = "game_over"
        self.busy_until = time.monotonic() + self._animation_time(events) * self.delay_scale
        self._emit({"kind": "move", "seat": seat, "events": events})

    @staticmethod
    def _animation_time(events: list[Event]) -> float:
        """Roughly how long the browsers animate these events (bots wait for them)."""
        t = 0.0
        for ev in events:
            t += {"place": 0.55, "knock": 0.5, "move": 0.5, "recall": 0.45, "medals": 0.9, "draw": 0.4}.get(
                ev["kind"], 0.0
            )
        return t

    # ------------------------------------------------------------------ narration
    def _name(self, seat: int | None) -> str:
        return self.seats[seat].name if seat is not None and 0 <= seat < len(self.seats) else ""

    def _where(self, node: int) -> str:
        game = self.game
        assert game is not None
        n = game.terrain.nodes[node]
        if n.kind == "hq":
            return f"the {SIDE_NAMES[n.side or 0]} H.Q."
        return "a special base" if n.kind == "special" and game.special else "a base"

    def _narrate(self, ev: Event) -> None:
        seat = ev.get("seat")
        name = self._name(seat)
        game = self.game
        assert game is not None
        match ev["kind"]:
            case "draw":
                n = len(ev["troops"])
                if ev["source"] == "action":
                    self._say(f"{name} draws {_plural(n, 'troop')}", seat)
                else:
                    self._say(f"{name} draws {_plural(n, 'more troop')}", seat)
            case "place":
                troop = ev["troop"]
                covered = ev["covered"]
                text = f"{name} places {troop_tag(troop)} on {self._where(ev['node'])}"
                if covered is not None:
                    text += f", covering {troop_tag(covered)}" if side_of(covered) != seat else " (reinforcing)"
                self._say(text, seat)
            case "rally":
                pass
            case "knock":
                self._say(f"💥 {name} knocks {troop_tag(ev['troop'])} off the board", seat)
            case "snatch":
                self._say(f"🧲 {name}'s magnet pulls {troop_tag(ev['troop'])} off the opponent's rack", seat)
            case "pin":
                self._say(f"🪣 {name} buries a troop of {self._name(ev['target'])}'s rack in the sand", seat)
            case "recall":
                self._say(f"{name} takes {troop_tag(ev['troop'])} back to the rack", seat)
            case "revive":
                self._say(f"{name} brings {troop_tag(ev['troop'])} back from the discard", seat)
            case "move":
                self._say(f"{name} pushes {troop_tag(ev['troop'])} to another base", seat)
            case "medals":
                self._say(f"🏅 {name} takes a region: +{_plural(ev['medals'], 'medal')}", seat)
            case "stuck":
                self._say(f"{name} can neither draw nor place a troop: the game ends", seat)
            case "game_over":
                winner = ev["winner"]
                medals = ev["medals"]
                reason = {
                    "hq": "captures the enemy H.Q.",
                    "medals": f"collects {medals[winner]} medals",
                    "stuck": f"wins on medals, {medals[winner]} to {medals[1 - winner]}",
                }[ev["reason"]]
                log.info("table %s: game %d won by %s (%s)", self.id, self.game_no, self._name(winner), ev["reason"])
                self._say(f"🏆 {self._name(winner)} {reason} and wins!", winner)

    # ------------------------------------------------------------------ automation
    def _bot_turn(self) -> int | None:
        if self.status != "playing" or self.game is None or self.game.phase == Phase.OVER:
            return None
        seat = self.game.current
        return seat if self._is_auto(seat) else None

    def _bot_delay(self, game: Game) -> float:
        base = 1.0 if game.phase == Phase.TURN else 0.7
        return base * BOT_SPEEDS[self.settings.bot_speed] * self.delay_scale

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
            ready_at = max(self.busy_until, time.monotonic()) + self._bot_delay(game)
            view = game.view(seat)
            try:
                agent = self._agent(seat)
                action, thought = await think_apart(agent, "act", view)
                self._keep_agent(agent, thought)
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
                self._apply(seat, action)
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
            self._apply(seat, self._agent(seat).act(game.view(seat)))

    def _refresh_deadline(self) -> None:
        """With a turn timer, each human decision gets its own deadline (counted from when the table is ready)."""
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
        self._say(f"⏱ {self.seats[seat].name} ran out of time; the autopilot finishes the turn", seat)
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
        if event is not None and "events" in event:
            event = {**event, "events": [self._filter_event(e, you) for e in event["events"]]}
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

    def _filter_event(self, ev: Event, you: int | None) -> Event:
        """Drawn troops and the troop pinned on the Battlefield are only shown to the player they belong to."""
        kind = ev["kind"]
        if kind == "draw" and ev["seat"] != you:
            return {**ev, "troops": [None] * len(ev["troops"])}
        if kind == "pin" and ev["target"] != you:
            game = self.game
            known = game is not None and ev["troop"] in game.known[ev["target"]]
            return ev if known else {**ev, "troop": None}
        return ev

    def _game_state(self, you: int | None) -> dict[str, Any] | None:
        game = self.game
        if game is None:
            return None
        over = game.phase == Phase.OVER
        racks = []
        for side in range(2):
            rack = game.rack[side]
            known = set(game.known[side])
            visible = over or side == you
            racks.append(
                {
                    "count": len(rack),
                    "pinned_count": len(game.pinned[side]),
                    "troops": list(rack) if visible else sorted(known),
                    "pinned": sorted(game.pinned[side]) if visible else sorted(game.pinned[side] & known),
                    "hidden": 0 if visible else len(rack) - len(known),
                    "known": sorted(known),
                }
            )
        mine = you is not None and you == game.current and not self._is_auto(you) and self.status == "playing"
        state: dict[str, Any] = {
            "terrain": game.terrain_key,
            "special": game.special,
            "phase": game.phase.value,
            "current": None if over else game.current,
            "turn": game.turn,
            "starter": game.starter,
            "stacks": [list(s) for s in game.stacks],
            "racks": racks,
            "reserves": [len(r) for r in game.reserve],
            "removed": [len(r) for r in game.removed],
            "discard": list(game.discard),
            "medals": list(game.medals),
            "objective": list(game.terrain.objective),
            "region_taken": list(game.region_taken),
            "pending": game.pending.to_json() if game.pending else None,
            "queued": [e.to_json() for e in reversed(game.troop_fx)] + [e.to_json() for e in game.base_fx],
            "legal": [a.to_json() for a in game.legal_actions(you)] if mine else [],
            "result": dataclasses.asdict(game.result) if game.result else None,
            "stuck": game.current if game.result and game.result.reason == "stuck" else None,
            "time_left": None,
        }
        if over:
            state["removed_troops"] = [list(r) for r in game.removed]
        if self._deadline is not None:
            state["time_left"] = round(max(0.0, self._deadline[1] - time.monotonic()), 2)
            state["time_total"] = self.settings.turn_timer
        return state


def catalogue() -> dict[str, Any]:
    """Static game data the client needs to draw and explain things."""
    return {
        "bots": bots_public(),
        "terrains": [TERRAINS[k].public() for k in TERRAINS],
        "default_terrain": DEFAULT_TERRAIN,
        "kinds": [dataclasses.asdict(k) for k in KIND_INFO],
        "sides": list(SIDE_NAMES),
        "max_seats": MAX_SEATS,
        "turn_timers": list(TURN_TIMERS),
        "bot_speeds": list(BOT_SPEEDS),
        "reactions": list(Room.REACTIONS),
    }


__all__ = ["MAX_SEATS", "Room", "RoomError", "bots_public", "catalogue"]
