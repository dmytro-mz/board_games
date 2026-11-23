"""A multiplayer table: members, two seats (humans or bots), lobby settings and the match.

All mutations are synchronous and run on the event loop thread. Every change is pushed to each listener as
a full per-viewer snapshot (`Room.state_for`) tagged with the events that caused it, so clients can animate
them. Hidden information: a player's hand and the card they draw from the deck go only to that player.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boardgames.table import MAX_NAME, Member, RoomError, Table, clean_text
from lostcities.bots import REGISTRY, Bot
from lostcities.game import actions
from lostcities.game.actions import Action
from lostcities.game.cards import CARDS, COLORS, SITES, sort_key
from lostcities.game.engine import Event, Game, IllegalMove, Phase

log = logging.getLogger(__name__)

MAX_SEATS = 2
BOT_SPEEDS = {"slow": 1.8, "normal": 1.0, "fast": 0.4}
TURN_TIMERS = (0, 30, 60, 90, 180)
ROUND_CHOICES = (1, 2, 3, 4, 5)
SEAT_COLORS = ("amber", "teal")
BOT_CONTINUE_DELAY = 6.0

Plan = tuple[float, Callable[[], None]]


@dataclass
class Settings:
    rounds: int = 3
    turn_timer: int = 0  # seconds per human turn, 0 = off
    bot_speed: str = "normal"
    hints: bool = False
    peek: bool = False  # players may look through whole discard piles, not just the top card

    def update(self, changes: dict[str, Any]) -> None:
        """All or nothing: an invalid entry leaves every setting unchanged."""
        trial = dataclasses.replace(self)
        trial._apply(changes)
        self.__dict__.update(trial.__dict__)

    def _apply(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "rounds" and value in ROUND_CHOICES and not isinstance(value, bool):
                self.rounds = int(value)
            elif key == "turn_timer" and value in TURN_TIMERS and not isinstance(value, bool):
                self.turn_timer = int(value)
            elif key == "bot_speed" and value in BOT_SPEEDS:
                self.bot_speed = str(value)
            elif key in ("hints", "peek") and isinstance(value, bool):
                setattr(self, key, value)
            else:
                raise RoomError(f"invalid setting {key}={value!r}")


@dataclass
class Seat:
    name: str
    member_id: str | None = None  # None: a bot
    bot: str | None = None  # REGISTRY key
    agent: Bot | None = None
    autoplay: bool = False  # a human seat temporarily played by the autopilot
    ready: bool = False  # between rounds

    @property
    def is_bot(self) -> bool:
        return self.member_id is None


def bots_public() -> list[dict[str, Any]]:
    return [{"key": b.key, "label": b.label, "stars": b.stars, "description": b.description} for b in REGISTRY.values()]


def card_tag(card_id: str) -> str:
    """Log markup the client renders as a small card chip."""
    return f"{{{card_id}}}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


class Room(Table):
    MAX_SEATS = MAX_SEATS

    def __init__(self, room_id: str, delay_scale: float = 1.0, seed: int | None = None) -> None:
        super().__init__(room_id, delay_scale, seed)
        self.settings = Settings()
        self.game: Game | None = None
        self.game_no = 0
        self._autopilot = REGISTRY[list(REGISTRY)[-1]].make(self.rng.randrange(2**31))
        self._step = 0  # counts game steps so bot delays restart after each one

    # ------------------------------------------------------------------ members
    def _new_seat(self, member: Member) -> Seat:
        return Seat(name=member.name, member_id=member.id)

    def _welcome_extra(self) -> dict[str, Any]:
        return {"bots": bots_public()}

    def _lineup(self) -> str:
        return " vs ".join(f"{s.name} (bot)" if s.is_bot else s.name for s in self.seats) or "nobody seated"

    def describe(self) -> str:
        """One line for the server console: who is at this table and what it's doing."""
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
            case "undo":
                self._undo(member)
            case "ready":
                self._ready(member)
            case "autoplay":
                self._set_autoplay(msg.get("seat"), bool(msg.get("on")))
            case "hint":
                return self._hint(member)
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
        if self.status not in ("playing", "round_over") or not isinstance(seat, int) or not 0 <= seat < len(self.seats):
            raise RoomError("No such seat")
        target = self.seats[seat]
        if target.is_bot:
            raise RoomError("That seat is already a bot")
        member = self.members[target.member_id or ""]
        if on and member.connections:
            raise RoomError(f"{target.name} is still connected")
        target.autoplay = on
        if on and self.status == "round_over":
            target.ready = True
        self._say(f"The autopilot plays for {target.name}" if on else f"{target.name} plays again")
        self._emit({"kind": "presence"})

    # ------------------------------------------------------------------ game flow
    def start(self) -> None:
        if self.status in ("playing", "round_over"):
            raise RoomError("A game is already running")
        if len(self.seats) < MAX_SEATS:
            raise RoomError("Two players are needed: invite someone or add a bot")
        for seat in self.seats:
            seat.agent = REGISTRY[seat.bot].make(self.rng.randrange(2**31)) if seat.bot else None
            seat.autoplay = False
            seat.ready = False
        starter = self.rng.randrange(MAX_SEATS)
        self.game = Game(rounds=self.settings.rounds, seed=self.rng.randrange(2**63), starter=starter)
        self.game_no += 1
        self.status = "playing"
        log.info("table %s: game %d started: %s", self.id, self.game_no, self._lineup())
        rounds = "one round" if self.settings.rounds == 1 else f"{self.settings.rounds} rounds"
        self._say(f"🧭 Game {self.game_no}: {self._lineup()} · {rounds}")
        self._say(f"{self.seats[starter].name} sets out first.", starter)
        self._emit({"kind": "game_start"})

    def _to_lobby(self) -> None:
        if self.status == "lobby":
            return
        self.status = "lobby"
        self.game = None
        for seat in self.seats:
            seat.agent = None
            seat.autoplay = False
            seat.ready = False
        for member in self.members.values():
            if member.connections and self.seat_of(member.id) is None and len(self.seats) < MAX_SEATS:
                self.seats.append(Seat(name=member.name, member_id=member.id))
        self._say("Back to the lobby")
        self._emit({"kind": "lobby"})

    def _game(self) -> Game:
        if self.game is None or self.status != "playing":
            raise RoomError("No round in progress")
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

    def _undo(self, member: Member) -> None:
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        game = self._game()
        if self.seats[seat].autoplay:
            raise RoomError("The autopilot is playing for you")
        try:
            events = game.undo(seat)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._step += 1
        for ev in events:
            self._narrate(ev)
        self._emit({"kind": "move", "seat": seat, "events": events})

    def _auto_move(self, seat: int) -> None:
        game = self._game()
        self._apply(seat, self._agent(seat).act(game.view(seat)))

    def _apply(self, seat: int, action: Action) -> None:
        game = self._game()
        try:
            events = game.step(seat, action)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._step += 1
        for ev in events:
            self._narrate(ev)
        if game.phase == Phase.ROUND_OVER:
            self.status = "round_over"
            for s in self.seats:
                s.ready = s.is_bot or s.autoplay
        elif game.phase == Phase.GAME_OVER:
            self.status = "game_over"
        self._emit({"kind": "move", "seat": seat, "events": events})

    def _ready(self, member: Member) -> None:
        seat = self.seat_of(member.id)
        if self.status != "round_over" or seat is None:
            raise RoomError("Nothing to be ready for")
        self.seats[seat].ready = True
        self._emit({"kind": "ready"})

    def _next_round(self) -> None:
        game = self.game
        assert game is not None
        events = game.next_round()
        self.status = "playing"
        for seat in self.seats:
            seat.ready = False
        starter = events[0]["starter"]
        self._say(f"🧭 Round {game.round_no} of {game.rounds}: {self.seats[starter].name} sets out first.", starter)
        self._emit({"kind": "round_start", "events": events})

    def _name(self, seat: int | None) -> str:
        return self.seats[seat].name if seat is not None and 0 <= seat < len(self.seats) else ""

    def _narrate(self, ev: Event) -> None:
        seat = ev.get("seat")
        name = self._name(seat)
        match ev["kind"]:
            case "play":
                game = self.game
                assert game is not None and seat is not None
                pile = game.expeditions[seat][ev["color"]]
                card = CARDS[ev["card"]]
                if len(pile) == 1:
                    what = "backs" if card.is_wager else "sets out for"
                    self._say(f"{name} {what} {SITES[card.color]} {card_tag(card.id)}", seat)
                else:
                    self._say(f"{name} pushes on to {SITES[card.color]} {card_tag(card.id)}", seat)
            case "discard":
                self._say(f"{name} discards {card_tag(ev['card'])}", seat)
            case "undo":
                self._say(f"↩ {name} takes back {card_tag(ev['card'])}", seat)
            case "draw" if ev["source"] != actions.DECK_SOURCE:
                self._say(f"{name} picks up {card_tag(ev['card'])}", seat)
            case "round_over":
                scores = ", ".join(f"{s.name} {_signed(p)}" for s, p in zip(self.seats, ev["scores"], strict=True))
                self._say(f"🏁 Round {ev['round']} is over: {scores}")
            case "game_over":
                totals = ev["totals"]
                winners = " & ".join(self.seats[w].name for w in ev["winners"])
                line = " – ".join(str(t) for t in totals)
                log.info("table %s: game %d won by %s (%s)", self.id, self.game_no, winners, line)
                if len(ev["winners"]) > 1:
                    self._say(f"🤝 A draw at {totals[0]} points each!")
                else:
                    self._say(f"🏆 {winners} wins the game, {line}!")

    # ------------------------------------------------------------------ hints
    def _hint(self, member: Member) -> dict[str, Any]:
        if not self.settings.hints:
            raise RoomError("Hints are turned off at this table")
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        game = self._game()
        if game.current != seat:
            raise RoomError("It's not your turn")
        action = self._autopilot.act(game.view(seat))
        return {"type": "hint", "action": actions.to_json(action)}

    # ------------------------------------------------------------------ automation

    def _bot_delay(self, base: float) -> float:
        return base * BOT_SPEEDS[self.settings.bot_speed]

    def plan(self) -> Plan | None:
        """The next automatic step as (seconds to wait, action), or None to wait for a human."""
        if self.status == "round_over" and self.game is not None:
            humans = [s for s in self.seats if not s.is_bot and not s.autoplay]
            online = [s for s in humans if self.members[s.member_id or ""].connections]
            if not online:
                key = ("continue", self.game_no, len(self.game.history))
                return self._wait(key, BOT_CONTINUE_DELAY), self._next_round
            if all(s.ready for s in online):
                return 0.0, self._next_round
            return None
        if self.status != "playing" or self.game is None:
            return None
        game = self.game
        if self._is_auto(game.current):
            base = 1.1 if game.phase == Phase.PLAY else 0.8
            delay = self._wait(("move", self.game_no, self._step), self._bot_delay(base))
            return delay, lambda s=game.current: self._auto_move(s)
        if self._deadline is not None:
            return max(0.0, self._deadline[1] - time.monotonic()), self._timeout
        return None

    def _refresh_deadline(self) -> None:
        timer = self.settings.turn_timer
        key: tuple[Any, ...] | None = None
        game = self.game
        if timer and self.status == "playing" and game is not None and not self._is_auto(game.current):
            key = ("turn", self.game_no, len(game.history), game.turn, game.current)
        if key is None:
            self._deadline = None
        elif self._deadline is None or self._deadline[0] != key:
            self._deadline = (key, time.monotonic() + timer)

    def _timeout(self) -> None:
        game = self._game()
        seat = game.current
        self._say(f"⏱ {self.seats[seat].name} ran out of time; the autopilot finishes the turn")
        key = (len(game.history), game.turn)
        while self.status == "playing" and (len(game.history), game.turn) == key and game.current == seat:
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
                    "color": SEAT_COLORS[i],
                    "connected": True if member is None else member.connections > 0,
                    "autoplay": s.autoplay,
                    "ready": s.ready,
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
        """A card drawn from the deck is only shown to the player who drew it."""
        if ev["kind"] == "draw" and ev["source"] == actions.DECK_SOURCE and ev.get("seat") != you:
            return {**ev, "card": None}
        return ev

    def _game_state(self, you: int | None) -> dict[str, Any] | None:
        game = self.game
        if game is None:
            return None
        playing = game.phase in (Phase.PLAY, Phase.DRAW)
        mine = (
            you is not None
            and playing
            and you == game.current
            and not self.seats[you].autoplay
            and self.status == "playing"
        )
        peek = self.settings.peek or not playing
        discards = {}
        for color in COLORS:
            pile = game.discards[color]
            discards[color] = {
                "top": pile[-1].id if pile else None,
                "count": len(pile),
                "cards": [c.id for c in pile] if peek else None,
            }
        live = [[e.to_json() for e in game.live_scores(seat)] for seat in range(2)]
        state: dict[str, Any] = {
            "phase": game.phase.value,
            "current": game.current if playing else None,
            "round": game.round_no,
            "rounds": game.rounds,
            "turn": game.turn,
            "deck_left": len(game.deck),
            "hand": [c.id for c in sorted(game.hands[you], key=sort_key)] if you is not None else None,
            "hand_sizes": [len(h) for h in game.hands],
            "expeditions": [{c: [card.id for card in e[c]] for c in COLORS} for e in game.expeditions],
            "discards": discards,
            "last_discard": game.last_discard,
            "live": live,
            "live_total": [sum(e["score"] for e in side) for side in live],
            "totals": game.totals,
            "history": [r.to_json() for r in game.history],
            "legal": [actions.to_json(a) for a in game.legal_actions(you)] if mine else [],
            "can_undo": bool(mine and game.can_undo(you)),
            "result": dataclasses.asdict(game.result) if game.result else None,
            "time_left": None,
        }
        if not playing:
            # Between rounds and at the end, both hands are revealed (unplayed cards don't score).
            state["hands"] = [[c.id for c in sorted(h, key=sort_key)] for h in game.hands]
        if self._deadline is not None:
            state["time_left"] = round(max(0.0, self._deadline[1] - time.monotonic()), 2)
            state["time_total"] = self.settings.turn_timer
        return state


__all__ = ["MAX_SEATS", "Room", "RoomError", "bots_public"]
