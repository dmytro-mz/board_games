"""A multiplayer table: members, seats (humans or bots), lobby settings and the game.

All mutations are synchronous and run on the event loop thread. Every change is pushed to each listener as a full
per-viewer snapshot (`Room.state_for`) tagged with the events that caused it, so clients can animate them. With
closed hands a viewer sees only their own cards, and the cards others draw are hidden (Epidemics stay visible).
Bots always plan with every hand open: they stand for teammates who tell each other what they hold.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boardgames.table import CHAT_INTERVAL, MAX_CHAT, MAX_NAME, Member, RoomError, Table, clean_text
from pandemic.bots import REGISTRY, Bot, Planner
from pandemic.game import actions
from pandemic.game.actions import (
    EVENT_ACTIONS,
    Action,
    Continue,
    Discard,
    DrawCards,
    ForecastOrder,
)
from pandemic.game.engine import Event, Game, IllegalMove, RulesConfig, Step, name
from pandemic.game.model import DIFFICULTIES, EPIDEMIC, EVENT_NAMES, ROLE_NAMES, EventCard, Role

log = logging.getLogger(__name__)

MAX_SEATS = 4
MIN_SEATS = 2
HOLD_MAX = 30.0  # seconds bots wait for a player who opened an event card
HOLD_GRACE = 1.0  # after the card is put back or played: the action may still be on its way
REACTIONS = ("👍", "👏", "🎉", "😱", "😬", "🤔", "😂", "🙏", "💪", "💀")
BOT_SPEEDS = {"slow": 1.8, "normal": 1.0, "fast": 0.45}
ROLE_MODES = ("random", "choose")
LOSS_TEXT = {
    "outbreaks": "The 8th outbreak: the world panics. The team loses.",
    "cubes": "There are no {color} cubes left to place. The team loses.",
    "deck": "The player deck ran out. The team loses.",
}

Plan = tuple[float, Callable[[], None]]


@dataclass
class Settings:
    epidemics: int = 5
    open_hands: bool = True
    roles: str = "random"  # random | choose
    bot_speed: str = "normal"

    def update(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "epidemics" and value in DIFFICULTIES and not isinstance(value, bool):
                self.epidemics = int(value)
            elif key == "open_hands" and isinstance(value, bool):
                self.open_hands = value
            elif key == "roles" and value in ROLE_MODES:
                self.roles = str(value)
            elif key == "bot_speed" and value in BOT_SPEEDS:
                self.bot_speed = str(value)
            else:
                raise RoomError(f"invalid setting {key}={value!r}")


@dataclass
class Seat:
    name: str
    member_id: str | None = None  # None: a bot
    bot: str | None = None  # REGISTRY key
    role: Role | None = None  # picked in the lobby (roles: choose)
    agent: Bot | None = None
    autoplay: bool = False  # a human seat temporarily played by the autopilot

    @property
    def is_bot(self) -> bool:
        return self.member_id is None


def bots_public() -> list[dict[str, Any]]:
    return [{"key": b.key, "label": b.label, "stars": b.stars, "description": b.description} for b in REGISTRY.values()]


def _cubes(n: int, color: str) -> str:
    return f"{n} {color} cube{'' if n == 1 else 's'}"


def _names(cities: list[str]) -> str:
    return ", ".join(name(c) for c in cities)


class Room(Table):
    MAX_SEATS = MAX_SEATS
    REACTIONS = REACTIONS

    def __init__(self, room_id: str, delay_scale: float = 1.0, seed: int | None = None) -> None:
        super().__init__(room_id, delay_scale, seed, log_size=600)
        self.settings = Settings()
        self.game: Game | None = None
        self.open_hands = True  # of the running game
        self.turn_end: list[Event] = []  # events since the current player drew, so a reload can show them
        self.game_no = 0
        self._autopilot = Planner(seed=self.rng.randrange(2**31))
        self._step = 0  # counts game changes so bot delays restart after each one
        self._next: tuple[int, int, Action] | None = None  # (step, seat, action) planned for a bot
        self._asked: tuple[int, set[int]] = (-1, set())  # seats asked for an event reaction at this step
        self._hold: tuple[tuple[int, int], float] = ((-1, -1), 0.0)  # bots pause while a human picks an event
        self._held: tuple[tuple[int, int], set[int]] = ((-1, -1), set())  # seats that paused them at this step

    # ------------------------------------------------------------------ members
    def _new_seat(self, member: Member) -> Seat:
        return Seat(name=member.name, member_id=member.id)

    def _welcome_extra(self) -> dict[str, Any]:
        return {"bots": bots_public()}

    def _crashed(self) -> None:
        self._say("A bot crashed; the game is back in the lobby", tone="bad")
        self._to_lobby()

    def _lineup(self) -> str:
        parts = []
        for i, s in enumerate(self.seats):
            label = f"{s.name} (bot)" if s.is_bot else s.name
            if self.game is not None and self.status != "lobby":
                label += f", {ROLE_NAMES[self.game.roles[i]]}"
            parts.append(label)
        return "; ".join(parts) or "nobody seated"

    def describe(self) -> str:
        """One line for the server console: who is at this table and what it's doing."""
        host = self.members.get(self.host_id or "")
        online = sum(1 for m in self.members.values() if m.connections)
        parts = [self.id, self.status.replace("_", " "), f"host {host.name if host else '-'}", self._lineup()]
        if self.game is not None:
            parts.append(f"turn {self.game.turn}")
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
                self._add_bot(str(msg.get("bot")))
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
            case "pick_role":
                self._pick_role(member, msg.get("seat"), msg.get("role"))
            case "start" | "play_again":
                self.start()
            case "to_lobby":
                self._to_lobby()
            case "action":
                self._human_action(member, msg.get("action"))
            case "undo":
                self._undo(member)
            case "autoplay":
                self._set_autoplay(msg.get("seat"), bool(msg.get("on")))
            case "hold":
                self._set_hold(member, bool(msg.get("on")))
            case _:
                raise RoomError(f"unknown request {kind!r}")
        return None

    def _chat(self, member: Member, text: object) -> None:
        text = clean_text(text, MAX_CHAT)
        if not text:
            return
        now = time.monotonic()
        if now - member.last_chat < CHAT_INTERVAL:
            raise RoomError("Slow down a little")
        member.last_chat = now
        seat = self.seat_of(member.id)
        self._append_log({"kind": "chat", "member": member.id, "seat": seat, "name": member.name, "text": text})

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
        bot = REGISTRY.get(key)
        if bot is None:
            raise RoomError("Unknown bot")
        if len(self.seats) >= MAX_SEATS:
            raise RoomError("The table is full")
        names = {s.name for s in self.seats}
        label, n = bot.label, 1
        while label in names:
            n += 1
            label = f"{bot.label} {n}"
        self.seats.append(Seat(name=label, bot=key))
        self._emit({"kind": "lobby"})

    def _remove_seat(self, seat: object) -> None:
        self._require_lobby()
        if not isinstance(seat, int) or not 0 <= seat < len(self.seats):
            raise RoomError("No such seat")
        del self.seats[seat]
        self._emit({"kind": "lobby"})

    def _pick_role(self, member: Member, seat: object, role: object) -> None:
        self._require_lobby()
        if self.settings.roles != "choose":
            raise RoomError("Roles are dealt at random at this table")
        if not isinstance(seat, int) or not 0 <= seat < len(self.seats):
            raise RoomError("No such seat")
        target = self.seats[seat]
        if target.member_id != member.id and not (target.is_bot and member.id == self.host_id):
            raise RoomError("Pick a role for your own seat")
        if role is None:
            target.role = None
        else:
            try:
                wanted = Role(role)
            except ValueError:
                raise RoomError("Unknown role") from None
            other = next((s for s in self.seats if s is not target and s.role == wanted), None)
            if other is not None:
                raise RoomError(f"{other.name} already plays the {ROLE_NAMES[wanted]}")
            target.role = wanted
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
            raise RoomError("Pandemic needs at least 2 players: invite someone or add a bot")
        for seat in self.seats:
            seat.agent = REGISTRY[seat.bot].make(self.rng.randrange(2**31)) if seat.bot else None
            seat.autoplay = False
        roles = tuple(s.role for s in self.seats) if self.settings.roles == "choose" else None
        rules = RulesConfig(epidemics=self.settings.epidemics, roles=roles)
        self.game = Game(n, seed=self.rng.randrange(2**63), rules=rules)
        self.open_hands = self.settings.open_hands
        self.turn_end = []
        self.game_no += 1
        self.status = "playing"
        self._step += 1
        log.info("table %s: game %d started with %s", self.id, self.game_no, self._lineup())
        level = DIFFICULTIES[self.settings.epidemics]
        hands = "open" if self.open_hands else "closed"
        self._say(f"Game {self.game_no}: {level}, {self.settings.epidemics} Epidemics, {hands} hands.", tone="turn")
        events = self.game.setup_events
        self._narrate_all(events)
        self._emit({"kind": "game_start", "events": events})

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
        return s.is_bot or s.autoplay

    def _agent(self, seat: int) -> Bot:
        return self.seats[seat].agent or self._autopilot

    def _bot_view(self, seat: int) -> Any:
        return self._game().view(seat, open_hands=True)

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

    def _undo(self, member: Member) -> None:
        seat = self.seat_of(member.id)
        game = self._game()
        if seat is None:
            raise RoomError("You are watching this game")
        try:
            events = game.undo(seat)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._step += 1
        self._say(f"{self.seats[seat].name} takes back their last action", seat)
        self._emit({"kind": "move", "seat": seat, "events": events})

    def _apply(self, seat: int, action: Action) -> None:
        game = self._game()
        try:
            events = game.play(seat, action)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._step += 1
        for ev in events:
            if ev["kind"] == "draw":
                self.turn_end = [ev]
            elif ev["kind"] == "turn":
                self.turn_end = []
            elif self.turn_end:
                self.turn_end.append(ev)
        self._narrate_all(events)
        if game.step == Step.GAME_OVER:
            self.status = "game_over"
            self._end_game()
        self._emit({"kind": "move", "seat": seat, "events": events})

    # ------------------------------------------------------------------ narration
    def _name(self, seat: int | None) -> str:
        return self.seats[seat].name if seat is not None and 0 <= seat < len(self.seats) else ""

    def _narrate_all(self, events: list[Event]) -> None:
        setup = [e for e in events if e["kind"] == "infect" and e.get("setup")]
        if setup:
            by_count: dict[int, list[str]] = {}
            for e in setup:
                by_count.setdefault(e["placed"], []).append(e["city"])
            parts = [f"{n} on {_names(cs)}" for n, cs in sorted(by_count.items(), reverse=True)]
            self._say("Setup infections: " + "; ".join(parts) + ".")
        infected: list[str] = []
        for ev in events:
            if ev["kind"] == "infect" and ev.get("setup"):
                continue
            if ev["kind"] in ("infect", "prevented") and not ev.get("via") and not ev.get("epidemic"):
                if ev["kind"] == "prevented":
                    infected.append(f"{name(ev['city'])} (protected)")
                elif ev["outbreak"]:
                    infected.append(f"{name(ev['city'])} (outbreak!)")
                else:
                    infected.append(f"{name(ev['city'])} +{ev['placed']}")
                continue
            if infected and ev["kind"] not in ("outbreak", "infect", "prevented"):
                self._say("Infected: " + ", ".join(infected) + ".")
                infected = []
            self._narrate(ev)
        if infected:
            self._say("Infected: " + ", ".join(infected) + ".")

    def _narrate(self, ev: Event) -> None:
        game = self.game
        assert game is not None
        seat = ev.get("seat")
        who = self._name(seat)
        match ev["kind"]:
            case "setup":
                for i, role in enumerate(ev["roles"]):
                    self._say(f"{self._name(i)} is the {ROLE_NAMES[Role(role)]}", i)
            case "turn":
                self._say(f"Turn {ev['turn']}: {who}", seat, tone="turn")
            case "move":
                pawn = ev["pawn"]
                whose = "" if pawn == seat else f"{self._name(pawn)} "
                to = name(ev["to"])
                text = {
                    "drive": f"{who} drives {whose}to {to}" if whose else f"{who} drives to {to}",
                    "direct": f"{who} flies {whose}directly to {to}",
                    "charter": f"{who} charters a flight {'for ' + whose if whose else ''}to {to}",
                    "shuttle": f"{who} takes {whose or 'a '}shuttle flight to {to}",
                    "dispatch": f"{who} sends {whose}to {to}",
                    "ops": f"{who} flies from the station to {to}, discarding {name(ev['card'] or '')}",
                    "airlift": f"{self._name(pawn)} is airlifted to {to}",
                }[ev["by"]]
                self._say(" ".join(text.split()), seat)
            case "build":
                moved = f" (moved from {name(ev['moved_from'])})" if ev["moved_from"] else ""
                self._say(f"{who} builds a research station in {name(ev['city'])}{moved}", seat)
            case "treat":
                self._say(f"{who} treats {name(ev['city'])}: {_cubes(ev['removed'], ev['color'])} removed", seat)
            case "medic_clear":
                self._say(f"{who} clears {_cubes(ev['removed'], ev['color'])} from {name(ev['city'])}", seat)
            case "share":
                if ev["from"] == seat:
                    self._say(f"{who} gives the {name(ev['card'])} card to {self._name(ev['to'])}", seat)
                else:
                    self._say(f"{who} takes the {name(ev['card'])} card from {self._name(ev['from'])}", seat)
            case "cure":
                self._say(f"{who} discovers the cure for {ev['color']}!", seat, tone="good")
            case "eradicated":
                self._say(f"{str(ev['color']).capitalize()} is eradicated: no more {ev['color']} cubes", tone="good")
            case "take_event":
                self._say(f"{who} stores {EVENT_NAMES[EventCard(ev['card'])]}", seat)
            case "pass":
                self._say(f"{who} ends their actions early", seat)
            case "draw":
                self._say(f"{who} draws 2 player cards", seat)
            case "epidemic":
                self._say(
                    f"Epidemic {ev['number']} of {game.rules.epidemics}! The infection rate is now {ev['rate']}.",
                    tone="bad",
                )
            case "infect" if ev.get("epidemic"):
                if ev["outbreak"]:
                    self._say(f"{name(ev['city'])} gets 3 {ev['color']} cubes and breaks out", tone="bad")
                else:
                    self._say(f"{name(ev['city'])} gets {_cubes(ev['placed'], ev['color'])}", tone="bad")
            case "prevented" if ev.get("epidemic"):
                self._say(f"{name(ev['city'])} is protected from the epidemic")
            case "intensify":
                self._say(f"Intensify: {_names(ev['cities'])} go back on top of the infection deck")
            case "outbreak":
                spread = f": spreads to {_names(ev['to'])}" if ev["to"] else ""
                self._say(f"Outbreak in {name(ev['city'])} ({ev['count']} of 8){spread}", tone="bad")
            case "quiet_night":
                self._say("One Quiet Night: no cities are infected")
            case "event":
                card = EVENT_NAMES[EventCard(ev["card"])]
                where = f" on {name(ev['city'])}" if ev.get("city") else ""
                self._say(f"{who} plays {card}{where}", seat)
            case "forecast":
                self._say(f"{who} looks at the top 6 infection cards", seat)
            case "forecast_done":
                self._say(f"{who} puts the 6 cards back in a new order", seat)
            case "discard":
                self._say(f"{who} discards {name(ev['card'])}", seat)
            case "deck_empty":
                self._say("The player deck can't supply 2 cards", tone="bad")

    def _end_game(self) -> None:
        game = self.game
        assert game is not None and game.result is not None
        res = game.result
        log.info("table %s: game %d %s (%s)", self.id, self.game_no, "won" if res.won else "lost", res.reason)
        if res.won:
            self._say(f"All four cures are found on turn {res.turn}. The team wins!", tone="good")
        else:
            self._say(LOSS_TEXT[res.reason].format(color=res.color), tone="bad")

    # ------------------------------------------------------------------ automation

    def _set_hold(self, member: Member, on: bool) -> None:
        """A player opened an event card (or put it back): bots wait so the board doesn't change under them."""
        seat = self.seat_of(member.id)
        game = self.game
        if seat is None or game is None or self.status != "playing":
            return
        key = (self.game_no, self._step)
        now = time.monotonic()
        if not on:
            if self._hold[0] == key:
                self._hold = (key, min(self._hold[1], now + HOLD_GRACE))
                self._wake.set()
            return
        if self._held[0] != key:
            self._held = (key, set())
        events = {c.value for c in EventCard}
        if seat in self._held[1] or not (set(game.hands[seat]) | {game.stored[seat]}) & events:
            return
        self._held[1].add(seat)
        self._hold = (key, max(self._hold[1] if self._hold[0] == key else 0.0, now + HOLD_MAX))
        self._wake.set()  # the driver may be counting down to a bot move planned before the hold

    def _bot_delay(self, base: float) -> float:
        return base * BOT_SPEEDS[self.settings.bot_speed]

    def _human_holds(self, cards: tuple[str, ...]) -> bool:
        """A connected human could still want to play one of these event cards."""
        game = self.game
        assert game is not None
        for i in range(len(self.seats)):
            if self._is_auto(i):
                continue
            held = set(game.hands[i]) | {game.stored[i]}
            if held.intersection(cards):
                return True
        return False

    def _reaction(self) -> tuple[int, Action] | None:
        """An event a bot wants to play out of turn (Resilient Population, Forecast, One Quiet Night)."""
        game = self._game()
        waiting = game.waiting_for()
        if game.step not in (Step.EPIDEMIC, Step.INFECT) or game.forecast is not None or waiting is None:
            return None
        if game.over_limit() is not None:
            return None
        step, asked = self._asked
        if step != self._step:
            asked = set()
            self._asked = (self._step, asked)
        for i in range(1, game.n):
            seat = (waiting + i) % game.n
            if seat in asked or not self._is_auto(seat):
                continue
            agent, view = self._agent(seat), self._bot_view(seat)
            action = self.think(("react", self.game_no, self._step, seat), lambda a=agent, v=view: a.react(v))
            asked.add(seat)
            if action is not None:
                return seat, action
        return None

    def _planned(self, seat: int) -> Action:
        if self._next is None or self._next[:2] != (self._step, seat):
            agent, view = self._agent(seat), self._bot_view(seat)
            action = self.think(("act", self.game_no, self._step, seat), lambda: agent.act(view))
            self._next = (self._step, seat, action)
        return self._next[2]

    def _auto_move(self, seat: int, action: Action) -> None:
        try:
            self._apply(seat, action)
        except RoomError:
            log.warning("table %s: bot move %r was refused", self.id, action)
            self._step += 1  # plan again from scratch

    def plan(self) -> Plan | None:
        """The next automatic step as (seconds to wait, step), or None to wait for a human."""
        if self.status != "playing" or self.game is None:
            return None
        game = self.game
        held = self._hold[1] - time.monotonic()
        if self._hold[0] == (self.game_no, self._step) and held > 0:
            return held, lambda: None
        if self._next is None or self._next[0] != self._step:
            react = self._reaction()
            if react is not None:
                self._next = (self._step, *react)
        if self._next is not None and self._next[0] == self._step:
            _, seat, action = self._next
        else:
            waiting = game.waiting_for()
            if waiting is None or not self._is_auto(waiting):
                return None
            seat, action = waiting, self._planned(waiting)
        delay = self._wait(("move", self.game_no, self._step), self._pause(action))
        return delay, lambda: self._auto_move(seat, action)

    def _pause(self, action: Action) -> float:
        """Seconds a bot waits before this action; humans get time to play their events, whatever the bot speed."""
        game = self._game()
        if isinstance(action, Continue):
            if game.step == Step.EPIDEMIC:
                return 6.0 if self._human_holds((EventCard.RESILIENT_POPULATION,)) else self._bot_delay(2.2)
            held = (EventCard.FORECAST, EventCard.ONE_QUIET_NIGHT, EventCard.RESILIENT_POPULATION)
            return 4.5 if self._human_holds(held) else self._bot_delay(1.6)
        return self._bot_delay(self._bot_pause(action))

    def _bot_pause(self, action: Action) -> float:
        if isinstance(action, DrawCards):
            return 1.0
        if isinstance(action, (Discard, ForecastOrder)):
            return 1.2
        if isinstance(action, EVENT_ACTIONS):
            return 1.4
        return 0.9

    # ------------------------------------------------------------------ output

    def _say(self, text: str, seat: int | None = None, tone: str | None = None) -> None:
        self._append_log({"kind": "game", "text": text, "seat": seat, "tone": tone})

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
                    "role": s.role.value if s.role else None,
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

    def _sees(self, viewer: int | None, seat: int) -> bool:
        return self.open_hands or viewer == seat

    def _filter_event(self, ev: Event, you: int | None) -> Event:
        if ev["kind"] == "draw" and not self._sees(you, ev["seat"]):
            return {**ev, "cards": [c if c == EPIDEMIC else None for c in ev["cards"]]}
        if ev["kind"] == "forecast" and not self._sees(you, ev["seat"]):
            return {**ev, "cards": []}
        if ev["kind"] == "forecast_done" and not self._sees(you, ev["seat"]):
            return {**ev, "order": []}
        return ev

    def _game_state(self, you: int | None) -> dict[str, Any] | None:
        game = self.game
        if game is None:
            return None
        over = game.over_limit() if game.result is None else None
        mine = you is not None and self.status == "playing" and not self.seats[you].autoplay
        drawn = [c if c == EPIDEMIC or self._sees(you, game.current) else None for c in game.drawn]
        return {
            "step": game.step.value,
            "current": game.current,
            "turn": game.turn,
            "actions_left": game.actions_left,
            "waiting_for": game.waiting_for(),
            "over_limit": over,
            "open_hands": self.open_hands,
            "players": [
                {
                    "role": game.roles[i].value,
                    "location": game.location[i],
                    "hand": list(game.hands[i]) if self._sees(you, i) else None,
                    "count": len(game.hands[i]),
                    "stored": game.stored[i],
                }
                for i in range(game.n)
            ],
            "cubes": {c: {k.value: v for k, v in cc.items() if v} for c, cc in game.cubes.items() if any(cc.values())},
            "supply": {k.value: v for k, v in game.supply.items()},
            "stations": list(game.stations),
            "cures": {k.value: v for k, v in game.cures.items()},
            "outbreaks": game.outbreaks,
            "epidemics": game.rules.epidemics,
            "epidemics_drawn": game.epidemics_drawn,
            "infection_rate": game.infection_rate,
            "player_deck": len(game.player_deck),
            "player_discard": list(game.player_discard),
            "infection_deck": len(game.infection_deck),
            "infection_discard": list(game.infection_discard),
            "removed": list(game.removed),
            "drawn": drawn,
            "turn_end": [self._filter_event(e, you) for e in self.turn_end],
            "quiet_night": game.quiet_night,
            "ops_flight_used": game.ops_flight_used,
            "forecast": (
                {"seat": game.forecast[0], "cards": list(game.forecast[1]) if self._sees(you, game.forecast[0]) else []}
                if game.forecast
                else None
            ),
            "can_undo": bool(mine and you is not None and game.can_undo(you)),
            "result": game.result.to_json() if game.result else None,
            "stats": {k: list(v) for k, v in game.stats.items()},
        }


__all__ = ["MAX_SEATS", "REACTIONS", "Room", "RoomError", "Settings", "bots_public"]
