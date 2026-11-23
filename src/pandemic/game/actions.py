"""Player actions and their JSON form (the web protocol uses `to_json` / `from_json`).

`pawn` on the movement actions is the seat whose pawn moves; only the Dispatcher may name another seat.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from pandemic.game.model import Color


@dataclass(frozen=True)
class Drive:
    """Drive / Ferry to a connected city."""

    to: str
    pawn: int | None = None


@dataclass(frozen=True)
class DirectFlight:
    """Discard the card of the destination and fly there."""

    to: str
    pawn: int | None = None


@dataclass(frozen=True)
class CharterFlight:
    """Discard the card of the city the pawn is in and fly anywhere."""

    to: str
    pawn: int | None = None


@dataclass(frozen=True)
class ShuttleFlight:
    """Fly from a research station to another research station."""

    to: str
    pawn: int | None = None


@dataclass(frozen=True)
class Dispatch:
    """Dispatcher: move any pawn to a city that has another pawn."""

    pawn: int
    to: str


@dataclass(frozen=True)
class OpsFlight:
    """Operations Expert, once per turn: from a research station to any city, discarding any city card."""

    to: str
    card: str


@dataclass(frozen=True)
class Build:
    """Build a research station here. With all 6 built, `remove` names the station that moves."""

    remove: str | None = None


@dataclass(frozen=True)
class Treat:
    color: Color


@dataclass(frozen=True)
class Give:
    """Share Knowledge: give a card to a player in your city."""

    card: str
    to: int


@dataclass(frozen=True)
class Take:
    """Share Knowledge: take a card from a player in your city."""

    card: str
    giver: int


@dataclass(frozen=True)
class Cure:
    """Discover a Cure at a research station with 5 cards of one color (the Scientist needs 4)."""

    cards: tuple[str, ...]


@dataclass(frozen=True)
class TakeEvent:
    """Contingency Planner: store an event card from the player discard pile."""

    card: str


@dataclass(frozen=True)
class Pass:
    """End the action phase early."""


@dataclass(frozen=True)
class DrawCards:
    """Draw the two player cards at the end of the actions."""


@dataclass(frozen=True)
class Continue:
    """Finish an epidemic (Intensify) or infect the cities at the end of a turn."""


@dataclass(frozen=True)
class Discard:
    """Hand limit: discard a card."""

    card: str


@dataclass(frozen=True)
class Airlift:
    pawn: int
    to: str


@dataclass(frozen=True)
class GovernmentGrant:
    city: str
    remove: str | None = None


@dataclass(frozen=True)
class OneQuietNight:
    pass


@dataclass(frozen=True)
class Forecast:
    """Reveal the top 6 infection cards; answer with `ForecastOrder`."""


@dataclass(frozen=True)
class ForecastOrder:
    order: tuple[str, ...]  # top card first


@dataclass(frozen=True)
class ResilientPopulation:
    city: str


Action = (
    Drive
    | DirectFlight
    | CharterFlight
    | ShuttleFlight
    | Dispatch
    | OpsFlight
    | Build
    | Treat
    | Give
    | Take
    | Cure
    | TakeEvent
    | Pass
    | DrawCards
    | Continue
    | Discard
    | Airlift
    | GovernmentGrant
    | OneQuietNight
    | Forecast
    | ForecastOrder
    | ResilientPopulation
)

MOVES = (Drive, DirectFlight, CharterFlight, ShuttleFlight, Dispatch, OpsFlight)
TURN_ACTIONS = (*MOVES, Build, Treat, Give, Take, Cure, TakeEvent)  # each costs one action
EVENT_ACTIONS = (Airlift, GovernmentGrant, OneQuietNight, Forecast, ResilientPopulation)

TYPES: dict[str, type] = {
    "drive": Drive,
    "direct": DirectFlight,
    "charter": CharterFlight,
    "shuttle": ShuttleFlight,
    "dispatch": Dispatch,
    "ops_flight": OpsFlight,
    "build": Build,
    "treat": Treat,
    "give": Give,
    "take": Take,
    "cure": Cure,
    "take_event": TakeEvent,
    "pass": Pass,
    "draw": DrawCards,
    "continue": Continue,
    "discard": Discard,
    "airlift": Airlift,
    "grant": GovernmentGrant,
    "quiet": OneQuietNight,
    "forecast": Forecast,
    "forecast_order": ForecastOrder,
    "resilient": ResilientPopulation,
}
NAMES: dict[type, str] = {cls: name for name, cls in TYPES.items()}


class BadAction(ValueError):
    pass


def to_json(action: Action) -> dict[str, Any]:
    out: dict[str, Any] = {"type": NAMES[type(action)]}
    for f in fields(action):  # type: ignore[arg-type]
        value = getattr(action, f.name)
        out[f.name] = list(value) if isinstance(value, tuple) else value
    return out


def _value(cls: type, name: str, value: object) -> object:
    hint = str(cls.__annotations__[name])
    optional = "None" in hint
    if value is None:
        if optional:
            return None
        raise BadAction(f"{name} is missing")
    if hint.startswith("int"):
        if not isinstance(value, int) or isinstance(value, bool):
            raise BadAction(f"{name} must be a number")
        return value
    if hint == "Color":
        try:
            return Color(value)
        except ValueError:
            raise BadAction("unknown color") from None
    if hint.startswith("tuple"):
        if not isinstance(value, list) or len(value) > 8 or not all(isinstance(v, str) for v in value):
            raise BadAction(f"{name} must be a list of cards")
        return tuple(value)
    if not isinstance(value, str) or len(value) > 16:
        raise BadAction(f"{name} must be a text")
    return value


def from_json(data: object) -> Action:
    if not isinstance(data, dict):
        raise BadAction("action must be an object")
    cls = TYPES.get(data.get("type"))  # type: ignore[arg-type]
    if cls is None:
        raise BadAction(f"unknown action type {data.get('type')!r}")
    return cls(**{f.name: _value(cls, f.name, data.get(f.name)) for f in fields(cls)})


__all__ = [
    "EVENT_ACTIONS",
    "MOVES",
    "TURN_ACTIONS",
    "Action",
    "Airlift",
    "BadAction",
    "Build",
    "CharterFlight",
    "Continue",
    "Cure",
    "DirectFlight",
    "Discard",
    "Dispatch",
    "DrawCards",
    "Drive",
    "Forecast",
    "ForecastOrder",
    "Give",
    "GovernmentGrant",
    "OneQuietNight",
    "OpsFlight",
    "Pass",
    "ResilientPopulation",
    "ShuttleFlight",
    "Take",
    "TakeEvent",
    "Treat",
    "from_json",
    "to_json",
]
