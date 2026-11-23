"""A multiplayer table: members, seats (humans or bots), lobby settings and the game.

All mutations are synchronous and run on the event loop thread. Every change is pushed to each listener as
a full per-viewer snapshot (`Room.state_for`) tagged with the events that caused it, so clients can animate
them. Karak has almost no hidden information: only the oracle's second token is private until the game ends.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boardgames.table import MAX_NAME, Member, RoomError, Table, clean_text
from karak.bots import REGISTRY, Bot, PlannerBot
from karak.game import actions
from karak.game.actions import Action
from karak.game.engine import Event, Game, IllegalMove, Phase, RulesConfig
from karak.game.model import (
    BASE_HEROES,
    CHEST,
    CHESTS,
    CORNER,
    CROSS,
    DIR_NAMES,
    HEROES,
    ITEMS,
    MONSTERS,
    REGENT_HEROES,
    REGENT_MONSTERS,
    REGENT_TILES,
    STRAIGHT,
    TEE,
    TILE_PILE,
    Hero,
    Kind,
)

log = logging.getLogger(__name__)

MAX_SEATS = 5
MIN_SEATS = 1
REACTIONS = ("👍", "😂", "😱", "😡", "🎉", "🤔", "😭", "🔥", "👏", "💀")
BOT_SPEEDS = {"slow": 1.8, "normal": 1.0, "fast": 0.4}
TURN_TIMERS = (0, 30, 60, 90, 180)
HERO_COLORS = {
    Hero.WARRIOR: "red",
    Hero.THIEF: "green",
    Hero.WIZARD: "blue",
    Hero.WARLOCK: "purple",
    Hero.SWORDSMAN: "gold",
    Hero.ORACLE: "teal",
    Hero.BARBARIAN: "orange",
    Hero.BATTLEMAGE: "indigo",
    Hero.ACROBAT: "pink",
    Hero.RANGER: "olive",
    Hero.LORD: "ember",
}

Plan = tuple[float, Callable[[], None]]

SHAPES = {STRAIGHT: "straight", CORNER: "corner", TEE: "tee", CROSS: "cross"}
PILE_KINDS = (Kind.ROOM, Kind.CORRIDOR, Kind.FOUNTAIN, Kind.PORTAL)
REGENT_KINDS = (Kind.ARENA, Kind.CURSED)


def pile_summary(pile: list[tuple[Kind, int]], expansion: bool = False) -> list[dict[str, Any]]:
    """What is left in the tile pile, per kind and base shape (the order stays hidden)."""
    left = Counter(pile)
    out = []
    tiles = TILE_PILE + (REGENT_TILES if expansion else ())
    for kind in PILE_KINDS + (REGENT_KINDS if expansion else ()):
        totals = Counter[int]()
        for k, mask, n in tiles:
            if k == kind:
                totals[mask] += n
        rows = [(SHAPES[mask], left[(kind, mask)], n) for mask, n in totals.items()]
        out.append(
            {
                "kind": kind.value,
                "left": sum(r[1] for r in rows),
                "total": sum(r[2] for r in rows),
                "shapes": {name: n for name, n, _ in rows},
            }
        )
    return out


def bag_summary(bag: list[str], expansion: bool = False) -> list[dict[str, Any]]:
    """How many of each token are still in the bag, strongest monster first, chests last."""
    left = Counter(bag)
    monsters = sorted(
        (m for m in MONSTERS.values() if expansion or m.key not in REGENT_MONSTERS), key=lambda m: -m.strength
    )
    tokens = [(m.key, m.count) for m in monsters] + [(CHEST, CHESTS)]
    return [{"key": key, "left": left[key], "total": total} for key, total in tokens]


@dataclass
class Settings:
    turn_timer: int = 0  # seconds per human turn, 0 = off
    bot_speed: str = "normal"
    hints: bool = False
    peek: bool = False  # players may not see which tiles and tokens are left, only how many
    expansion: bool = False  # Karak: Regent: new tiles, heroes and monsters
    lord: bool = False  # the Lord of Karak game version (only with the expansion)

    def update(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "turn_timer" and value in TURN_TIMERS:
                self.turn_timer = int(value)
            elif key == "bot_speed" and value in BOT_SPEEDS:
                self.bot_speed = str(value)
            elif key in ("hints", "peek", "expansion", "lord") and isinstance(value, bool):
                setattr(self, key, value)
            else:
                raise RoomError(f"invalid setting {key}={value!r}")
        if not self.expansion:
            self.lord = False  # the Lord of Karak only exists with the expansion


@dataclass
class Seat:
    name: str
    member_id: str | None = None  # None: a bot
    bot: str | None = None  # REGISTRY key
    hero: Hero | None = None  # None: random at the start
    agent: Bot | None = None
    autoplay: bool = False  # a human seat temporarily played by the autopilot

    @property
    def is_bot(self) -> bool:
        return self.member_id is None


def bots_public() -> list[dict[str, Any]]:
    return [
        {"key": b.key, "label": b.label, "stars": b.stars, "description": b.description, "expansion": b.expansion}
        for b in REGISTRY.values()
    ]


def heroes_public() -> list[dict[str, Any]]:
    return [
        {
            "key": h.key.value,
            "name": h.name,
            "color": HERO_COLORS[h.key],
            "skills": [{"name": n, "text": t} for n, t in h.skills],
            "expansion": h.key in REGENT_HEROES,
            "pickable": h.key != Hero.LORD,
        }
        for h in HEROES.values()
    ]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _points(half: int) -> str:
    return f"{half // 2}½" if half % 2 else str(half // 2)


class Room(Table):
    MAX_SEATS = MAX_SEATS
    REACTIONS = REACTIONS

    def __init__(self, room_id: str, delay_scale: float = 1.0, seed: int | None = None) -> None:
        super().__init__(room_id, delay_scale, seed)
        self.settings = Settings()
        self.game: Game | None = None
        self.game_no = 0
        self._autopilot = PlannerBot(seed=self.rng.randrange(2**31))
        self._step = 0  # counts game steps so bot delays restart after each one

    # ------------------------------------------------------------------ members
    def _new_seat(self, member: Member) -> Seat:
        return Seat(name=member.name, member_id=member.id)

    def _welcome_extra(self) -> dict[str, Any]:
        return {"bots": bots_public(), "heroes": heroes_public()}

    def _lineup(self) -> str:
        return ", ".join(f"{s.name} (bot)" if s.is_bot else s.name for s in self.seats) or "nobody seated"

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
            case "pick_hero":
                self._pick_hero(member, msg.get("seat"), msg.get("hero"))
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
                if not self.settings.expansion:
                    for seat in self.seats:
                        if seat.hero in REGENT_HEROES:
                            seat.hero = None
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

    def _pick_hero(self, member: Member, seat: object, hero: object) -> None:
        self._require_lobby()
        mine = self.seat_of(member.id)
        if seat is None:
            seat = mine
        if not isinstance(seat, int) or not 0 <= seat < len(self.seats):
            raise RoomError("No such seat")
        target = self.seats[seat]
        if seat != mine and not (target.is_bot and member.id == self.host_id):
            raise RoomError("You can only pick your own hero")
        if hero is None:
            target.hero = None
        else:
            try:
                choice = Hero(hero)
            except ValueError:
                raise RoomError("Unknown hero") from None
            if choice == Hero.LORD or (choice in REGENT_HEROES and not self.settings.expansion):
                raise RoomError("That hero is not at this table")
            taken = next((s for s in self.seats if s.hero == choice and s is not target), None)
            if taken is not None:
                raise RoomError(f"{taken.name} already plays the {HEROES[choice].name}")
            target.hero = choice
        self._emit({"kind": "lobby"})

    def _add_bot(self, key: str) -> None:
        self._require_lobby()
        bot = REGISTRY.get(key)
        if bot is None:
            raise RoomError("Unknown bot")
        if len(self.seats) >= MAX_SEATS:
            raise RoomError("The table is full")
        if self.settings.expansion and not bot.expansion:
            raise RoomError(f"The {bot.label} only knows the base game. Turn Karak: Regent off or pick another bot")
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
        regent = self.settings.expansion
        pool = (*BASE_HEROES, *REGENT_HEROES) if regent else BASE_HEROES
        free = [h for h in pool if h not in {s.hero for s in self.seats}]
        self.rng.shuffle(free)
        heroes = [s.hero or free.pop() for s in self.seats]
        for seat in self.seats:
            if regent and seat.bot and not REGISTRY[seat.bot].expansion:
                seat.bot = "champion"  # a trained network can't play the expansion
                self._say(f"{seat.name} swaps to the Champion's tactics: the AI only knows the base game")
            seat.agent = REGISTRY[seat.bot].make(self.rng.randrange(2**31)) if seat.bot else None
            seat.autoplay = False
        rules = RulesConfig(expansion=regent, lord=regent and self.settings.lord)
        self.game = Game(heroes, seed=self.rng.randrange(2**63), rules=rules)
        self.game_no += 1
        self.status = "playing"
        log.info("table %s: game %d started with %s", self.id, self.game_no, self._lineup())
        lineup = ", ".join(f"{s.name} the {HEROES[h].name}" for s, h in zip(self.seats, heroes, strict=True))
        self._say(f"Game {self.game_no}: {lineup} descend into the labyrinth.")
        if rules.lord:
            self._say(
                "👑 The Lord of Karak stirs: when 5 arenas and cursed chambers are found, he claims the weakest hero."
            )
        first = self.game.current
        self._say(f"🎲 {self.seats[first].name} rolled highest and goes first.", first)
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
        try:
            events = game.step(seat, action)
        except IllegalMove as e:
            raise RoomError(str(e)) from None
        self._step += 1
        for ev in events:
            self._narrate(ev)
        if game.phase == Phase.GAME_OVER:
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
            case "place":
                kind = ev["tile"]["kind"]
                if kind == Kind.FOUNTAIN:
                    self._say(f"⛲ {name} found a healing fountain", seat)
                elif kind == Kind.PORTAL:
                    self._say(f"🌀 {name} found a teleportation gate", seat)
                elif kind == Kind.ARENA:
                    self._say(f"⚔️ {name} found a battle arena", seat)
                elif kind == Kind.CURSED:
                    self._say(f"☠️ {name} found a cursed chamber", seat)
                if not ev.get("enter", True):
                    self._say(f"👂 {name} listens at the door without stepping in", seat)
            case "token" if ev["token"] == "chest":
                self._say(f"{name} found a locked [chest]", seat)
            case "token":
                m = MONSTERS[ev["token"]]
                self._say(f"{name} disturbed a [{m.key}] {m.name} (strength {m.strength})!", seat)
            case "dragon_awakens":
                self._say("🐉 The labyrinth is complete. The Dragon wakes in its deepest room!")
            case "choose_token":
                self._say(f"🔮 {name} foresaw two fates and chose one", seat)
            case "sneak":
                self._say(f"🥷 {name} slipped past the {MONSTERS[ev['monster']].name}", seat)
            case "roll" if ev.get("bear"):
                self._say(f"🐻 The bear turns {_plural(ev['bear'], 'die')} into a six for {name}", seat)
            case "roll" if ev["reroll"]:
                self._say(f"{name} swings again: 🎲 {ev['dice'][0]} + {ev['dice'][1]}", seat)
            case "strike":
                m = MONSTERS[ev["monster"]]
                extra = []
                if ev["bolts"]:
                    extra.append(f"{_plural(ev['bolts'], 'magic bolt')}")
                if ev["sacrifice"]:
                    extra.append("a blood price")
                using = f" with {' and '.join(extra)}" if extra else ""
                verdict = {"win": "defeated", "tie": "held off", "loss": "was beaten by"}[ev["outcome"]]
                self._say(
                    f"{'⚔️' if ev['outcome'] == 'win' else '🛡' if ev['outcome'] == 'tie' else '💥'} {name} {verdict} "
                    f"the {m.name}{using}: {ev['total']} vs {m.strength}",
                    seat,
                )
            case "loot":
                dropped = f", leaving the [{ev['dropped']}] behind" if ev.get("dropped") else ""
                self._say(f"{name} takes the [{ev['item']}] {ITEMS[ev['item']].name}{dropped}", seat)
            case "leave":
                self._say(f"{name} leaves the [{ev['item']}] {ITEMS[ev['item']].name} on the floor", seat)
            case "pickup":
                dropped = f" and leaves the [{ev['dropped']}]" if ev.get("dropped") else ""
                self._say(f"{name} picks up the [{ev['item']}] {ITEMS[ev['item']].name}{dropped}", seat)
            case "open_chest":
                self._say(f"🗝 {name} unlocked a chest: +1 [treasure]", seat)
            case "curse_roll":
                verdict = "and Karak's curse falls on them" if ev["cursed"] else "and escapes the curse"
                self._say(f"🎲 {name} rolls a {ev['die']} in the cursed chamber {verdict}", seat)
            case "curse" if ev.get("source") == "chamber":
                pass
            case "sprint":
                self._say(f"🤸 {name} sprints across the labyrinth", seat)
            case "blitz":
                self._say(f"⚡ {name} blitzes straight to a monster", seat)
            case "duel":
                self._say(f"⚔️ {name} summons {self._name(ev['defender'])} to a duel in the arena!", seat)
            case "duel_strike":
                self._say(f"🎲 {name} totals {ev['total']} in the duel", seat)
            case "duel_result" if ev["winner"] is None:
                self._say(f"🛡 The duel is a draw: {ev['totals'][0]} vs {ev['totals'][1]}")
            case "duel_result":
                self._say(
                    f"🏅 {self._name(ev['winner'])} wins the duel {ev['totals'][0]} vs {ev['totals'][1]}"
                    f" and {self._name(ev['loser'])} loses a life",
                    ev["winner"],
                )
            case "steal":
                if ev["item"] is None:
                    self._say(f"{name} takes nothing from {self._name(ev['victim'])}", seat)
                else:
                    self._say(
                        f"{name} takes the [{ev['item']}] {ITEMS[ev['item']].name} from {self._name(ev['victim'])}",
                        seat,
                    )
            case "thorn":
                self._say(f"🥀 {name} pricks {self._name(ev['target'])} with a thorn of darkness: -1 life", seat)
            case "lord":
                skills = ", ".join(HEROES[Hero(h)].name for h in ev["skills"])
                self._say(
                    f"👑 The Lord of Karak possesses {name}! Healed, uncursed and now with the skills of: {skills}",
                    seat,
                )
            case "curse":
                self._say(f"☠️ {name} lays the Curse on {self._name(ev['target'])}", seat)
            case "curse_kept":
                self._say(f"☠️ The Curse stays on {self._name(ev['target'])}", seat)
            case "heal" if ev["lifted"]:
                self._say(f"⛲ {self._name(ev['seat'])} is healed and the Curse is lifted", ev["seat"])
            case "heal":
                self._say(f"⛲ {self._name(ev['seat'])} heals {_plural(ev['hp'], 'wound')}", ev["seat"])
            case "knocked_out":
                self._say(f"💫 {name} falls unconscious and misses the next turn", seat)
            case "recover":
                self._say(f"{name} comes round with 1 HP", seat)
            case "reincarnate":
                self._say(f"🔥 {name} refuses to die and rises again at a fountain", seat)
            case "relentless":
                self._say(f"🗡 Rolled a six! {name} presses on", seat)
            case "swap":
                self._say(f"🔄 {name} swaps places with {self._name(ev['other'])}", seat)
            case "cast_healing":
                target = "themself" if ev["target"] == seat else self._name(ev["target"])
                self._say(f"✨ {name} opens a portal of healing for {target}", seat)
            case "teleport":
                self._say(f"🌀 {name} steps through a gate", seat)

    def _end_game(self) -> None:
        game = self.game
        assert game is not None and game.result is not None
        res = game.result
        winners = " & ".join(self.seats[w].name for w in res.winners)
        scores = ", ".join(f"{s.name} {_points(r.points)}" for s, r in zip(self.seats, res.players, strict=True))
        log.info("table %s: game %d won by %s (%s)", self.id, self.game_no, winners, scores)
        if res.dragon_slain_by is not None:
            self._say(f"🐉 {self._name(res.dragon_slain_by)} slew the Dragon!", res.dragon_slain_by)
        self._say(f"🏆 {winners} won! Treasure: {scores}")

    # ------------------------------------------------------------------ hints
    def _hint(self, member: Member) -> dict[str, Any]:
        if not self.settings.hints:
            raise RoomError("Hints are turned off at this table")
        seat = self.seat_of(member.id)
        if seat is None:
            raise RoomError("You are watching this game")
        game = self._game()
        if game.actor != seat:
            raise RoomError("It's not your turn")
        action = self._autopilot.act(game.view(seat))
        return {"type": "hint", "action": actions.to_json(action)}

    # ------------------------------------------------------------------ automation

    def _bot_delay(self, base: float) -> float:
        return base * BOT_SPEEDS[self.settings.bot_speed]

    def plan(self) -> Plan | None:
        """The next automatic step as (seconds to wait, action), or None to wait for a human."""
        if self.status != "playing" or self.game is None:
            return None
        game = self.game
        if self._is_auto(game.actor):
            base = {
                Phase.TURN: 0.75,
                Phase.PLACE: 0.7,
                Phase.COMBAT: 0.9,
                Phase.ROLLED: 1.5,
                Phase.LOOT: 0.9,
                Phase.CURSE: 1.0,
                Phase.CHOOSE_TOKEN: 1.0,
                Phase.CHALLENGE: 1.0,
                Phase.STEAL: 1.0,
                Phase.RETREAT: 0.9,
            }.get(game.phase, 0.8)
            if game.phase == Phase.TURN and game.used == 0:
                base = 1.1
            delay = self._wait(("move", self.game_no, self._step), self._bot_delay(base))
            return delay, lambda s=game.actor: self._auto_move(s)
        if self._deadline is not None:
            return max(0.0, self._deadline[1] - time.monotonic()), self._timeout
        return None

    def _refresh_deadline(self) -> None:
        timer = self.settings.turn_timer
        key: tuple[Any, ...] | None = None
        game = self.game
        if timer and self.status == "playing" and game is not None and not self._is_auto(game.actor):
            key = ("turn", self.game_no, game.turn, game.actor)
        if key is None:
            self._deadline = None
        elif self._deadline is None or self._deadline[0] != key:
            self._deadline = (key, time.monotonic() + timer)

    def _timeout(self) -> None:
        game = self._game()
        seat = game.actor
        self._say(f"⏱ {self.seats[seat].name} ran out of time; the autopilot finishes the turn")
        turn = game.turn
        while self.status == "playing" and game.turn == turn and game.actor == seat:
            self._auto_move(seat)

    # ------------------------------------------------------------------ output

    def _color(self, i: int) -> str:
        if self.game is not None and i < len(self.game.players):
            return HERO_COLORS[self.game.players[i].hero]
        hero = self.seats[i].hero
        return HERO_COLORS[hero] if hero else "stone"

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
                    "hero": s.hero.value if s.hero else None,
                    "color": self._color(i),
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
            "game": self._game_state(you),
        }

    def _filter_event(self, ev: Event, you: int | None) -> Event:
        if self.status == "game_over" or ev.get("seat") == you:
            return ev
        if ev["kind"] == "offer":
            return {**ev, "tokens": None}
        if ev["kind"] == "choose_token":
            return {**ev, "returned": None}
        return ev

    def _game_state(self, you: int | None) -> dict[str, Any] | None:
        game = self.game
        if game is None:
            return None
        over = game.phase == Phase.GAME_OVER
        peek = self.settings.peek or over
        current = game.current if not over else None
        actor = game.actor if not over else None
        pending = None
        if game.pending is not None:
            p = game.pending
            pending = {
                "x": p.pos.x,
                "y": p.pos.y,
                "kind": p.kind.value,
                "mask": p.mask,
                "rotations": p.rotations,
                "enter": p.enter,
            }
        mine = you is not None and you == actor and not self.seats[you].autoplay and self.status == "playing"
        state: dict[str, Any] = {
            "phase": game.phase.value,
            "current": current,
            "turn": game.turn,
            "round": game.turn // max(1, game.n) + 1,
            "moves_left": game.moves_left,
            "moves": game.rules.moves,
            "max_hp": game.rules.max_hp,
            "tiles": [t.to_json() for t in game.tiles.values()],
            "players": [{**p.to_json(), "power": game.attack_power(i)} for i, p in enumerate(game.players)],
            "cursed": game.cursed,
            "combat": game.combat.to_json() if game.combat else None,
            "actor": actor,
            "bonus": game.combat_bonus(game.actor) if game.combat else 0,
            "expansion": game.rules.expansion,
            "lord": game.lord,
            "lord_mode": game.rules.lord,
            "spoils": list(game.spoils) if game.spoils else None,
            "chambers": sum(1 for t in game.tiles.values() if t.kind in (Kind.ARENA, Kind.CURSED)),
            "pending": pending,
            "offer": list(game.offer) if mine or over else [],
            "offer_size": len(game.offer),
            "loot_item": game.loot_item,
            "pile_left": len(game.pile),
            "pile": pile_summary(game.pile, game.rules.expansion) if peek else None,
            "bag_left": len(game.bag),
            "bag": bag_summary(game.bag, game.rules.expansion) if peek else None,
            "dragon_seen": "dragon" not in game.bag,
            "legal": [actions.to_json(a) for a in game.legal_actions(you)] if mine and you is not None else [],
            "result": self._result(game) if over else None,
            "time_left": None,
        }
        if self._deadline is not None:
            state["time_left"] = round(max(0.0, self._deadline[1] - time.monotonic()), 2)
            state["time_total"] = self.settings.turn_timer
        return state

    def _result(self, game: Game) -> dict[str, Any]:
        assert game.result is not None
        return {
            "winners": game.result.winners,
            "dragon_slain_by": game.result.dragon_slain_by,
            "players": [dataclasses.asdict(r) for r in game.result.players],
        }


__all__ = ["DIR_NAMES", "MAX_SEATS", "Room", "RoomError", "bots_public", "heroes_public"]
