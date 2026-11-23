"""A multiplayer table: members, seats in two teams (humans or bots), lobby settings and the game.

All mutations are synchronous and run on the event loop thread. Every change is pushed to each listener as a
full per-viewer snapshot (`Room.state_for`) tagged with the events that caused it, so clients can animate them.
Hidden information (hands, discards, a face-down card, the decks) only goes to its owner.
Bots think in a worker thread on a redacted copy of the game, so a slow decision never blocks the table.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from dataclasses import dataclass
from typing import Any

from avenue.bots import REGISTRY, Bot, SearchBot, make_bot
from avenue.game import actions
from avenue.game.actions import choice_json
from avenue.game.cards import AGENT_LIST, HAND_SIZE, MARKET_LIST, TRACK
from avenue.game.engine import Action, Event, Game, IllegalMove, Phase
from boardgames.table import MAX_NAME, Member, RoomError, Table, clean_text

log = logging.getLogger(__name__)

MAX_SEATS = 4
MAX_TEAM = 2
REACTIONS = ("👍", "😂", "😱", "😡", "🎉", "🤔", "😭", "🔥", "👏", "🕵️")
BOT_SPEEDS = {"slow": 1.6, "normal": 1.0, "fast": 0.5}
TEAM_NAMES = ("Green", "Blue")
TEAM_COLORS = ("green", "blue")
FIRST_OPTIONS = ("random", "green", "blue")
TURN_TIMERS = (0, 30, 60, 90, 180)

AGENT_NAMES = {a.key: a.name for a in AGENT_LIST}
MARKET_NAMES = {m.key: m.name for m in MARKET_LIST}
REASONS = {
    "caught": "caught the other spy",
    "codebreakers": "recruited 3 Codebreakers",
    "masterplan": "has 7 different agents (Masterplan)",
    "security_system": "caught the other spy on their home space (Security System)",
    "leader_of_the_pack": "has 3 Daredevils (Leader of the Pack)",
    "opponent_daredevils": "the other team recruited 3 Daredevils",
    "out_of_cards": "the cards ran out and they were closer",
}


@dataclass
class Settings:
    mode: str = "simple"  # simple | advanced
    turn_timer: int = 0  # seconds per human decision, 0 = off
    bot_speed: str = "normal"
    first: str = "random"

    def update(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "mode" and value in ("simple", "advanced"):
                self.mode = str(value)
            elif key == "turn_timer" and value in TURN_TIMERS and not isinstance(value, bool):
                self.turn_timer = int(value)
            elif key == "bot_speed" and value in BOT_SPEEDS:
                self.bot_speed = str(value)
            elif key == "first" and value in FIRST_OPTIONS:
                self.first = str(value)
            else:
                raise RoomError(f"invalid setting {key}={value!r}")


@dataclass
class Seat:
    name: str
    team: int
    member_id: str | None = None  # None: a bot
    bot: str | None = None
    agent: Bot | None = None
    autoplay: bool = False  # a human seat temporarily played by the autopilot

    @property
    def is_bot(self) -> bool:
        return self.member_id is None


def bots_public() -> list[dict[str, Any]]:
    return [{"key": b.key, "label": b.label, "description": b.description} for b in REGISTRY.values()]


def _agent_name(key: str | None) -> str:
    return f"[{key}]" if key else "a card"


def event_seconds(events: list[Event]) -> float:
    """How long the browsers take to animate these events (bots wait for it before their next move)."""
    t = 0.0
    for ev in events:
        kind = ev["kind"]
        if kind == "play":
            t += 0.7
        elif kind == "recruit":
            t += 1.3
        elif kind == "move":
            t += 0.25 + 0.2 * abs(ev["steps"])
        elif kind in ("market", "ability_recruit", "steal", "spycation", "reveal"):
            t += 1.0
        elif kind == "game_over":
            t += 0.5
    return t


class Room(Table):
    MAX_SEATS = MAX_SEATS
    REACTIONS = REACTIONS

    def __init__(
        self, room_id: str, delay_scale: float = 1.0, seed: int | None = None, bot_budget: float = 1.0
    ) -> None:
        super().__init__(room_id, delay_scale, seed)
        self.bot_budget = bot_budget  # seconds a bot may think per decision
        self.settings = Settings()
        self.game: Game | None = None
        self.game_no = 0
        self.version = 0  # bumps on every game change; a bot's answer for an older version is dropped
        self.lead: tuple[int, int] | None = None  # (turn, seat): a human let their bot teammate play first
        self.busy_until = 0.0  # browsers are animating until then
        self.thinking: int | None = None
        self._autopilot = SearchBot(seed=self.rng.randrange(2**31), budget=min(0.6, bot_budget))

    # ------------------------------------------------------------------ members
    def _new_seat(self, member: Member) -> Seat:
        return Seat(name=member.name, team=self._open_team(), member_id=member.id)

    def _welcome_extra(self) -> dict[str, Any]:
        return {"bots": bots_public()}

    def _team_size(self, team: int) -> int:
        return sum(1 for s in self.seats if s.team == team)

    def _open_team(self) -> int:
        return 0 if self._team_size(0) <= self._team_size(1) else 1

    def _lineup(self) -> str:
        parts = []
        for team in (0, 1):
            names = [f"{s.name} (bot)" if s.is_bot else s.name for s in self.seats if s.team == team]
            parts.append(f"{TEAM_NAMES[team]}: {', '.join(names) or '-'}")
        return " vs ".join(parts)

    def describe(self) -> str:
        host = self.members.get(self.host_id or "")
        online = sum(1 for m in self.members.values() if m.connections)
        parts = [self.id, self.status.replace("_", " "), self.settings.mode, f"host {host.name if host else '-'}"]
        parts += [self._lineup(), f"{online} online"]
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
            "move_seat",
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
                self._sit(member, msg.get("team"))
            case "stand":
                self._stand(member)
            case "add_bot":
                self._add_bot(msg.get("team"))
            case "remove_seat":
                self._remove_seat(msg.get("seat"))
            case "move_seat":
                self._move_seat(msg.get("seat"), msg.get("team"))
            case "shuffle":
                self._shuffle()
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
            case "lead":
                self._let_lead(member)
            case "autoplay":
                self._set_autoplay(msg.get("seat"), bool(msg.get("on")))
            case _:
                raise RoomError(f"unknown request {kind!r}")
        return None

    def _team_arg(self, team: object, default: int) -> int:
        if team is None:
            return default
        if team not in (0, 1):
            raise RoomError("No such team")
        return int(team)  # type: ignore[call-overload]

    def _sit(self, member: Member, team: object) -> None:
        self._require_lobby()
        target = self._team_arg(team, self._open_team())
        seat = self.seat_of(member.id)
        if seat is not None:
            if self.seats[seat].team == target:
                return
            if self._team_size(target) >= MAX_TEAM:
                raise RoomError(f"Team {TEAM_NAMES[target]} is full")
            self.seats[seat].team = target
        else:
            if len(self.seats) >= MAX_SEATS or self._team_size(target) >= MAX_TEAM:
                raise RoomError(
                    "The table is full" if len(self.seats) >= MAX_SEATS else f"Team {TEAM_NAMES[target]} is full"
                )
            self.seats.append(Seat(name=member.name, team=target, member_id=member.id))
        self._emit({"kind": "lobby"})

    def _stand(self, member: Member) -> None:
        self._require_lobby()
        seat = self.seat_of(member.id)
        if seat is not None:
            del self.seats[seat]
            self._emit({"kind": "lobby"})

    def _add_bot(self, team: object) -> None:
        self._require_lobby()
        target = self._team_arg(team, self._open_team())
        if len(self.seats) >= MAX_SEATS or self._team_size(target) >= MAX_TEAM:
            raise RoomError(f"Team {TEAM_NAMES[target]} is full")
        info = next(iter(REGISTRY.values()))
        names = {s.name for s in self.seats}
        name, n = info.label, 1
        while name in names:
            n += 1
            name = f"{info.label} {n}"
        self.seats.append(Seat(name=name, team=target, bot=info.key))
        self._emit({"kind": "lobby"})

    def _check_seat(self, seat: object) -> int:
        if not isinstance(seat, int) or isinstance(seat, bool) or not 0 <= seat < len(self.seats):
            raise RoomError("No such seat")
        return seat

    def _remove_seat(self, seat: object) -> None:
        self._require_lobby()
        del self.seats[self._check_seat(seat)]
        self._emit({"kind": "lobby"})

    def _move_seat(self, seat: object, team: object) -> None:
        self._require_lobby()
        i = self._check_seat(seat)
        target = self._team_arg(team, 1 - self.seats[i].team)
        if self.seats[i].team == target:
            return
        if self._team_size(target) >= MAX_TEAM:
            raise RoomError(f"Team {TEAM_NAMES[target]} is full")
        self.seats[i].team = target
        self._emit({"kind": "lobby"})

    def _shuffle(self) -> None:
        """Deal the seats into the teams at random (each team keeps its size)."""
        self._require_lobby()
        if len(self.seats) < 2:
            raise RoomError("Add a player or a bot first")
        teams = [s.team for s in self.seats]
        self.rng.shuffle(self.seats)
        for seat, team in zip(self.seats, teams, strict=True):
            seat.team = team
        self.seats.sort(key=lambda s: s.team)
        self._emit({"kind": "lobby"})

    def _set_autoplay(self, seat: object, on: bool) -> None:
        if self.status != "playing":
            raise RoomError("No game in progress")
        target = self.seats[self._check_seat(seat)]
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
        sizes = [self._team_size(0), self._team_size(1)]
        if not all(sizes):
            raise RoomError("Each team needs at least one player or bot")
        for seat in self.seats:
            seat.agent = make_bot(seat.bot, self.rng.randrange(2**31), budget=self.bot_budget) if seat.bot else None
            seat.autoplay = False
        first = FIRST_OPTIONS.index(self.settings.first) - 1 if self.settings.first != "random" else None
        teams = [s.team for s in self.seats]
        self.game = Game(teams, advanced=self.settings.mode == "advanced", seed=self.rng.randrange(2**63), first=first)
        self.game_no += 1
        self.version += 1
        self.status = "playing"
        self.lead = None
        # the browsers deal the hands first
        self.busy_until = time.monotonic() + (0.6 + 0.12 * HAND_SIZE * len(self.seats)) * self.delay_scale
        log.info("table %s: game %d (%s) started — %s", self.id, self.game_no, self.settings.mode, self._lineup())
        mode = "advanced mode" if self.game.advanced else "simple mode"
        variant = " (team variant)" if len(self.seats) > 2 else ""
        self._say(f"Game {self.game_no} starts in {mode}{variant}. Team {TEAM_NAMES[self.game.active]} plays first!")
        self._emit({"kind": "game_start"})

    def _to_lobby(self) -> None:
        if self.status == "lobby":
            return
        self.status = "lobby"
        self.game = None
        self.version += 1
        for seat in self.seats:
            seat.agent = None
            seat.autoplay = False
        for member in self.members.values():
            if member.connections and self.seat_of(member.id) is None and len(self.seats) < MAX_SEATS:
                team = self._open_team()
                if self._team_size(team) < MAX_TEAM:
                    self.seats.append(Seat(name=member.name, team=team, member_id=member.id))
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

    def _let_lead(self, member: Member) -> None:
        seat = self.seat_of(member.id)
        game = self._game()
        if seat is None or game.phase != Phase.PLAY or game.up is not None or game.side_of[seat] != game.active:
            raise RoomError("Nothing to hand over right now")
        mates = [p for p in game.sides[game.active] if p != seat and self._is_auto(p)]
        if not mates:
            raise RoomError("Your teammate decides for themselves")
        self.lead = (game.turn, mates[0])
        self._say(f"{self.seats[seat].name} lets {self.seats[mates[0]].name} play the face-up card", seat)
        self._emit({"kind": "presence"})

    def _apply(self, seat: int, action: Action) -> None:
        game = self._game()
        try:
            events = game.step(seat, action)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self.version += 1
        for ev in events:
            self._narrate(ev)
        if game.phase == Phase.OVER:
            self.status = "game_over"
            self._end_game()
        self.busy_until = max(self.busy_until, time.monotonic()) + event_seconds(events) * self.delay_scale
        self._emit({"kind": "move", "seat": seat, "events": events})

    # ------------------------------------------------------------------ narration
    def _side_name(self, side: int) -> str:
        names = [s.name for s in self.seats if s.team == side]
        return " & ".join(names) if names else TEAM_NAMES[side]

    def _narrate(self, ev: Event) -> None:
        game = self.game
        assert game is not None
        player = ev.get("player")
        name = self.seats[player].name if isinstance(player, int) else ""
        side = ev.get("side")
        team = self._side_name(side) if isinstance(side, int) else ""
        match ev["kind"]:
            case "discard":
                self._say(f"{name} discarded a card face down ({ev['left']} discards left)", player)
            case "play":
                if ev["up"] and ev["down"]:
                    self._say(f"{name} played [{ev['up']}] face up and a card face down", player)
                elif ev["up"]:
                    self._say(f"{name} played [{ev['up']}] face up", player)
                else:
                    self._say(f"{name} played a card face down", player)
            case "recruit":
                taken = "the face-up" if ev["take"] == "up" else "the face-down"
                self._say(
                    f"{name} recruited {taken} [{ev['card']}] · {self._side_name(1 - side)} recruited [{ev['other']}]",
                    player,
                )
            case "move" if ev["steps"]:
                steps = ev["steps"]
                way = "forward" if steps > 0 else "backward"
                why = ev["why"]
                cause = (
                    "Getaway Car"
                    if why == "getaway_car"
                    else "Surveillance Truck"
                    if why == "surveillance_truck"
                    else None
                )
                tail = f" ({cause})" if cause else ""
                self._say(f"{team} moved {abs(steps)} space{'s' if abs(steps) != 1 else ''} {way}{tail}")
            case "market":
                self._say(f"🛒 Black market! {name} took {MARKET_NAMES[ev['card']]}", player)
            case "market_empty":
                self._say("The black market is sold out")
            case "ability_recruit":
                self._say(f"{team} recruited [{ev['card']}] ({MARKET_NAMES[ev['source']]})")
            case "steal":
                self._say(
                    f"{name} brainwashed [{ev['card']}] from {self._side_name(ev['from'])} into their hand", player
                )
            case "spycation":
                self._say(f"{name} sent [{ev['card']}] on a Spycation (back to their hand)", player)
            case "keep":
                self._say(f"{name} keeps [{ev['card']}] in their hand", player)
            case "reveal":
                self._say(f"{name} revealed 2 × [{ev['cards'][0]}]", player)
            case "ability" if ev.get("effect") == "none":
                self._say(f"{MARKET_NAMES[ev['card']]} has no effect")
            case "game_over":
                pass

    def _end_game(self) -> None:
        game = self.game
        assert game is not None and game.result is not None
        res = game.result
        winner = res["winner"]
        why = ", ".join(REASONS.get(r, r) for r in res["reasons"])
        tie = ""
        if res["tie"]:
            loser = 1 - winner
            other = ", ".join(REASONS.get(r, r) for r in res["claims"][loser])
            tie = f" — {self._side_name(loser)} also {other}, and a tie goes to the active team"
        log.info("table %s: game %d won by %s (%s)", self.id, self.game_no, self._side_name(winner), res["reasons"])
        self._say(f"🏆 {self._side_name(winner)} won: {why}{tie}!")

    # ------------------------------------------------------------------ automation
    def _deciders(self, game: Game) -> list[int]:
        """Players whose decision the table waits for now (a human beats a bot in the same team)."""
        waiting = game.waiting()
        lead = self.lead
        team_lead = game.phase == Phase.PLAY and game.up is None and not game.solo(game.active)
        if team_lead and lead is not None and lead[0] == game.turn and lead[1] in waiting:
            return [lead[1]]
        return waiting

    def bot_turn(self) -> int | None:
        """The bot seat that should move now, or None when waiting for a human."""
        if self.status != "playing" or self.game is None:
            return None
        deciders = self._deciders(self.game)
        if not deciders or any(not self._is_auto(p) for p in deciders):
            return None
        return deciders[0]

    def _bot_delay(self, game: Game) -> float:
        base = {Phase.PLAY: 1.0, Phase.RECRUIT: 1.2, Phase.MARKET: 1.2, Phase.CHOICE: 1.0}.get(game.phase, 1.0)
        return base * BOT_SPEEDS[self.settings.bot_speed] * self.delay_scale

    async def drive(self) -> None:
        """Run bot moves until the room is closed. Bots think in a thread while the browsers animate."""
        while not self.closed:
            self._wake.clear()
            seat = self.bot_turn()
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
                await self._timeout()
                continue
            game = self.game
            assert game is not None
            version = self.version
            ready_at = max(self.busy_until, time.monotonic()) + self._bot_delay(game)
            view = game.redacted(seat)
            self.thinking = seat
            try:
                action = await asyncio.to_thread(self._agent(seat).act, view, seat)
            except Exception:
                log.exception("room %s: bot failed", self.id)
                self.thinking = None
                self._say("⚠️ A bot crashed; the game is back in the lobby")
                self._to_lobby()
                continue
            self.thinking = None
            wait = ready_at - time.monotonic()
            if wait > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), wait)
                    if self.version != version:
                        continue
                    remaining = ready_at - time.monotonic()
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                except TimeoutError:
                    pass
            if self.version != version or self.game is not game or self.closed:
                continue
            if self.bot_turn() != seat:  # e.g. the player came back and took over from the autopilot
                continue
            try:
                self._apply(seat, action)
            except RoomError:
                log.exception("room %s: bot chose an illegal move", self.id)
            await asyncio.sleep(0)

    def _refresh_deadline(self) -> None:
        """With a turn timer, each human decision gets its own deadline (counted from when the table is ready)."""
        timer = self.settings.turn_timer
        game = self.game
        key: tuple[Any, ...] | None = None
        if timer and self.status == "playing" and game is not None:
            humans = tuple(p for p in self._deciders(game) if not self._is_auto(p))
            if humans:
                key = (self.game_no, self.version, humans)
        if key is None:
            self._deadline = None
        elif self._deadline is None or self._deadline[0] != key:
            self._deadline = (key, max(self.busy_until, time.monotonic()) + timer)

    async def _timeout(self) -> None:
        """A human ran out of time: the autopilot finishes their part of the turn."""
        game = self.game
        self._deadline = None
        if game is None or self.status != "playing":
            return
        humans = [p for p in self._deciders(game) if not self._is_auto(p)]
        if not humans:
            return
        seat = humans[0]
        self._say(f"⏱ {self.seats[seat].name} ran out of time — the autopilot moves", seat)
        turn, phase = game.turn, game.phase
        for _ in range(6):
            if self.game is not game or self.status != "playing" or game.turn != turn or game.phase != phase:
                break
            if seat not in self._deciders(game):
                break
            version = self.version
            action = await asyncio.to_thread(self._autopilot.act, game.redacted(seat), seat)
            if self.version != version or self.game is not game:
                break
            try:
                self._apply(seat, action)
            except RoomError:
                log.exception("room %s: the autopilot chose an illegal move", self.id)
                break

    def step_bots(self, limit: int = 10_000) -> None:
        """Play all pending bot moves synchronously (tests and scripted demos)."""
        for _ in range(limit):
            seat = self.bot_turn()
            if seat is None:
                return
            game = self.game
            assert game is not None
            self._apply(seat, self._agent(seat).act(game.redacted(seat), seat))

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
                    "team": s.team,
                    "color": TEAM_COLORS[s.team],
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
        if event is not None and event.get("kind") == "move":
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
            "thinking": self.thinking,
            "game": self._game_state(you),
        }

    def _filter_event(self, ev: Event, you: int | None) -> Event:
        if ev.get("player") == you:
            return ev
        kind = ev["kind"]
        if kind == "draw":
            return {**ev, "cards": [None] * len(ev["cards"])}
        if kind == "discard":
            return {**ev, "card": None}
        if kind == "play" and ev["down"] is not None:
            return {**ev, "down": None}
        return ev

    def _game_state(self, you: int | None) -> dict[str, Any] | None:
        game = self.game
        if game is None:
            return None
        over = game.phase == Phase.OVER
        players = []
        for p in range(game.n_players):
            players.append(
                {
                    "side": game.side_of[p],
                    "hand": len(game.hands[p]),
                    "discards": len(game.discards[p]),
                    "discards_left": game.discards_left[p],
                    "known": [AGENT_LIST[c].key for c in game.known[p]],
                    "hand_cards": [AGENT_LIST[c].key for c in sorted(game.hands[p])] if over else None,
                }
            )
        sides = []
        for side in (0, 1):
            sides.append(
                {
                    "pos": game.pos[side],
                    "square": game.square(side),
                    "distance": game.distance(side),
                    "tableau": {AGENT_LIST[c].key: n for c, n in enumerate(game.tableau[side]) if n},
                    "owned": [MARKET_LIST[m].key for m in game.owned[side]],
                    "members": game.sides[side],
                }
            )
        up = {"player": game.up[0], "card": AGENT_LIST[game.up[1]].key} if game.up else None
        down = None
        if game.down is not None:
            visible = game.down[0] == you
            down = {"player": game.down[0], "card": AGENT_LIST[game.down[1]].key if visible else None}
        choice = None
        if game.choice is not None:
            ch = game.choice
            choice = {
                "player": ch["player"],
                "side": ch["side"],
                "card": MARKET_LIST[ch["card"]].key,
                "stage": ch["stage"],
                "agent": AGENT_LIST[ch["agent"]].key if ch["agent"] >= 0 else None,
                "options": [choice_json(ch["stage"], o) for o in ch["options"]],
            }
        state: dict[str, Any] = {
            "phase": game.phase.value,
            "active": game.active,
            "turn": game.turn,
            "advanced": game.advanced,
            "track": TRACK,
            "deck": len(game.deck),
            "players": players,
            "sides": sides,
            "up": up,
            "down": down,
            "supply": [MARKET_LIST[m].key for m in game.supply],
            "market_deck": len(game.market_deck),
            "market_discard": [MARKET_LIST[m].key for m in game.market_discard],
            "queue": list(game.queue),
            "choice": choice,
            "waiting": self._deciders(game) if not over else [],
            "lead": self.lead[1] if self.lead and self.lead[0] == game.turn else None,
            "result": game.result,
            "me": self._my_state(game, you) if you is not None else None,
        }
        if self._deadline is not None and not over:
            state["time_left"] = round(max(0.0, self._deadline[1] - time.monotonic()), 2)
            state["time_total"] = self.settings.turn_timer
        return state

    def _my_state(self, game: Game, seat: int) -> dict[str, Any]:
        playing = self.status == "playing" and not self.seats[seat].autoplay
        legal = game.legal(seat) if playing else []
        return {
            "hand": [AGENT_LIST[c].key for c in game.hands[seat]],
            "discards": [AGENT_LIST[c].key for c in game.discards[seat]],
            "legal": [actions.to_json(a) for a in legal if a[0] != "choose"],
            "can_discard": playing and game.can_discard(seat),
            "can_lead": playing
            and game.phase == Phase.PLAY
            and game.up is None
            and not game.solo(game.side_of[seat])
            and game.side_of[seat] == game.active
            and any(self._is_auto(p) for p in game.sides[game.active] if p != seat),
        }
