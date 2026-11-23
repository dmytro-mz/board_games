"""The game state machine: `Game.play(seat, action) -> events`, `Game.view(seat)` for bots.

A turn is: up to 4 actions (ACTIONS) → draw 2 player cards (DRAW) → resolve each Epidemic drawn, pausing between
its Infect and Intensify steps (EPIDEMIC) → infect cities (INFECT) → next player. Event cards can be played by
anyone at any time except during an epidemic, where only Resilient Population is allowed. Whoever holds more than
7 cards must discard (or play events) before anything else happens; the player who drew only after their
epidemics are resolved. A pending Forecast blocks everything until its cards are put back.

The team wins the moment the fourth cure is discovered. It loses at the 8th outbreak, when a disease runs out of
cubes, or when the player deck can't supply the 2 cards to draw.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from typing import Any

from pandemic.game.actions import (
    EVENT_ACTIONS,
    TURN_ACTIONS,
    Action,
    Airlift,
    Build,
    CharterFlight,
    Continue,
    Cure,
    DirectFlight,
    Discard,
    Dispatch,
    DrawCards,
    Drive,
    Forecast,
    ForecastOrder,
    Give,
    GovernmentGrant,
    OneQuietNight,
    OpsFlight,
    Pass,
    ResilientPopulation,
    ShuttleFlight,
    Take,
    TakeEvent,
    Treat,
)
from pandemic.game.model import (
    ACTIONS_PER_TURN,
    ADJ,
    CITIES,
    COLORS,
    CUBES_PER_COLOR,
    EPIDEMIC,
    EVENT_NAMES,
    EVENTS,
    FORECAST_CARDS,
    HAND_LIMIT,
    INFECTION_RATE,
    MAX_OUTBREAKS,
    MAX_STATIONS,
    START_CITY,
    STARTING_HAND,
    Color,
    EventCard,
    Role,
    path,
)

Event = dict[str, Any]
HIDDEN = "?"  # a card a sandbox doesn't know


class Step(StrEnum):
    ACTIONS = "actions"
    DRAW = "draw"
    EPIDEMIC = "epidemic"
    INFECT = "infect"
    GAME_OVER = "game_over"


class IllegalMove(ValueError):
    """The action is not allowed now; the game state is unchanged. The message is for the player."""


@dataclass(frozen=True)
class RulesConfig:
    epidemics: int = 5
    roles: tuple[Role | None, ...] | None = None  # per seat; None (or a None entry) deals a random role

    def __post_init__(self) -> None:
        if not 4 <= self.epidemics <= 6:
            raise ValueError("epidemics must be 4, 5 or 6")


@dataclass
class Result:
    won: bool
    reason: str  # cured | outbreaks | cubes | deck
    turn: int
    color: str | None = None  # the color that ran out of cubes

    def to_json(self) -> dict[str, Any]:
        return {"won": self.won, "reason": self.reason, "turn": self.turn, "color": self.color}


def name(city: str) -> str:
    c = CITIES.get(city)
    return c.name if c else city


def need_for_cure(role: Role) -> int:
    return 4 if role == Role.SCIENTIST else 5


@dataclass
class View:
    """Everything one seat may know. Bots decide from this only."""

    seat: int
    n: int
    step: Step
    current: int
    waiting_for: int | None
    actions_left: int
    roles: list[Role]
    locations: list[str]
    hands: list[list[str] | None]  # None: hidden (closed hands)
    hand_counts: list[int]
    stored: list[str | None]
    cubes: dict[str, dict[Color, int]]
    supply: dict[Color, int]
    stations: list[str]
    cures: dict[Color, str]
    outbreaks: int
    epidemics_drawn: int
    epidemics: int
    player_deck_size: int
    pile_sizes: list[int]
    player_discard: list[str]
    infection_deck_size: int
    infection_discard: list[str]
    known_top: list[str]  # cities put back on top of the infection deck by the last epidemic, not drawn yet
    quiet_night: bool
    ops_flight_used: bool
    forecast: list[str] | None  # the cards to arrange, if this seat is arranging a Forecast
    turn: int
    open_hands: bool = True
    removed: list[str] = field(default_factory=list)

    @property
    def infection_rate(self) -> int:
        return INFECTION_RATE[min(self.epidemics_drawn, len(INFECTION_RATE) - 1)]

    def sandbox(self) -> Game:
        """A game built from this view to try actions on: hidden cards are placeholders."""
        return Game.from_view(self)


class Game:
    def __init__(self, n: int, seed: int | None = None, rules: RulesConfig | None = None) -> None:
        if not 2 <= n <= 4:
            raise ValueError("Pandemic is for 2 to 4 players")
        self.n = n
        self.rules = rules or RulesConfig()
        self.rng = random.Random(seed)
        self.roles = self._deal_roles()
        self.location = [START_CITY] * n
        self.hands: list[list[str]] = [[] for _ in range(n)]
        self.stored: list[str | None] = [None] * n  # the Contingency Planner's event card
        self.cubes: dict[str, dict[Color, int]] = {c: dict.fromkeys(COLORS, 0) for c in CITIES}
        self.supply: dict[Color, int] = dict.fromkeys(COLORS, CUBES_PER_COLOR)
        self.stations = [START_CITY]
        self.cures: dict[Color, str] = dict.fromkeys(COLORS, "none")  # none | cured | eradicated
        self.outbreaks = 0
        self.epidemics_drawn = 0
        self.player_deck: list[str] = []  # top is the end of the list
        self.player_discard: list[str] = []
        self.removed: list[str] = []  # out of the game: stored events once played, Resilient Population targets
        self.infection_deck = list(CITIES)
        self.infection_discard: list[str] = []
        self.known_top: list[str] = []
        self.pile_sizes: list[int] = []
        self.turn = 0
        self.current = 0
        self.actions_left = 0
        self.step = Step.ACTIONS
        self.drawn: list[str] = []  # the player cards drawn this turn
        self.pending_epidemics = 0
        self.quiet_night = False
        self.ops_flight_used = False
        self.forecast: tuple[int, list[str]] | None = None
        self.result: Result | None = None
        self.stats: dict[str, list[int]] = {k: [0] * n for k in ("treated", "built", "cured", "shared", "events")}
        self.track_undo = True
        self._undo: list[Game] = []
        self._setup = True
        self.setup_events = self._set_up()
        self._setup = False

    # ------------------------------------------------------------------ setup
    def _deal_roles(self) -> list[Role]:
        wanted = list(self.rules.roles or [None] * self.n)
        if len(wanted) != self.n:
            raise ValueError("one role per seat")
        chosen = [r for r in wanted if r is not None]
        if len(set(chosen)) != len(chosen):
            raise ValueError("two seats can't have the same role")
        free = [r for r in Role if r not in chosen]
        self.rng.shuffle(free)
        return [r if r is not None else free.pop() for r in wanted]

    def _set_up(self) -> list[Event]:
        events: list[Event] = []
        self.rng.shuffle(self.infection_deck)
        for count in (3, 2, 1):
            for _ in range(3):
                city = self.infection_deck.pop()
                self.infection_discard.append(city)
                events.append(
                    {
                        "kind": "infect",
                        "city": city,
                        "color": CITIES[city].color,
                        "placed": count,
                        "cubes": count,
                        "setup": True,
                    }
                )
                self._add(city, CITIES[city].color, count)
        deck = list(CITIES) + list(EVENTS)
        self.rng.shuffle(deck)
        for _ in range(STARTING_HAND[self.n]):
            for seat in range(self.n):
                self.hands[seat].append(deck.pop())
        k = self.rules.epidemics
        q, r = divmod(len(deck), k)
        sizes = [q + 1] * r + [q] * (k - r)  # top pile first: the bigger piles go on top
        piles = []
        for size in sizes:
            pile = [deck.pop() for _ in range(size)] + [EPIDEMIC]
            self.rng.shuffle(pile)
            piles.append(pile)
        self.player_deck = [card for pile in reversed(piles) for card in pile]
        self.pile_sizes = [s + 1 for s in sizes]
        first = max(
            range(self.n),
            key=lambda s: (max((CITIES[c].population for c in self.hands[s] if c in CITIES), default=0), -s),
        )
        events.append({"kind": "setup", "first": first, "roles": [r.value for r in self.roles]})
        self._begin_turn(first, events)
        return events

    # ------------------------------------------------------------------ queries
    @property
    def infection_rate(self) -> int:
        return INFECTION_RATE[min(self.epidemics_drawn, len(INFECTION_RATE) - 1)]

    def need(self, seat: int) -> int:
        return need_for_cure(self.roles[seat])

    def seats_at(self, city: str) -> list[int]:
        return [s for s in range(self.n) if self.location[s] == city]

    def over_limit(self) -> int | None:
        """The seat that must discard down to 7 cards now (the drawer only once their epidemics are resolved)."""
        for i in range(self.n):
            seat = (self.current + i) % self.n
            if seat == self.current and self.step == Step.EPIDEMIC:
                continue
            if len(self.hands[seat]) > HAND_LIMIT:
                return seat
        return None

    def waiting_for(self) -> int | None:
        """The seat whose decision the game waits for (others may still play events in some steps)."""
        if self.result is not None:
            return None
        if self.forecast is not None:
            return self.forecast[0]
        over = self.over_limit()
        return self.current if over is None else over

    def can_undo(self, seat: int) -> bool:
        return bool(self._undo) and seat == self.current and self.step == Step.ACTIONS and self.result is None

    def cube_total(self, color: Color) -> int:
        return CUBES_PER_COLOR - self.supply[color]

    def card_count(self) -> int:
        """Player cards everywhere; always 48 cities + 5 events + the epidemics."""
        return (
            sum(len(h) for h in self.hands)
            + sum(1 for s in self.stored if s)
            + len(self.player_deck)
            + len(self.player_discard)
            + sum(1 for c in self.removed if c in EVENTS)
        )

    def infection_count(self) -> int:
        """Infection cards everywhere; always 48."""
        return len(self.infection_deck) + len(self.infection_discard) + sum(1 for c in self.removed if c in CITIES)

    def holder_of(self, card: str) -> int | None:
        for s in range(self.n):
            if card in self.hands[s] or self.stored[s] == card:
                return s
        return None

    # ------------------------------------------------------------------ cubes
    def _protected(self, city: str, color: Color) -> str | None:
        if self._setup:
            return None
        for s in range(self.n):
            at = self.location[s]
            if self.roles[s] == Role.QUARANTINE_SPECIALIST and (at == city or city in ADJ[at]):
                return "quarantine"
            if self.roles[s] == Role.MEDIC and at == city and self.cures[color] != "none":
                return "medic"
        return None

    def _add(self, city: str, color: Color, count: int) -> None:
        if self.supply[color] < count:
            self.cubes[city][color] += self.supply[color]
            self.supply[color] = 0
            self._lose("cubes", color.value)
            return
        self.cubes[city][color] += count
        self.supply[color] -= count

    def _remove(self, city: str, color: Color, count: int) -> None:
        self.cubes[city][color] -= count
        self.supply[color] += count

    def _infect(self, city: str, color: Color, count: int, events: list[Event], **tags: Any) -> None:
        """Put `count` cubes on `city` (an infection card or an epidemic); a 4th cube becomes an outbreak."""
        if self.cures[color] == "eradicated":
            events.append({"kind": "prevented", "city": city, "color": color, "by": "eradicated", **tags})
            return
        by = self._protected(city, color)
        if by is not None:
            events.append({"kind": "prevented", "city": city, "color": color, "by": by, **tags})
            return
        have = self.cubes[city][color]
        place = min(count, 3 - have)
        boom = have + count > 3
        self._add(city, color, place)
        events.append(
            {
                "kind": "infect",
                "city": city,
                "color": color,
                "placed": place,
                "cubes": self.cubes[city][color],
                "outbreak": boom,
                **tags,
            }
        )
        if boom and self.result is None:
            self._outbreak(city, color, events, set())

    def _outbreak(self, city: str, color: Color, events: list[Event], chain: set[str]) -> None:
        chain.add(city)
        self.outbreaks += 1
        targets = [c for c in ADJ[city] if c not in chain]
        events.append({"kind": "outbreak", "city": city, "color": color, "count": self.outbreaks, "to": targets})
        if self.outbreaks >= MAX_OUTBREAKS:
            self._lose("outbreaks")
            return
        for nb in targets:
            if self.result is not None:
                return
            if nb in chain:  # reached through an earlier branch of this chain
                continue
            by = self._protected(nb, color)
            if by is not None:
                events.append({"kind": "prevented", "city": nb, "color": color, "by": by, "via": city})
            elif self.cubes[nb][color] >= 3:
                self._outbreak(nb, color, events, chain)
            else:
                self._add(nb, color, 1)
                events.append(
                    {
                        "kind": "infect",
                        "city": nb,
                        "color": color,
                        "placed": 1,
                        "cubes": self.cubes[nb][color],
                        "outbreak": False,
                        "via": city,
                    }
                )

    def _check_eradicated(self, color: Color, events: list[Event]) -> None:
        if self.cures[color] == "cured" and self.cube_total(color) == 0:
            self.cures[color] = "eradicated"
            events.append({"kind": "eradicated", "color": color})

    def _medic_sweep(self, seat: int, events: list[Event]) -> None:
        """The Medic clears cubes of cured diseases from their city without an action."""
        if self.roles[seat] != Role.MEDIC:
            return
        city = self.location[seat]
        for color in COLORS:
            n = self.cubes[city][color]
            if n and self.cures[color] != "none":
                self._remove(city, color, n)
                self.stats["treated"][seat] += n
                events.append({"kind": "medic_clear", "seat": seat, "city": city, "color": color, "removed": n})
                self._check_eradicated(color, events)

    def _lose(self, reason: str, color: str | None = None) -> None:
        if self.result is None:
            self.result = Result(False, reason, self.turn, color)
            self.step = Step.GAME_OVER

    # ------------------------------------------------------------------ turn flow
    def _begin_turn(self, seat: int, events: list[Event]) -> None:
        self.current = seat
        self.actions_left = ACTIONS_PER_TURN
        self.step = Step.ACTIONS
        self.ops_flight_used = False
        self.drawn = []
        self.turn += 1
        self._undo.clear()
        events.append({"kind": "turn", "seat": seat, "turn": self.turn})

    def _spend(self) -> None:
        self.actions_left -= 1
        if self.actions_left <= 0:
            self.actions_left = 0
            self.step = Step.DRAW

    def _draw(self, events: list[Event]) -> None:
        seat = self.current
        if len(self.player_deck) < 2:
            events.append({"kind": "deck_empty", "seat": seat})
            self._lose("deck")
            return
        cards = [self.player_deck.pop(), self.player_deck.pop()]
        self.drawn = cards
        events.append({"kind": "draw", "seat": seat, "cards": list(cards)})
        for card in cards:
            if card == EPIDEMIC:
                self.player_discard.append(card)
                self.pending_epidemics += 1
            else:
                self.hands[seat].append(card)
        self._next_epidemic(events)

    def _next_epidemic(self, events: list[Event]) -> None:
        if self.pending_epidemics == 0:
            self.step = Step.INFECT
            return
        self.epidemics_drawn += 1
        events.append(
            {"kind": "epidemic", "seat": self.current, "number": self.epidemics_drawn, "rate": self.infection_rate}
        )
        self.step = Step.EPIDEMIC
        if self.infection_deck:
            city = self.infection_deck.pop(0)
            self.infection_discard.append(city)
            self._infect(city, CITIES[city].color, 3, events, epidemic=True)

    def _intensify(self, events: list[Event]) -> None:
        pile = self.infection_discard
        self.rng.shuffle(pile)
        self.infection_deck.extend(pile)
        self.known_top = list(pile)
        self.infection_discard = []
        self.pending_epidemics -= 1
        events.append({"kind": "intensify", "cities": sorted(pile, key=name)})
        self._next_epidemic(events)

    def _infect_cities(self, events: list[Event]) -> None:
        if self.quiet_night:
            self.quiet_night = False
            events.append({"kind": "quiet_night"})
        else:
            events.append({"kind": "infect_step", "rate": self.infection_rate})
            for _ in range(self.infection_rate):
                if not self.infection_deck or self.result is not None:
                    break
                city = self.infection_deck.pop()
                if city in self.known_top:
                    self.known_top.remove(city)
                self.infection_discard.append(city)
                self._infect(city, CITIES[city].color, 1, events)
        if self.result is None:
            self._begin_turn((self.current + 1) % self.n, events)

    # ------------------------------------------------------------------ actions
    def play(self, seat: int, action: Action) -> list[Event]:
        """Apply `action` for `seat` (raises IllegalMove and leaves the state untouched if it isn't allowed)."""
        if self.result is not None:
            raise IllegalMove("The game is over")
        if not 0 <= seat < self.n:
            raise IllegalMove("No such seat")
        events: list[Event] = []
        undoable = False
        if isinstance(action, ForecastOrder):
            self._forecast_order(seat, action, events)
        elif self.forecast is not None:
            raise IllegalMove("Wait until the Forecast cards are back on the deck")
        elif isinstance(action, Discard):
            self._discard(seat, action.card, events)
        elif isinstance(action, EVENT_ACTIONS):
            self._event(seat, action, events)
        else:
            over = self.over_limit()
            if over is not None:
                mine = over == seat
                raise IllegalMove("Discard down to 7 cards first" if mine else "Wait: a player is over the hand limit")
            if seat != self.current:
                raise IllegalMove("It's not your turn")
            if isinstance(action, (*TURN_ACTIONS, Pass)):
                if self.step != Step.ACTIONS:
                    raise IllegalMove("You have no actions left this turn")
                snap = self._snapshot() if self.track_undo else None
                self._turn_action(seat, action, events)
                if snap is not None:
                    self._undo.append(snap)
                undoable = True
            elif isinstance(action, DrawCards):
                if self.step != Step.DRAW:
                    raise IllegalMove(
                        "Use your actions first, or end them"
                        if self.step == Step.ACTIONS
                        else "You already drew your cards"
                    )
                self._draw(events)
            elif isinstance(action, Continue):
                if self.step == Step.EPIDEMIC:
                    self._intensify(events)
                elif self.step == Step.INFECT:
                    self._infect_cities(events)
                else:
                    raise IllegalMove("Nothing to continue")
            else:
                raise IllegalMove(f"unknown action {action!r}")
        if not undoable:
            self._undo.clear()
        if self.result is not None and not any(e["kind"] == "game_over" for e in events):
            events.append({"kind": "game_over", **self.result.to_json()})
        return events

    def _pawn(self, actor: int, pawn: int | None) -> int:
        if pawn is None or pawn == actor:
            return actor
        if not 0 <= pawn < self.n:
            raise IllegalMove("No such pawn")
        if self.roles[actor] != Role.DISPATCHER:
            raise IllegalMove("Only the Dispatcher can move other players' pawns")
        return pawn

    def _city(self, city: str) -> str:
        if city not in CITIES:
            raise IllegalMove("No such city")
        return city

    def _hold(self, seat: int, card: str, what: str = "") -> None:
        if card not in self.hands[seat]:
            raise IllegalMove(what or f"You need the {name(card)} card")

    def _discard_card(self, seat: int, card: str) -> None:
        self.hands[seat].remove(card)
        self.player_discard.append(card)

    def _move(self, actor: int, pawn: int, to: str, by: str, events: list[Event], card: str | None = None) -> None:
        start = self.location[pawn]
        self.location[pawn] = to
        route = path(start, to) if by == "drive" else [start, to]
        events.append(
            {
                "kind": "move",
                "seat": actor,
                "pawn": pawn,
                "from": start,
                "to": to,
                "by": by,
                "card": card,
                "path": route,
            }
        )
        self._medic_sweep(pawn, events)

    def _turn_action(self, seat: int, action: Action, events: list[Event]) -> None:
        role = self.roles[seat]
        here = self.location[seat]
        match action:
            case Drive(to, pawn):
                p = self._pawn(seat, pawn)
                if self._city(to) not in ADJ[self.location[p]]:
                    raise IllegalMove(f"{name(to)} isn't connected to {name(self.location[p])}")
                self._move(seat, p, to, "drive", events)
            case DirectFlight(to, pawn):
                p = self._pawn(seat, pawn)
                if self._city(to) == self.location[p]:
                    raise IllegalMove("That pawn is already there")
                self._hold(seat, to)
                self._discard_card(seat, to)
                self._move(seat, p, to, "direct", events, card=to)
            case CharterFlight(to, pawn):
                p = self._pawn(seat, pawn)
                start = self.location[p]
                if self._city(to) == start:
                    raise IllegalMove("That pawn is already there")
                self._hold(seat, start)
                self._discard_card(seat, start)
                self._move(seat, p, to, "charter", events, card=start)
            case ShuttleFlight(to, pawn):
                p = self._pawn(seat, pawn)
                start = self.location[p]
                if start not in self.stations:
                    raise IllegalMove(f"There is no research station in {name(start)}")
                if self._city(to) not in self.stations or to == start:
                    raise IllegalMove(f"There is no research station in {name(to)}")
                self._move(seat, p, to, "shuttle", events)
            case Dispatch(pawn, to):
                if role != Role.DISPATCHER:
                    raise IllegalMove("Only the Dispatcher can do that")
                p = self._pawn(seat, pawn)
                if self._city(to) == self.location[p]:
                    raise IllegalMove("That pawn is already there")
                if not any(self.location[o] == to for o in range(self.n) if o != p):
                    raise IllegalMove(f"No other pawn is in {name(to)}")
                self._move(seat, p, to, "dispatch", events)
            case OpsFlight(to, card):
                if role != Role.OPERATIONS_EXPERT:
                    raise IllegalMove("Only the Operations Expert can do that")
                if here not in self.stations:
                    raise IllegalMove("You must be at a research station")
                if self.ops_flight_used:
                    raise IllegalMove("You already used this move this turn")
                if self._city(to) == here:
                    raise IllegalMove("You are already there")
                if card not in CITIES:
                    raise IllegalMove("Discard a city card")
                self._hold(seat, card)
                self._discard_card(seat, card)
                self.ops_flight_used = True
                self._move(seat, seat, to, "ops", events, card=card)
            case Build(remove):
                if here in self.stations:
                    raise IllegalMove(f"{name(here)} already has a research station")
                if role != Role.OPERATIONS_EXPERT:
                    self._hold(seat, here)
                self._check_station_removal(here, remove)
                if role != Role.OPERATIONS_EXPERT:
                    self._discard_card(seat, here)
                self._build(seat, here, remove, events, card=None if role == Role.OPERATIONS_EXPERT else here)
            case Treat(color):
                n = self.cubes[here][color]
                if n == 0:
                    raise IllegalMove(f"There are no {color} cubes in {name(here)}")
                removed = n if role == Role.MEDIC or self.cures[color] != "none" else 1
                self._remove(here, color, removed)
                self.stats["treated"][seat] += removed
                events.append(
                    {
                        "kind": "treat",
                        "seat": seat,
                        "city": here,
                        "color": color,
                        "removed": removed,
                        "left": n - removed,
                    }
                )
                self._check_eradicated(color, events)
            case Give(card, to):
                self._share(seat, seat, to, card, events)
            case Take(card, giver):
                self._share(seat, giver, seat, card, events)
            case Cure(cards):
                self._cure(seat, list(cards), events)
            case TakeEvent(card):
                if role != Role.CONTINGENCY_PLANNER:
                    raise IllegalMove("Only the Contingency Planner can do that")
                if self.stored[seat] is not None:
                    raise IllegalMove("You already store an event card")
                if card not in EVENTS or card not in self.player_discard:
                    raise IllegalMove("That event card isn't in the player discard pile")
                self.player_discard.remove(card)
                self.stored[seat] = card
                events.append({"kind": "take_event", "seat": seat, "card": card})
            case Pass():
                events.append({"kind": "pass", "seat": seat, "left": self.actions_left})
                self.actions_left = 0
                self.step = Step.DRAW
                return
            case _:
                raise IllegalMove(f"unknown action {action!r}")
        if self.result is None:
            self._spend()

    def _check_station_removal(self, city: str, remove: str | None) -> None:
        if len(self.stations) >= MAX_STATIONS:
            if remove is None:
                raise IllegalMove("All 6 research stations are built: pick one to move")
            if remove not in self.stations or remove == city:
                raise IllegalMove(f"There is no research station in {name(remove)}")
        elif remove is not None:
            raise IllegalMove("There are research stations left; none has to move")

    def _build(self, seat: int, city: str, remove: str | None, events: list[Event], card: str | None) -> None:
        if remove is not None:
            self.stations.remove(remove)
        self.stations.append(city)
        self.stats["built"][seat] += 1
        events.append({"kind": "build", "seat": seat, "city": city, "card": card, "moved_from": remove})

    def _share(self, actor: int, giver: int, receiver: int, card: str, events: list[Event]) -> None:
        other = receiver if giver == actor else giver
        if not 0 <= other < self.n or other == actor:
            raise IllegalMove("Pick another player")
        here = self.location[actor]
        if self.location[other] != here:
            raise IllegalMove("You must be in the same city to share knowledge")
        if card not in CITIES:
            raise IllegalMove("Only city cards can be shared")
        if card not in self.hands[giver]:
            raise IllegalMove("You don't hold that card" if giver == actor else "They don't hold that card")
        if card != here and self.roles[giver] != Role.RESEARCHER:
            raise IllegalMove(f"Only the {name(here)} card can be shared here")
        self.hands[giver].remove(card)
        self.hands[receiver].append(card)
        self.stats["shared"][actor] += 1
        events.append({"kind": "share", "seat": actor, "from": giver, "to": receiver, "card": card})

    def _cure(self, seat: int, cards: list[str], events: list[Event]) -> None:
        here = self.location[seat]
        if here not in self.stations:
            raise IllegalMove("You must be at a research station to discover a cure")
        need = self.need(seat)
        if len(set(cards)) != len(cards) or any(c not in CITIES for c in cards):
            raise IllegalMove("Pick different city cards")
        colors = {CITIES[c].color for c in cards}
        if len(colors) != 1:
            raise IllegalMove("All the cards must be the same color")
        color = colors.pop()
        if self.cures[color] != "none":
            raise IllegalMove(f"{color.capitalize()} is already cured")
        if len(cards) != need:
            raise IllegalMove(f"A cure needs {need} {color} cards")
        for c in cards:
            self._hold(seat, c, "You don't hold those cards")
        for c in cards:
            self._discard_card(seat, c)
        self.cures[color] = "cured"
        self.stats["cured"][seat] += 1
        events.append({"kind": "cure", "seat": seat, "color": color, "cards": cards})
        for s in range(self.n):
            self._medic_sweep(s, events)
        self._check_eradicated(color, events)
        if all(v != "none" for v in self.cures.values()):
            self.result = Result(True, "cured", self.turn)
            self.step = Step.GAME_OVER
            events.append({"kind": "game_over", **self.result.to_json()})

    def _discard(self, seat: int, card: str, events: list[Event]) -> None:
        if self.over_limit() != seat:
            raise IllegalMove("You don't have to discard now")
        self._hold(seat, card, "You don't hold that card")
        self._discard_card(seat, card)
        events.append({"kind": "discard", "seat": seat, "card": card})

    # ------------------------------------------------------------------ events
    def _event(self, seat: int, action: Action, events: list[Event]) -> None:
        card = {
            Airlift: EventCard.AIRLIFT,
            GovernmentGrant: EventCard.GOVERNMENT_GRANT,
            OneQuietNight: EventCard.ONE_QUIET_NIGHT,
            Forecast: EventCard.FORECAST,
            ResilientPopulation: EventCard.RESILIENT_POPULATION,
        }[type(action)].value
        from_hand = card in self.hands[seat]
        if not from_hand and self.stored[seat] != card:
            raise IllegalMove(f"You don't hold {EVENT_NAMES[EventCard(card)]}")
        over = self.over_limit()
        if over is not None and over != seat:
            raise IllegalMove("Wait: a player is over the hand limit")
        if self.step == Step.EPIDEMIC and card != EventCard.RESILIENT_POPULATION:
            raise IllegalMove("During an epidemic only Resilient Population can be played")
        info: Event = {"kind": "event", "seat": seat, "card": card}
        match action:
            case Airlift(pawn, to):
                if not 0 <= pawn < self.n:
                    raise IllegalMove("No such pawn")
                if self._city(to) == self.location[pawn]:
                    raise IllegalMove("That pawn is already there")
            case GovernmentGrant(city, remove):
                if self._city(city) in self.stations:
                    raise IllegalMove(f"{name(city)} already has a research station")
                self._check_station_removal(city, remove)
            case ResilientPopulation(city):
                if city not in self.infection_discard:
                    raise IllegalMove(f"{name(city)} isn't in the infection discard pile")
                info["city"] = city
            case Forecast():
                if not self.infection_deck:
                    raise IllegalMove("The infection deck is empty")
        if from_hand:
            self._discard_card(seat, card)
        else:
            self.stored[seat] = None
            self.removed.append(card)
        self.stats["events"][seat] += 1
        events.append(info)
        match action:
            case Airlift(pawn, to):
                self._move(seat, pawn, to, "airlift", events)
            case GovernmentGrant(city, remove):
                self._build(seat, city, remove, events, card=None)
            case OneQuietNight():
                self.quiet_night = True
            case ResilientPopulation(city):
                self.infection_discard.remove(city)
                self.removed.append(city)
            case Forecast():
                top = self.infection_deck[-FORECAST_CARDS:][::-1]
                self.forecast = (seat, top)
                events.append({"kind": "forecast", "seat": seat, "cards": list(top)})

    def _forecast_order(self, seat: int, action: ForecastOrder, events: list[Event]) -> None:
        if self.forecast is None or self.forecast[0] != seat:
            raise IllegalMove("You are not arranging a Forecast")
        cards = self.forecast[1]
        order = list(action.order)
        if sorted(order) != sorted(cards):
            raise IllegalMove("Put back exactly the cards you looked at")
        k = len(cards)
        self.infection_deck[-k:] = order[::-1]
        self.forecast = None
        events.append({"kind": "forecast_done", "seat": seat, "order": order})

    # ------------------------------------------------------------------ undo
    def _snapshot(self) -> Game:
        return self.clone()

    def undo(self, seat: int) -> list[Event]:
        """Take back the current player's last action of this turn (actions never reveal hidden cards)."""
        if not self.can_undo(seat):
            raise IllegalMove("Nothing to undo")
        stack = self._undo
        snap = stack.pop()
        rng = self.rng
        self.__dict__.update(snap.__dict__)
        self.rng = rng
        self._undo = stack
        return [{"kind": "undo", "seat": seat}]

    def clone(self) -> Game:
        g = object.__new__(Game)
        g.__dict__.update(self.__dict__)
        g.location = list(self.location)
        g.hands = [list(h) for h in self.hands]
        g.stored = list(self.stored)
        g.cubes = {c: dict(v) for c, v in self.cubes.items()}
        g.supply = dict(self.supply)
        g.stations = list(self.stations)
        g.cures = dict(self.cures)
        g.player_deck = list(self.player_deck)
        g.player_discard = list(self.player_discard)
        g.removed = list(self.removed)
        g.infection_deck = list(self.infection_deck)
        g.infection_discard = list(self.infection_discard)
        g.known_top = list(self.known_top)
        g.drawn = list(self.drawn)
        g.forecast = (self.forecast[0], list(self.forecast[1])) if self.forecast else None
        g.stats = {k: list(v) for k, v in self.stats.items()}
        g._undo = []
        g.rng = random.Random()
        g.rng.setstate(self.rng.getstate())
        return g

    # ------------------------------------------------------------------ views and legal moves
    def view(self, seat: int, open_hands: bool = True) -> View:
        return View(
            seat=seat,
            n=self.n,
            step=self.step,
            current=self.current,
            waiting_for=self.waiting_for(),
            actions_left=self.actions_left,
            roles=list(self.roles),
            locations=list(self.location),
            hands=[list(h) if open_hands or s == seat else None for s, h in enumerate(self.hands)],
            hand_counts=[len(h) for h in self.hands],
            stored=list(self.stored),
            cubes={c: dict(v) for c, v in self.cubes.items()},
            supply=dict(self.supply),
            stations=list(self.stations),
            cures=dict(self.cures),
            outbreaks=self.outbreaks,
            epidemics_drawn=self.epidemics_drawn,
            epidemics=self.rules.epidemics,
            player_deck_size=len(self.player_deck),
            pile_sizes=list(self.pile_sizes),
            player_discard=list(self.player_discard),
            infection_deck_size=len(self.infection_deck),
            infection_discard=list(self.infection_discard),
            known_top=[c for c in self.known_top if c in self.infection_deck],
            quiet_night=self.quiet_night,
            ops_flight_used=self.ops_flight_used,
            forecast=list(self.forecast[1]) if self.forecast and self.forecast[0] == seat else None,
            turn=self.turn,
            open_hands=open_hands,
            removed=list(self.removed),
        )

    @classmethod
    def from_view(cls, view: View) -> Game:
        g = object.__new__(cls)
        g.n = view.n
        g.rules = RulesConfig(epidemics=view.epidemics, roles=tuple(view.roles))
        g.rng = random.Random(0)
        g.roles = list(view.roles)
        g.location = list(view.locations)
        g.hands = [list(h) if h is not None else [HIDDEN] * view.hand_counts[s] for s, h in enumerate(view.hands)]
        g.stored = list(view.stored)
        g.cubes = {c: dict(v) for c, v in view.cubes.items()}
        g.supply = dict(view.supply)
        g.stations = list(view.stations)
        g.cures = dict(view.cures)
        g.outbreaks = view.outbreaks
        g.epidemics_drawn = view.epidemics_drawn
        g.player_deck = [HIDDEN] * view.player_deck_size
        g.player_discard = list(view.player_discard)
        g.removed = list(view.removed)
        g.infection_deck = [HIDDEN] * view.infection_deck_size
        g.infection_discard = list(view.infection_discard)
        g.known_top = list(view.known_top)
        g.pile_sizes = list(view.pile_sizes)
        g.turn = view.turn
        g.current = view.current
        g.actions_left = view.actions_left
        g.step = view.step
        g.drawn = []
        g.pending_epidemics = 0
        g.quiet_night = view.quiet_night
        g.ops_flight_used = view.ops_flight_used
        g.forecast = (view.seat, list(view.forecast)) if view.forecast else None
        g.result = None
        g.stats = {k: [0] * view.n for k in ("treated", "built", "cured", "shared", "events")}
        g.track_undo = False
        g._undo = []
        g._setup = False
        g.setup_events = []
        return g

    def turn_actions(self, seat: int) -> list[Action]:
        """Every legal action that costs an action (plus Pass) for the current player in the ACTIONS step."""
        if self.result is not None or seat != self.current or self.step != Step.ACTIONS:
            return []
        if self.forecast is not None or self.over_limit() is not None:
            return []
        out: list[Action] = []
        role = self.roles[seat]
        hand = [c for c in self.hands[seat] if c in CITIES]
        pawns = range(self.n) if role == Role.DISPATCHER else [seat]
        for p in pawns:
            at = self.location[p]
            arg = None if p == seat else p
            out += [Drive(c, arg) for c in ADJ[at]]
            out += [DirectFlight(c, arg) for c in dict.fromkeys(hand) if c != at]
            if at in hand:
                out += [CharterFlight(c, arg) for c in CITIES if c != at]
            if at in self.stations:
                out += [ShuttleFlight(c, arg) for c in self.stations if c != at]
            if role == Role.DISPATCHER:
                spots = dict.fromkeys(self.location[o] for o in range(self.n) if o != p)
                out += [Dispatch(p, c) for c in spots if c != at]
        here = self.location[seat]
        if role == Role.OPERATIONS_EXPERT and here in self.stations and not self.ops_flight_used:
            out += [OpsFlight(c, card) for card in dict.fromkeys(hand) for c in CITIES if c != here]
        if here not in self.stations and (role == Role.OPERATIONS_EXPERT or here in hand):
            if len(self.stations) >= MAX_STATIONS:
                out += [Build(s) for s in self.stations]
            else:
                out.append(Build())
        out += [Treat(c) for c in COLORS if self.cubes[here][c]]
        for o in self.seats_at(here):
            if o == seat:
                continue
            mine = hand if role == Role.RESEARCHER else [c for c in hand if c == here]
            out += [Give(c, o) for c in dict.fromkeys(mine)]
            theirs = [c for c in self.hands[o] if c in CITIES]
            if self.roles[o] != Role.RESEARCHER:
                theirs = [c for c in theirs if c == here]
            out += [Take(c, o) for c in dict.fromkeys(theirs)]
        if here in self.stations:
            need = self.need(seat)
            for color in COLORS:
                if self.cures[color] != "none":
                    continue
                cards = [c for c in hand if CITIES[c].color == color]
                if len(cards) >= need:
                    out += [Cure(combo) for combo in combinations(cards, need)]
        if role == Role.CONTINGENCY_PLANNER and self.stored[seat] is None:
            out += [TakeEvent(c) for c in dict.fromkeys(self.player_discard) if c in EVENTS]
        out.append(Pass())
        return out

    def event_actions(self, seat: int) -> list[Action]:
        """Every legal event play for `seat` right now (Forecast orders aside)."""
        if self.result is not None or self.forecast is not None:
            return []
        over = self.over_limit()
        if over is not None and over != seat:
            return []
        held = set(self.hands[seat]) | ({self.stored[seat]} if self.stored[seat] else set())
        out: list[Action] = []
        epidemic = self.step == Step.EPIDEMIC
        if EventCard.RESILIENT_POPULATION in held:
            out += [ResilientPopulation(c) for c in self.infection_discard]
        if epidemic:
            return out
        if EventCard.AIRLIFT in held:
            out += [Airlift(p, c) for p in range(self.n) for c in CITIES if c != self.location[p]]
        if EventCard.GOVERNMENT_GRANT in held:
            full = len(self.stations) >= MAX_STATIONS
            for c in CITIES:
                if c not in self.stations:
                    out += [GovernmentGrant(c, s) for s in self.stations] if full else [GovernmentGrant(c)]
        if EventCard.ONE_QUIET_NIGHT in held and not self.quiet_night:
            out.append(OneQuietNight())
        if EventCard.FORECAST in held and self.infection_deck:
            out.append(Forecast())
        return out

    def legal_actions(self, seat: int) -> list[Action]:
        """What `seat` may do right now (a Forecast offers two sample orders, not all 720)."""
        if self.result is not None:
            return []
        if self.forecast is not None:
            if self.forecast[0] != seat:
                return []
            cards = self.forecast[1]
            return [ForecastOrder(tuple(cards)), ForecastOrder(tuple(reversed(cards)))]
        out = self.event_actions(seat)
        over = self.over_limit()
        if over is not None:
            if over == seat:
                out += [Discard(c) for c in dict.fromkeys(self.hands[seat])]
            return out
        if seat != self.current:
            return out
        if self.step == Step.ACTIONS:
            out += self.turn_actions(seat)
        elif self.step == Step.DRAW:
            out.append(DrawCards())
        elif self.step in (Step.EPIDEMIC, Step.INFECT):
            out.append(Continue())
        return out


__all__ = ["HIDDEN", "Event", "Game", "IllegalMove", "Result", "RulesConfig", "Step", "View", "name", "need_for_cure"]
