"""A multiplayer table: members, seats (humans or bots), lobby settings and the game.

All mutations are synchronous and run on the event loop thread. Every change is pushed to each listener as a
full per-viewer snapshot (`Room.state_for`) tagged with the events that caused it, so clients can animate them.
Chronicles of Avel is cooperative and the table is open: only face-down tiles, the stacks and the bag are hidden,
and the engine never puts those into a snapshot.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from avel.bots import BOT_TYPES, DEFAULT_BOT, Bot, HeroBot
from avel.game import actions
from avel.game.actions import Action
from avel.game.engine import HERO_COLORS, Event, Game, IllegalMove, Phase
from avel.game.model import EQUIPMENT_TYPES, MONSTER_TYPES, TILE_TYPES
from boardgames.table import MAX_NAME, Member, RoomError, Table, clean_text

log = logging.getLogger(__name__)

MAX_SEATS = 4
MIN_SEATS = 1
REACTIONS = ("👍", "😂", "😱", "😡", "🎉", "🤔", "😭", "🔥", "👏", "💀")
BOT_SPEEDS = {"slow": 1.8, "normal": 1.0, "fast": 0.4}
TURN_TIMERS = (0, 60, 120, 300)
CRATER_KEYS = ("easy", "moderate", "difficult")

Plan = tuple[float, Callable[[], None]]


@dataclass
class Settings:
    crater: str = "easy"
    turn_timer: int = 0  # seconds per human decision, 0 = off
    bot_speed: str = "normal"
    hints: bool = True

    def update(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "crater" and value in CRATER_KEYS:
                self.crater = str(value)
            elif key == "turn_timer" and value in TURN_TIMERS:
                self.turn_timer = int(value)
            elif key == "bot_speed" and value in BOT_SPEEDS:
                self.bot_speed = str(value)
            elif key == "hints" and isinstance(value, bool):
                self.hints = value
            else:
                raise RoomError(f"invalid setting {key}={value!r}")


@dataclass
class Seat:
    name: str
    member_id: str | None = None  # None: a bot
    bot: str | None = None  # BOT_TYPES key
    agent: Bot | None = None
    autoplay: bool = False  # a human seat temporarily played by the autopilot

    @property
    def is_bot(self) -> bool:
        return self.member_id is None


def bots_public() -> list[dict[str, Any]]:
    return [
        {"key": b.key, "label": b.label, "stars": b.stars, "description": b.description} for b in BOT_TYPES.values()
    ]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _item_name(key: str) -> str:
    return EQUIPMENT_TYPES[key].name


def _monster_name(key: str) -> str:
    return MONSTER_TYPES[key].name


class Room(Table):
    MAX_SEATS = MAX_SEATS
    REACTIONS = REACTIONS

    def __init__(self, room_id: str, delay_scale: float = 1.0, seed: int | None = None) -> None:
        super().__init__(room_id, delay_scale, seed, log_size=500)
        self.settings = Settings()
        self.game: Game | None = None
        self.game_no = 0
        self._autopilot = HeroBot(seed=self.rng.randrange(2**31))
        self._step = 0  # counts game steps so bot delays restart after each one
        self._decision = 0  # counts changes of the deciding seat, for the turn timer

    # ------------------------------------------------------------------ members
    def _new_seat(self, member: Member) -> Seat:
        return Seat(name=member.name, member_id=member.id)

    def _welcome_extra(self) -> dict[str, Any]:
        return {"bots": bots_public()}

    def _lineup(self) -> str:
        return ", ".join(f"{s.name} (bot)" if s.is_bot else s.name for s in self.seats) or "nobody seated"

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
        host_only = {"add_bot", "remove_seat", "settings", "start", "play_again", "to_lobby", "autoplay", "shuffle"}
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
                self._add_bot(str(msg.get("bot") or DEFAULT_BOT))
            case "remove_seat":
                self._remove_seat(msg.get("seat"))
            case "shuffle":
                self._require_lobby()
                self.rng.shuffle(self.seats)
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
            case "hint":
                return self._hint(member)
            case _:
                raise RoomError(f"unknown request {kind!r}")
        return None

    def _rename(self, member: Member, name: str) -> None:
        log.info("table %s: %s is now called %s", self.id, member.name, name)
        self._say(f"{member.name} is now called {name}")
        member.name = name
        seat = self.seat_of(member.id)
        if seat is not None:
            self.seats[seat].name = name
            if self.game is not None:
                self.game.heroes[seat].name = name

    def _sit(self, member: Member) -> None:
        self._require_lobby()
        if self.seat_of(member.id) is not None:
            return
        if len(self.seats) >= MAX_SEATS:
            raise RoomError("The table is full")
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
        bot = BOT_TYPES.get(key)
        if bot is None:
            raise RoomError("Unknown bot")
        if len(self.seats) >= MAX_SEATS:
            raise RoomError("The table is full")
        names = {s.name for s in self.seats}
        name, n = bot.label, 1
        while name in names:
            n += 1
            name = f"{bot.label} {n}"
        self.seats.append(Seat(name=name, bot=key))
        self._emit({"kind": "lobby"})

    def _remove_seat(self, seat: object) -> None:
        self._require_lobby()
        if not isinstance(seat, int) or not 0 <= seat < len(self.seats):
            raise RoomError("No such seat")
        del self.seats[seat]
        self._emit({"kind": "lobby"})

    def _set_autoplay(self, seat: object, on: bool) -> None:
        if self.status != "playing" or not isinstance(seat, int) or not 0 <= seat < len(self.seats):
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
        n = len(self.seats)
        if n < MIN_SEATS:
            raise RoomError("Take a seat or add a bot first")
        for seat in self.seats:
            seat.agent = BOT_TYPES[seat.bot].make(self.rng.randrange(2**31)) if seat.bot else None
            seat.autoplay = False
        self.game = Game(
            n, seed=self.rng.randrange(2**63), crater=self.settings.crater, names=[s.name for s in self.seats]
        )
        self.game_no += 1
        self.status = "playing"
        log.info("table %s: game %d started with %s", self.id, self.game_no, self._lineup())
        crater = self.game.crater.name.lower()
        self._say(f"Game {self.game_no} ({crater} crater): {self._lineup()} set out from Avel Castle.")
        self._say(f"🛡 {self.seats[0].name} holds the coat of arms and starts every round.", 0)
        self._emit({"kind": "game_start"})

    def _to_lobby(self) -> None:
        if self.status == "lobby":
            return
        self.status = "lobby"
        self.game = None
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
        return s.is_bot or s.autoplay

    def _agent(self, seat: int) -> Bot:
        return self.seats[seat].agent or self._autopilot

    def _human_action(self, member: Member, data: object) -> None:
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        self._game()
        try:
            action = actions.from_json(data)
        except actions.BadAction as e:
            raise RoomError(str(e)) from None
        if self.seats[seat].autoplay:
            self.seats[seat].autoplay = False
        self._apply(seat, action)

    def _auto_move(self, seat: int) -> None:
        game = self._game()
        self._apply(seat, self._agent(seat).act(game.view(seat)))

    def _apply(self, seat: int, action: Action) -> None:
        game = self._game()
        before = game.actor
        try:
            events = game.step(seat, action)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._step += 1
        if game.actor != before or not events:
            self._decision += 1
        for ev in events:
            self._narrate(ev)
        if game.phase == Phase.GAME_OVER:
            self.status = "game_over"
            self._end_game()
        self._emit({"kind": "move", "seat": seat, "action": actions.to_json(action), "events": events})

    def _name(self, seat: int | None) -> str:
        return self.seats[seat].name if seat is not None and 0 <= seat < len(self.seats) else ""

    def _narrate(self, ev: Event) -> None:
        game = self.game
        assert game is not None
        seat = ev.get("seat")
        name = self._name(seat)
        match ev["kind"]:
            case "reveal":
                t = TILE_TYPES[ev["tile"]["key"]]
                self._say(f"🗺 {name or 'The Black Moon'} uncovered the {t.name}", seat)
            case "spawn":
                m = MONSTER_TYPES[ev["monster"]["key"]]
                self._say(f"👹 A [{m.key}] {m.name} appeared", None)
            case "battle":
                self._say(f"⚔️ {name} attacks the [{ev['key']}] {_monster_name(ev['key'])}", seat)
            case "drink" if ev.get("healed") is not None:
                self._say(f"🧪 {name} drinks a healing elixir (+{ev['healed']})", seat)
            case "drink":
                self._say(f"🧪 {name} drinks the {_item_name(ev['key'])}: +1 {ev['die']} die", seat)
            case "clash":
                parts = []
                if ev["dealt"]:
                    parts.append(f"deals {_plural(ev['dealt'], 'wound')}")
                if ev["taken"]:
                    parts.append(f"takes {_plural(ev['taken'], 'wound')}")
                what = " and ".join(parts) or "trades blows without effect"
                self._say(f"🎲 Clash {ev['clash']}: {name} {what}", seat)
            case "slain" if ev.get("seat") is None:
                self._say(f"💥 The trap finished off the [{ev['key']}] {_monster_name(ev['key'])}!")
            case "slain":
                self._say(f"🏆 {name} defeated the [{ev['key']}] {_monster_name(ev['key'])}!", seat)
            case "reward":
                bits = []
                if ev["coins"]:
                    bits.append(f"{ev['coins']} [coin]")
                bits += [f"[{i['key']}] {_item_name(i['key'])}" for i in ev["items"]]
                if ev["upgrades"]:
                    bits.append(_plural(ev["upgrades"], "upgrade"))
                if bits:
                    self._say(f"🎁 {name} gains {', '.join(bits)}", seat)
            case "battle_end" if ev["outcome"] in ("retreat", "over"):
                self._say(f"🏃 {name} withdraws from the battle", seat)
            case "stunned":
                lost = f" and drops {_plural(ev['coins'], 'coin')}" if ev["coins"] else ""
                self._say(f"💫 {name} is stunned, wakes up in the castle{lost}", seat)
            case "lose":
                self._say(f"{name} loses the [{ev['key']}] {_item_name(ev['key'])}", seat)
            case "rest":
                self._say(f"🏕 {name} rests (+{ev['healed']})", seat)
            case "sell":
                self._say(f"💰 {name} sells the [{ev['key']}] {_item_name(ev['key'])}", seat)
            case "buy":
                self._say(f"🛒 {name} buys the [{ev['key']}] {_item_name(ev['key'])}", seat)
            case "seal":
                self._say(f"🌙 {name} seals a monster lair", seat)
            case "wall":
                self._say(f"🧱 {name} builds a wall fragment ({ev['walls']} standing)", seat)
            case "trap":
                self._say(f"🪤 {name} sets a level {ev['level']} trap", seat)
            case "work":
                self._say(f"🔨 {name} works for {_plural(ev['coins'], 'coin')}", seat)
            case "upgrade":
                self._say(f"✨ {name} upgrades the [{ev['key']}] {_item_name(ev['key'])}", seat)
            case "wish":
                result = {
                    "coins": "4 coins",
                    "equipment": "an equipment token",
                    "upgrade": "an upgrade",
                    None: "nothing",
                }[ev["outcome"]]
                self._say(f"🪙 {name} tosses a coin into the lake: {result}", seat)
            case "discard" if ev.get("key"):
                self._say(f"{name} puts the [{ev['key']}] {_item_name(ev['key'])} back in the bag", seat)
            case "transfer" if ev.get("key"):
                self._say(
                    f"🤝 {self._name(ev['frm'])} hands the [{ev['key']}] {_item_name(ev['key'])} "
                    f"to {self._name(ev['to'])}",
                    ev["frm"],
                )
            case "transfer":
                self._say(
                    f"🤝 {self._name(ev['frm'])} hands {_plural(ev['coins'], 'coin')} to {self._name(ev['to'])}",
                    ev["frm"],
                )
            case "moon":
                text = {
                    "spawn": "monsters gather in their empty lairs",
                    "heal": "every hero heals 1",
                    "black_moon": "the Black Moon rises!",
                }.get(ev["symbol"], "")
                self._say(f"🌘 The astrolabe moves on: {text}")
            case "beast":
                self._say("🐲 The Beast crawls out of the crater. Every monster marches on the castle!")
            case "crater_roll":
                pass
            case "march":
                self._say("👣 The monsters march towards the castle")
            case "wall_broken":
                self._say(f"🧱 The {_monster_name(ev['key'])} smashes {_plural(ev['broken'], 'wall fragment')}")
            case "trap_sprung":
                self._say(f"🪤 The Beast walks into a trap and takes {_plural(ev['damage'], 'wound')}!")
            case "castle_falls":
                self._say(f"🏰 The {_monster_name(ev['key'])} breaks into Avel Castle!")
            case "round":
                self._say(f"— Round {ev['round']} —")

    def _end_game(self) -> None:
        game = self.game
        assert game is not None and game.result is not None
        res = game.result
        log.info("table %s: game %d %s after %d rounds", self.id, self.game_no, res.reason, res.rounds)
        if res.won:
            self._say("🎉 The Beast is slain and Avel is safe. Victory!")
        else:
            self._say("☠️ The Healing Jewel is lost. Defeat.")

    # ------------------------------------------------------------------ hints
    def _hint(self, member: Member) -> dict[str, Any]:
        if not self.settings.hints:
            raise RoomError("Hints are turned off at this table")
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        game = self._game()
        if game.actor != seat:
            raise RoomError("It's not your move")
        action = self._autopilot.act(game.view(seat))
        return {"type": "hint", "action": actions.to_json(action)}

    # ------------------------------------------------------------------ automation

    def plan(self) -> Plan | None:
        """The next automatic step as (seconds to wait, action), or None to wait for a human."""
        if self.status != "playing" or self.game is None:
            return None
        game = self.game
        actor = game.actor
        if actor is None:
            return None
        if self._is_auto(actor):
            base = {
                Phase.TURN: 0.9,
                Phase.PREPARE: 0.8,
                Phase.CLASH: 1.4,
                Phase.AFTER_CLASH: 0.9,
                Phase.CHOOSE_UPGRADE: 0.9,
                Phase.OVERFLOW: 0.7,
                Phase.STUN_LOSS: 1.0,
                Phase.STEER: 0.9,
            }.get(game.phase, 0.8)
            delay = self._wait(("move", self.game_no, self._step), base * BOT_SPEEDS[self.settings.bot_speed])
            return delay, lambda s=actor: self._auto_move(s)
        if self._deadline is not None:
            return max(0.0, self._deadline[1] - time.monotonic()), self._timeout
        return None

    def _refresh_deadline(self) -> None:
        timer = self.settings.turn_timer
        key: tuple[Any, ...] | None = None
        game = self.game
        playing = timer and self.status == "playing" and game is not None and game.actor is not None
        if playing and not self._is_auto(game.actor):
            key = ("decide", self.game_no, game.round, game.current, game.actor)
        if key is None:
            self._deadline = None
        elif self._deadline is None or self._deadline[0] != key:
            self._deadline = (key, time.monotonic() + timer)

    def _timeout(self) -> None:
        game = self._game()
        seat = game.actor
        if seat is None:
            return
        self._say(f"⏱ {self.seats[seat].name} ran out of time; the autopilot takes over this turn")
        current, rnd = game.current, game.round
        guard = 0
        while self.status == "playing" and game.actor == seat and game.current == current and game.round == rnd:
            self._auto_move(seat)
            guard += 1
            if guard > 400:
                break

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
                    "color": HERO_COLORS[i] if i < len(HERO_COLORS) else "stone",
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
        state = game.to_json()
        actor = game.actor
        mine = (
            you is not None
            and actor == you
            and self.status == "playing"
            and not self.seats[you].autoplay
            and not self.seats[you].is_bot
        )
        state["legal"] = [actions.to_json(a) for a in game.legal_actions(you)] if mine else []
        state["time_left"] = None
        if self._deadline is not None:
            state["time_left"] = round(max(0.0, self._deadline[1] - time.monotonic()), 2)
            state["time_total"] = self.settings.turn_timer
        return state


__all__ = ["MAX_SEATS", "Room", "RoomError", "bots_public"]
