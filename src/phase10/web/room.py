"""A multiplayer table: members, seats (humans or bots), lobby settings and the game.

All mutations are synchronous and run on the event loop thread. Every change is pushed to each listener as a full
per-viewer snapshot (`Room.state_for`) tagged with the events that caused it, so clients can animate them. A viewer
only ever sees their own hand; cards drawn from the deck are hidden from everyone else.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boardgames.table import MAX_NAME, Member, RoomError, Table, clean_text
from phase10.bots import REGISTRY, Bot, PlannerBot
from phase10.game import actions
from phase10.game.actions import Action, Hit, LayDown
from phase10.game.engine import Event, Game, IllegalMove, RulesConfig, Step
from phase10.game.model import phase_label, phases_public

log = logging.getLogger(__name__)

MAX_SEATS = 6
MIN_SEATS = 2
REACTIONS = ("👍", "😂", "😱", "😡", "🎉", "🤔", "😭", "🔥", "👏", "💀")
BOT_SPEEDS = {"slow": 1.8, "normal": 1.0, "fast": 0.4}
TURN_TIMERS = (0, 30, 60, 90, 180)
GAME_LENGTHS = (10, 5, 3)
SEAT_COLORS = ("coral", "sky", "lime", "gold", "violet", "teal")

Plan = tuple[float, Callable[[], None]]


@dataclass
class Settings:
    turn_timer: int = 0  # seconds per human turn, 0 = off
    bot_speed: str = "normal"
    last_phase: int = 10  # the game ends when someone completes this phase
    skip_cooldown: bool = False  # house rule: a skipped player must play a turn before being skipped again

    def update(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "turn_timer" and value in TURN_TIMERS:
                self.turn_timer = int(value)
            elif key == "bot_speed" and value in BOT_SPEEDS:
                self.bot_speed = str(value)
            elif key == "last_phase" and value in GAME_LENGTHS:
                self.last_phase = int(value)
            elif key == "skip_cooldown" and isinstance(value, bool):
                self.skip_cooldown = value
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


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _card(c: dict[str, Any]) -> str:
    """Log markup the client renders as a little card: [c:red:7], [c:wild], [c:skip]."""
    if c["k"] == "w":
        return "[c:wild]"
    if c["k"] == "s":
        return "[c:skip]"
    return f"[c:{c['c']}:{c['v']}]"


class Room(Table):
    MAX_SEATS = MAX_SEATS
    REACTIONS = REACTIONS

    def __init__(self, room_id: str, delay_scale: float = 1.0, seed: int | None = None) -> None:
        super().__init__(room_id, delay_scale, seed)
        self.settings = Settings()
        self.game: Game | None = None
        self.game_no = 0
        self.ready: set[int] = set()  # seats ready for the next hand
        self._autopilot = PlannerBot(seed=self.rng.randrange(2**31))
        self._step = 0  # counts game steps so bot delays restart after each one
        self._next: tuple[int, Action] | None = None  # the bot move planned for step `_step`

    # ------------------------------------------------------------------ members
    def _new_seat(self, member: Member) -> Seat:
        return Seat(name=member.name, member_id=member.id)

    def _welcome_extra(self) -> dict[str, Any]:
        return {"bots": bots_public()}

    def _lineup(self) -> str:
        return ", ".join(f"{s.name} (bot)" if s.is_bot else s.name for s in self.seats) or "nobody seated"

    def describe(self) -> str:
        """One line for the server console: who is at this table and what it's doing."""
        host = self.members.get(self.host_id or "")
        online = sum(1 for m in self.members.values() if m.connections)
        parts = [self.id, self.status.replace("_", " "), f"host {host.name if host else '-'}", self._lineup()]
        if self.game is not None:
            parts.append(f"hand {self.game.hand_no}")
        parts.append(f"{online} online")
        return " · ".join(parts)

    # ------------------------------------------------------------------ requests
    def handle(self, member_id: str, msg: dict[str, Any]) -> dict[str, Any] | None:
        member = self.members[member_id]
        kind = msg.get("type")
        self.last_activity = time.monotonic()
        host_only = {
            "add_bot",
            "remove_seat",
            "settings",
            "start",
            "play_again",
            "to_lobby",
            "autoplay",
            "shuffle",
        }
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
            case "start" | "play_again":
                self.start()
            case "to_lobby":
                self._to_lobby()
            case "action":
                self._human_action(member, msg.get("action"))
            case "arrange":
                self._arrange(member, msg.get("order"))
            case "ready":
                self._ready(member)
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
            raise RoomError("Phase 10 needs at least 2 players: invite someone or add a bot")
        for seat in self.seats:
            seat.agent = REGISTRY[seat.bot].make(self.rng.randrange(2**31)) if seat.bot else None
            seat.autoplay = False
        rules = RulesConfig(last_phase=self.settings.last_phase, skip_cooldown=self.settings.skip_cooldown)
        self.game = Game(n, seed=self.rng.randrange(2**63), rules=rules)
        self.game_no += 1
        self.status = "playing"
        self.ready = set()
        log.info("table %s: game %d started with %s", self.id, self.game_no, self._lineup())
        length = "all 10 phases" if self.settings.last_phase == 10 else f"phases 1–{self.settings.last_phase}"
        self._say(f"Game {self.game_no} ({length}): {self._lineup()}.")
        if self.settings.skip_cooldown:
            self._say("House rule: a skipped player must play a turn before they can be skipped again")
        events = self.game.deal_events
        for ev in events:
            self._narrate(ev)
        self._emit({"kind": "game_start", "events": events})

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

    def _arrange(self, member: Member, order: object) -> None:
        seat = self.seat_of(member.id)
        game = self._game()
        if seat is None:
            raise RoomError("You are watching this game")
        if not isinstance(order, list) or not all(isinstance(i, int) for i in order):
            raise RoomError("invalid order")
        try:
            game.arrange(seat, order)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        for listener in list(self.listeners):
            if listener.member_id == member.id:
                listener.send(self.state_for(member.id, {"kind": "arrange", "seq": self.seq}))

    def _ready(self, member: Member) -> None:
        seat = self.seat_of(member.id)
        game = self._game()
        if seat is None or game.step != Step.HAND_OVER:
            return
        self.ready.add(seat)
        self._emit({"kind": "ready", "seat": seat})

    def _deal_next(self) -> None:
        game = self._game()
        if game.step != Step.HAND_OVER:
            raise RoomError("The hand isn't over yet")
        self.ready = set()
        events = game.next_hand()
        self._step += 1
        for ev in events:
            self._narrate(ev)
        self._emit({"kind": "move", "seat": None, "events": events})

    def _planned(self, seat: int) -> Action:
        game = self._game()
        if self._next is None or self._next[0] != self._step:
            self._next = (self._step, self._agent(seat).act(game.view(seat)))
        return self._next[1]

    def _auto_move(self, seat: int) -> None:
        self._apply(seat, self._planned(seat))

    def _apply(self, seat: int, action: Action) -> None:
        game = self._game()
        try:
            events = game.play(seat, action)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._step += 1
        for ev in events:
            self._narrate(ev)
        if game.step == Step.GAME_OVER:
            self.status = "game_over"
            self._end_game()
        self._emit({"kind": "move", "seat": seat, "events": events})

    def _name(self, seat: int | None) -> str:
        return self.seats[seat].name if seat is not None and 0 <= seat < len(self.seats) else ""

    def _narrate(self, ev: Event) -> None:
        game = self.game
        assert game is not None
        seat = ev.get("seat")
        name = self._name(seat)
        match ev["kind"]:
            case "deal":
                self._say(f"🃏 Hand {ev['hand']}: {self._name(ev['dealer'])} deals.")
                if not all(ev["active"]):
                    names = " & ".join(self._name(i) for i, on in enumerate(ev["active"]) if on)
                    self._say(f"🤝 Tie-break: only {names} play this hand")
            case "draw" if ev["from"] == "discard":
                self._say(f"{name} takes {_card(ev['card'])} from the discard pile", seat)
            case "reshuffle":
                self._say(f"🔀 The discard pile is shuffled into a new draw pile ({ev['count']} cards)")
            case "lay_down":
                self._say(f"✅ {name} lays down phase {ev['phase']}: {phase_label(ev['phase'])}!", seat)
            case "discard" if ev["target"] is not None:
                self._say(f"⛔ {name} skips {self._name(ev['target'])}", seat)
            case "discard":
                self._say(f"{name} discards {_card(ev['card'])}", seat)
            case "skipped":
                self._say(f"⛔ {name} loses a turn", seat)
            case "out":
                self._say(f"🏁 {name} goes out!", seat)
            case "tiebreak":
                names = " & ".join(self._name(i) for i in ev["seats"])
                self._say(f"🤝 A tie! {names} replay phase {game.rules.last_phase}: the first to go out wins")
            case "dry":
                self._say("The cards ran out: the hand ends without anyone going out")
            case "hand_over":
                res = ev["result"]
                made = [self._name(i) for i, m in enumerate(res["made"]) if m]
                if made:
                    self._say(f"Made their phase: {', '.join(made)}")
                else:
                    self._say("Nobody made their phase this hand")

    def _end_game(self) -> None:
        game = self.game
        assert game is not None and game.result is not None
        res = game.result
        winners = " & ".join(self.seats[w].name for w in res.winners)
        scores = ", ".join(f"{s.name} {p}" for s, p in zip(self.seats, res.scores, strict=True))
        log.info("table %s: game %d won by %s (%s)", self.id, self.game_no, winners, scores)
        self._say(f"🏆 {winners} won the game! Points: {scores}")

    # ------------------------------------------------------------------ automation

    def _bot_delay(self, base: float) -> float:
        return base * BOT_SPEEDS[self.settings.bot_speed]

    def _humans_waited_for(self) -> list[int]:
        out = []
        for i, s in enumerate(self.seats):
            member = self.members.get(s.member_id or "")
            if member is not None and member.connections and not s.autoplay:
                out.append(i)
        return out

    def plan(self) -> Plan | None:
        """The next automatic step as (seconds to wait, action), or None to wait for a human."""
        if self.status != "playing" or self.game is None:
            return None
        game = self.game
        if game.step == Step.HAND_OVER:
            waiting = [i for i in self._humans_waited_for() if i not in self.ready]
            if waiting:
                return None
            base = 1.0 if self._humans_waited_for() else 4.0
            return self._wait(("deal", self.game_no, game.hand_no), base), self._deal_next
        if self._is_auto(game.current):
            action = self._planned(game.current)
            if isinstance(action, LayDown):
                base = 1.4
            elif isinstance(action, Hit):
                base = 0.7
            else:
                base = 0.9
            delay = self._wait(("move", self.game_no, self._step), self._bot_delay(base))
            return delay, lambda s=game.current: self._auto_move(s)
        if self._deadline is not None:
            return max(0.0, self._deadline[1] - time.monotonic()), self._timeout
        return None

    def _refresh_deadline(self) -> None:
        timer = self.settings.turn_timer
        key: tuple[Any, ...] | None = None
        game = self.game
        live = self.status == "playing" and game is not None and game.step in (Step.DRAW, Step.PLAY)
        if timer and live and game is not None and not self._is_auto(game.current):
            key = ("turn", self.game_no, game.turn)
        if key is None:
            self._deadline = None
        elif self._deadline is None or self._deadline[0] != key:
            self._deadline = (key, time.monotonic() + timer)

    def _timeout(self) -> None:
        game = self._game()
        seat = game.current
        self._say(f"⏱ {self.seats[seat].name} ran out of time; the autopilot finishes the turn")
        turn = game.turn
        while (
            self.status == "playing"
            and game.step in (Step.DRAW, Step.PLAY)
            and game.current == seat
            and game.turn == turn
        ):
            self._auto_move(seat)

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
                    "color": SEAT_COLORS[i % len(SEAT_COLORS)],
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

    @staticmethod
    def _filter_event(ev: Event, you: int | None) -> Event:
        if ev["kind"] == "draw" and ev["from"] == "deck" and ev["seat"] != you:
            return {**ev, "card": None}
        return ev

    def _game_state(self, you: int | None) -> dict[str, Any] | None:
        game = self.game
        if game is None:
            return None
        live = game.step in (Step.DRAW, Step.PLAY)
        mine = (
            live
            and you is not None
            and you == game.current
            and not self.seats[you].autoplay
            and self.status == "playing"
        )
        state: dict[str, Any] = {
            "step": game.step.value,
            "current": game.current if live else None,
            "hand_no": game.hand_no,
            "dealer": game.dealer,
            "turn": game.turn,
            "last_phase": game.rules.last_phase,
            "players": [
                {
                    "phase": game.phases[i],
                    "score": game.scores[i],
                    "laid": game.laid[i],
                    "count": len(game.hands[i]),
                    "skipped": i in game.skipped,
                    "active": game.active[i],
                }
                for i in range(game.n)
            ],
            "tied": list(game.tied),
            "hand": [c.to_json() for c in game.hands[you]] if you is not None else [],
            "groups": [g.to_json() for g in game.groups],
            "discard_top": game.discard[-1].to_json() if game.discard else None,
            "discard_under": game.discard[-2].to_json() if len(game.discard) > 1 else None,
            "discard_size": len(game.discard),
            "draw_size": len(game.draw),
            "options": game.options(you) if mine else None,
            "history": [h.to_json() for h in game.history],
            "ready": sorted(self.ready),
            "waiting_for": [i for i in self._humans_waited_for() if i not in self.ready]
            if game.step == Step.HAND_OVER
            else [],
            "result": dataclasses.asdict(game.result) if game.result else None,
            "time_left": None,
        }
        if self._deadline is not None:
            state["time_left"] = round(max(0.0, self._deadline[1] - time.monotonic()), 2)
            timer = self.settings.turn_timer
            state["time_total"] = timer
        return state


__all__ = ["MAX_SEATS", "Room", "RoomError", "bots_public", "phases_public"]
