"""A multiplayer Skyjo table: members, seats (humans or bots), lobby settings and the game.

All mutations are synchronous and run on the event loop thread. Every change is pushed to
each listener as a full per-viewer snapshot (`Room.state_for`) tagged with the `event` that
caused it, so clients can animate it. Face-down card values never leave the room: the only
peeked values are setup flips that are already committed (see `_queue_setup_flip`).

Setup is simultaneous for humans although the engine flips seat by seat: flips are queued
per seat and fed to the engine in seat order as soon as the seat in turn has chosen.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boardgames.table import MAX_NAME, Member, RoomError, Table, clean_text
from skyjo.agents import Agent, ExpertAgent
from skyjo.game import DRAW_DECK, FLIP_BASE, TAKE_DISCARD, Game, Phase, Round, RulesConfig
from skyjo.game.board import FACE_UP
from skyjo.game.cards import COLS, HIDDEN, REMOVED, value_index
from skyjo.game.observation import Observation
from skyjo.web.bots import BotCatalog

log = logging.getLogger(__name__)

MAX_SEATS = 8
BOT_SPEEDS = {"slow": 1.7, "normal": 1.0, "fast": 0.45}
TURN_TIMERS = (0, 15, 30, 60, 120)
END_SCORES = (50, 100, 150, 200)
BOT_CONTINUE_DELAY = 6.0

Event = dict[str, Any]
Plan = tuple[float, Callable[[], None]]


@dataclass
class Settings:
    end_score: int = 100
    column_clear: bool = True
    double_finisher: bool = True
    turn_timer: int = 0  # seconds per human turn, 0 = off
    bot_speed: str = "normal"
    hints: bool = True

    def update(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "end_score" and value in END_SCORES:
                self.end_score = int(value)
            elif key == "turn_timer" and value in TURN_TIMERS:
                self.turn_timer = int(value)
            elif key == "bot_speed" and value in BOT_SPEEDS:
                self.bot_speed = str(value)
            elif key in ("column_clear", "double_finisher", "hints") and isinstance(value, bool):
                setattr(self, key, value)
            else:
                raise RoomError(f"invalid setting {key}={value!r}")


@dataclass
class Seat:
    name: str
    member_id: str | None = None  # None: a bot
    bot: str | None = None  # BotCatalog key
    agent: Agent | None = None
    autoplay: bool = False  # a human seat temporarily played by the autopilot
    ready: bool = False

    @property
    def is_bot(self) -> bool:
        return self.member_id is None


def _cell(view: int) -> int | str | None:
    if view == HIDDEN:
        return None
    if view == REMOVED:
        return "x"
    return view


class Room(Table):
    MAX_SEATS = MAX_SEATS

    def __init__(
        self,
        room_id: str,
        catalog: BotCatalog,
        delay_scale: float = 1.0,
        seed: int | None = None,
    ) -> None:
        super().__init__(room_id, delay_scale, seed, log_size=300)
        self.catalog = catalog
        self.settings = Settings()
        self.game: Game | None = None
        self.game_no = 0
        self.ended_round: Round | None = None  # shown during round_over / game_over
        self.pending: dict[int, list[int]] = {}
        self.turn_source: str | None = None
        self._autopilot = ExpertAgent(seed=self.rng.randrange(2**31))
        self._timed_out: tuple[Any, ...] | None = None

    # ------------------------------------------------------------------ members
    def _new_seat(self, member: Member) -> Seat:
        return Seat(name=member.name, member_id=member.id)

    def _welcome_extra(self) -> dict[str, Any]:
        return {"bots": self.catalog.public()}

    def _lineup(self) -> str:
        return ", ".join(f"{s.name} (bot)" if s.is_bot else s.name for s in self.seats) or "nobody seated"

    def describe(self) -> str:
        """One line for the server console: who is at this table and what it's doing."""
        host = self.members.get(self.host_id or "")
        online = sum(1 for m in self.members.values() if m.connections)
        seated = {s.member_id for s in self.seats}
        watching = sum(1 for m in self.members.values() if m.connections and m.id not in seated)
        parts = [self.id, self.status.replace("_", " "), f"host {host.name if host else '-'}", self._lineup()]
        parts.append(f"{online} online" + (f", {watching} watching" if watching else ""))
        return " · ".join(parts)

    # ------------------------------------------------------------------ requests
    def handle(self, member_id: str, msg: dict[str, Any]) -> dict[str, Any] | None:
        member = self.members[member_id]
        kind = msg.get("type")
        self.last_activity = time.monotonic()
        is_host = member_id == self.host_id
        host_only = {
            "add_bot",
            "remove_seat",
            "settings",
            "start",
            "continue",
            "play_again",
            "to_lobby",
            "autoplay",
            "shuffle",
        }
        if kind in host_only and not is_host:
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
            case "ready":
                self._ready(member)
            case "continue":
                if self.status != "round_over":
                    raise RoomError("Nothing to continue")
                self._next_round()
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
        bot = self.catalog.get(key)
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
        if self.status == "lobby" or not isinstance(seat, int) or not 0 <= seat < len(self.seats):
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
        if self.status not in ("lobby", "game_over"):
            raise RoomError("A game is already running")
        n = len(self.seats)
        if n < 2:
            raise RoomError("Add at least one more player or bot")
        for seat in self.seats:
            if seat.is_bot:
                bot = self.catalog.get(seat.bot or "")
                if bot is None:
                    raise RoomError(f"{seat.name}: unknown bot")
                if bot.n_players is not None and bot.n_players != n:
                    raise RoomError(f"{seat.name} only plays {bot.n_players}-player games")
        for seat in self.seats:
            seat.agent = self.catalog.make(seat.bot, seed=self.rng.randrange(2**31)) if seat.bot else None
            seat.autoplay = False
            seat.ready = False
        rules = RulesConfig(
            n_players=n,
            end_score=self.settings.end_score,
            column_clear=self.settings.column_clear,
            double_finisher_penalty=self.settings.double_finisher,
        )
        self.game = Game(rules, seed=self.rng.randrange(2**63))
        self.game_no += 1
        self.status = "playing"
        self.ended_round = None
        self.pending = {}
        self.turn_source = None
        log.info("table %s: game %d started with %s", self.id, self.game_no, self._lineup())
        self._say(f"Game {self.game_no} starts — first to {self.settings.end_score} points loses. Flip two cards!")
        self._emit({"kind": "game_start"})

    def _to_lobby(self) -> None:
        if self.status == "lobby":
            return
        self.status = "lobby"
        self.game = None
        self.ended_round = None
        self.pending = {}
        for seat in self.seats:
            seat.agent = None
            seat.autoplay = False
        # Members who joined mid-game were spectators; give them a seat if there is room.
        for member in self.members.values():
            if member.connections and self.seat_of(member.id) is None and len(self.seats) < MAX_SEATS:
                self.seats.append(Seat(name=member.name, member_id=member.id))
        self._say("Back to the lobby")
        self._emit({"kind": "lobby"})

    def _ready(self, member: Member) -> None:
        seat = self.seat_of(member.id)
        if self.status != "round_over" or seat is None:
            raise RoomError("Nothing to be ready for")
        self.seats[seat].ready = True
        self._emit({"kind": "ready"})

    def _next_round(self) -> None:
        self.status = "playing"
        self.ended_round = None
        self.pending = {}
        self.turn_source = None
        for seat in self.seats:
            seat.ready = False
        assert self.game is not None
        self._say(f"Round {self.game.round.round_index + 1} — flip two cards")
        self._emit({"kind": "round_start"})

    def _is_auto(self, seat: int) -> bool:
        s = self.seats[seat]
        return s.is_bot or s.autoplay

    def _agent(self, seat: int) -> Agent:
        return self.seats[seat].agent or self._autopilot

    def _round(self) -> Round:
        if self.game is None or self.status != "playing":
            raise RoomError("No game in progress")
        return self.game.round

    # ------------------------------------------------------------------ setup
    def _setup_left(self, seat: int) -> int:
        rnd = self._round()
        if rnd.phase != Phase.SETUP:
            return 0
        done = sum(1 for s in rnd.boards[seat].status if s == FACE_UP)
        return max(0, rnd.rules.setup_flips - done - len(self.pending.get(seat, ())))

    def _setup_obs(self, seat: int) -> tuple[Observation, list[int]]:
        rnd = self._round()
        obs = rnd.observe(seat)
        boards = [list(b) for b in obs.boards]
        unknown = list(obs.unknown_counts)
        for s, positions in self.pending.items():
            for pos in positions:
                value = rnd.boards[s].values[pos]
                boards[s][pos] = value
                unknown[value_index(value)] -= 1
        pending = set(self.pending.get(seat, ()))
        legal = [FLIP_BASE + p for p in rnd.boards[seat].hidden_positions() if p not in pending]
        obs = dataclasses.replace(obs, boards=tuple(tuple(b) for b in boards), unknown_counts=tuple(unknown))
        return obs, legal

    def _queue_setup_flip(self, seat: int, pos: int) -> None:
        rnd = self._round()
        if self._setup_left(seat) <= 0:
            raise RoomError("You already flipped your cards")
        if pos in self.pending.get(seat, ()) or pos not in rnd.boards[seat].hidden_positions():
            raise RoomError("That card is already face up")
        self.pending.setdefault(seat, []).append(pos)
        value = rnd.boards[seat].values[pos]
        started = self._drain_setup()
        event: Event = {"kind": "flip", "seat": seat, "pos": pos, "card": value}
        if started:
            current = self._round().current
            event["starter"] = current
            self._say(f"{self.seats[current].name} has the highest cards and starts")
        self._emit(event)

    def _drain_setup(self) -> bool:
        """Feed queued flips to the engine in seat order; True once play has started."""
        rnd = self._round()
        while rnd.phase == Phase.SETUP:
            queue = self.pending.get(rnd.current)
            if not queue:
                return False
            pos = queue.pop(0)
            assert self.game is not None
            self.game.step(FLIP_BASE + pos)
        self.pending = {}
        return True

    def _auto_setup(self, seat: int, key: tuple[Any, ...] | None = None) -> None:
        """`key`: the position this flip is planned for, so the bot may think off the event loop (`think`)."""
        obs, legal = self._setup_obs(seat)
        agent = self._agent(seat)
        action = agent.act(obs, legal) if key is None else self.think(key, lambda: agent.act(obs, legal))
        self._queue_setup_flip(seat, action - FLIP_BASE)

    # ------------------------------------------------------------------ moves
    def _human_action(self, member: Member, action: object) -> None:
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        if not isinstance(action, int):
            raise RoomError("invalid action")
        rnd = self._round()
        if self.seats[seat].autoplay:
            self.seats[seat].autoplay = False
        if rnd.phase == Phase.SETUP:
            if not FLIP_BASE <= action < DRAW_DECK:
                raise RoomError("Flip one of your cards first")
            self._queue_setup_flip(seat, action - FLIP_BASE)
            return
        if rnd.current != seat:
            raise RoomError("It's not your turn")
        if action not in rnd.legal_actions():
            raise RoomError("That move isn't allowed")
        self._apply(seat, action)

    def _auto_move(self, seat: int) -> None:
        rnd = self._round()
        agent, obs, legal = self._agent(seat), rnd.observe(seat), rnd.legal_actions()
        key = ("move", self.game_no, rnd.round_index, rnd.turn, rnd.phase, seat)
        self._apply(seat, self.think(key, lambda: agent.act(obs, legal)))

    def _apply(self, seat: int, action: int) -> None:
        game = self.game
        assert game is not None
        rnd = game.round
        board = rnd.boards[seat]
        hand = rnd.hand
        before = board.view()
        old = board.values[action] if action < FLIP_BASE else None
        had_finisher = rnd.finisher is not None
        result = game.step(action)
        name = self.seats[seat].name
        event: Event = {"seat": seat}

        if action == DRAW_DECK:
            self.turn_source = "deck"
            event.update(kind="draw", card=rnd.hand)
            self._emit(event)
            return
        if action == TAKE_DISCARD:
            self.turn_source = "discard"
            event.update(kind="take", card=rnd.hand)
            self._emit(event)
            return

        after = board.view()
        cleared = [c for c in range(COLS) if after[3 * c] == REMOVED and before[3 * c] != REMOVED]
        verb = "took" if self.turn_source == "discard" else "drew"
        if action < FLIP_BASE:
            was_hidden = before[action] == HIDDEN
            event.update(kind="replace", pos=action, card=hand, old=old, was_hidden=was_hidden)
            where = " (a face-down card)" if was_hidden else ""
            self._say(f"{name} {verb} [{hand}] and swapped it for [{old}]{where}", seat)
        else:
            pos = action - FLIP_BASE
            event.update(kind="discard_flip", pos=pos, card=hand, revealed=board.values[pos])
            self._say(f"{name} drew [{hand}], threw it away and flipped [{board.values[pos]}]", seat)
        event["cleared"] = [{"col": c, "card": board.values[3 * c]} for c in cleared]
        for c in cleared:
            self._say(f"Three [{board.values[3 * c]}]s — {name} clears a column!", seat)
        if not had_finisher and rnd.finisher == seat:
            event["finished"] = True
            self._say(f"{name} revealed every card — everyone else gets one last turn!", seat)
        self.turn_source = None
        if result is not None:
            self._end_round(rnd)
            event["round_over"] = True
        self._emit(event)

    def _end_round(self, rnd: Round) -> None:
        game = self.game
        assert game is not None and rnd.result is not None
        result = rnd.result
        self.ended_round = rnd
        self.pending = {}
        parts = []
        for i, seat in enumerate(self.seats):
            score = f"{result.scores[i]}"
            if result.doubled and i == result.finisher:
                score = f"{result.raw_scores[i]}×2 = {result.scores[i]}"
            parts.append(f"{seat.name} {score}")
        self._say(f"Round {len(game.rounds)} over: " + ", ".join(parts))
        for seat in self.seats:
            seat.ready = seat.is_bot or seat.autoplay
        if game.result is not None:
            self.status = "game_over"
            winners = " & ".join(self.seats[w].name for w in game.result.winners)
            log.info("table %s: game %d won by %s after %d rounds", self.id, self.game_no, winners, len(game.rounds))
            self._say(f"🏆 {winners} won with {min(game.result.totals)} points!")
        else:
            self.status = "round_over"

    # ------------------------------------------------------------------ hints
    def _hint(self, member: Member) -> dict[str, Any]:
        if not self.settings.hints:
            raise RoomError("Hints are turned off at this table")
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        rnd = self._round()
        if rnd.phase == Phase.SETUP:
            if not self._setup_left(seat):
                raise RoomError("Wait for the others to flip")
            obs, legal = self._setup_obs(seat)
        elif rnd.current == seat:
            obs, legal = rnd.observe(seat), rnd.legal_actions()
        else:
            raise RoomError("It's not your turn")
        return {"type": "hint", "action": self._autopilot.act(obs, legal)}

    # ------------------------------------------------------------------ automation

    def _bot_delay(self, base: float) -> float:
        return base * BOT_SPEEDS[self.settings.bot_speed]

    def plan(self) -> Plan | None:
        """The next automatic step as (seconds to wait, action), or None to wait for a human."""
        if self.status == "round_over":
            humans = [s for s in self.seats if not s.is_bot and not s.autoplay]
            if not humans:
                assert self.game is not None
                key = ("continue", self.game_no, len(self.game.rounds))
                return self._wait(key, BOT_CONTINUE_DELAY), self._next_round
            online = [s for s in humans if self.members[s.member_id or ""].connections]
            if online and all(s.ready for s in online):
                return 0.0, self._next_round
            return None
        if self.status != "playing" or self.game is None:
            return None
        rnd = self.game.round
        tag = (self.game_no, rnd.round_index)
        if rnd.phase == Phase.SETUP:
            for seat in range(len(self.seats)):
                left = self._setup_left(seat)
                if left and self._is_auto(seat):
                    key = ("setup", *tag, seat, left)
                    delay = self._wait(key, self._bot_delay(0.5))
                    return delay, lambda s=seat, k=key: self._auto_setup(s, k)
        elif self._is_auto(rnd.current):
            base = 0.9 if rnd.phase == Phase.CHOOSE_SOURCE else 1.1
            delay = self._wait(("move", *tag, rnd.turn, rnd.phase), self._bot_delay(base))
            return delay, lambda s=rnd.current: self._auto_move(s)
        if self._deadline is not None:
            return max(0.0, self._deadline[1] - time.monotonic()), self._timeout
        return None

    def _refresh_deadline(self) -> None:
        timer = self.settings.turn_timer
        key: tuple[Any, ...] | None = None
        if timer and self.status == "playing" and self.game is not None:
            rnd = self.game.round
            tag = (self.game_no, rnd.round_index)
            if rnd.phase == Phase.SETUP:
                if any(self._setup_left(s) and not self._is_auto(s) for s in range(len(self.seats))):
                    key = ("setup", *tag)
            elif not self._is_auto(rnd.current):
                key = ("turn", *tag, rnd.turn)
        if key is None:
            self._deadline = None
        elif self._deadline is None or self._deadline[0] != key:
            self._deadline = (key, time.monotonic() + timer)

    def _timeout(self) -> None:
        assert self._deadline is not None
        key = self._deadline[0]
        rnd = self._round()
        first = self._timed_out != key
        self._timed_out = key
        if rnd.phase == Phase.SETUP:
            for seat in range(len(self.seats)):
                if not self._is_auto(seat) and self._setup_left(seat):
                    self._say(f"⏱ {self.seats[seat].name} ran out of time — cards flipped automatically")
                    while self.status == "playing" and self._round().phase == Phase.SETUP and self._setup_left(seat):
                        self._auto_setup(seat)
            return
        if first:
            self._say(f"⏱ {self.seats[rnd.current].name} ran out of time — the autopilot moves")
        self._auto_move(rnd.current)

    # ------------------------------------------------------------------ output

    def state_for(self, member_id: str, event: Event | None = None) -> dict[str, Any]:
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
        rnd = self.ended_round or game.round
        playing = self.status == "playing"
        boards = []
        for seat, board in enumerate(rnd.boards):
            cells = [_cell(v) for v in board.view()]
            if playing and rnd.phase == Phase.SETUP:
                for pos in self.pending.get(seat, ()):
                    cells[pos] = board.values[pos]
            boards.append(cells)
        visible = [sum(c for c in cells if isinstance(c, int)) for cells in boards]
        state: dict[str, Any] = {
            "round": rnd.round_index,
            "phase": rnd.phase.name,
            "current": rnd.current if playing and rnd.phase != Phase.SETUP else None,
            "turn": rnd.turn,
            "finisher": rnd.finisher,
            "deck": len(rnd.deck),
            "discard": rnd.discard[-1] if rnd.discard else None,
            "discard_under": rnd.discard[-2] if len(rnd.discard) > 1 else None,
            "hand": rnd.hand,
            "source": self.turn_source,
            "boards": boards,
            "visible": visible,
            "totals": list(game.totals),
            "rounds": [
                {
                    "scores": list(r.scores),
                    "raw": list(r.raw_scores),
                    "finisher": r.finisher,
                    "doubled": r.doubled,
                }
                for r in game.rounds
            ],
            "end_score": game.rules.end_score,
            "setup_flips": game.rules.setup_flips,
            "legal": [],
            "setup_left": [self._setup_left(s) if playing else 0 for s in range(len(self.seats))],
            "time_left": None,
            "winners": list(game.result.winners) if game.result else None,
        }
        if playing and you is not None and not self.seats[you].autoplay:
            if rnd.phase == Phase.SETUP:
                if self._setup_left(you):
                    state["legal"] = self._setup_obs(you)[1]
            elif rnd.current == you:
                state["legal"] = rnd.legal_actions()
        if self._deadline is not None:
            state["time_left"] = round(max(0.0, self._deadline[1] - time.monotonic()), 2)
            state["time_total"] = self.settings.turn_timer
        return state
