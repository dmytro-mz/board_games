"""Player actions and their JSON form (the web protocol uses `to_json` / `from_json`)."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from avel.game.model import Hex


@dataclass(frozen=True)
class Move:
    """Movement action: to an adjacent tile, or between two shortcut tiles. Face-down tiles are revealed."""

    to: Hex


@dataclass(frozen=True)
class Battle:
    """Battle action against a monster on the hero's tile."""

    monster: str


@dataclass(frozen=True)
class Drink:
    """Drink an elixir: a battle elixir while preparing a battle, the healing elixir between actions."""

    item: str


@dataclass(frozen=True)
class Fight:
    """Roll the dice for the next clash."""


@dataclass(frozen=True)
class Reroll:
    """One-time equipment effect: reroll some of the dice on the table (indices into the clash dice)."""

    item: str
    dice: tuple[int, ...]


@dataclass(frozen=True)
class Bonus:
    """One-time equipment effect: add a sword or a shield to this clash."""

    item: str


@dataclass(frozen=True)
class Resolve:
    """Settle the clash; `spell_swords` of the rolled spells count as swords, the rest as shields."""

    spell_swords: int = 0


@dataclass(frozen=True)
class Retreat:
    """Leave the battle (before the first clash, or between clashes)."""


@dataclass(frozen=True)
class Rest:
    pass


@dataclass(frozen=True)
class Market:
    """Marketplace: up to 2 transactions, each a sale (2 coins) or a purchase (3 coins); sales happen first."""

    sell: tuple[str, ...] = ()
    buy: int = 0


@dataclass(frozen=True)
class Seal:
    at: Hex
    lair: int


@dataclass(frozen=True)
class Wall:
    pass


@dataclass(frozen=True)
class Trap:
    level: int
    at: Hex


@dataclass(frozen=True)
class Work:
    pass


@dataclass(frozen=True)
class Upgrade:
    """Alchemist workshop: pay 3 coins to upgrade an item."""

    item: str


@dataclass(frozen=True)
class Wish:
    pass


@dataclass(frozen=True)
class ChooseUpgrade:
    """A free upgrade (monster reward or wishing lake): which item to flip."""

    item: str


@dataclass(frozen=True)
class Equip:
    item: str


@dataclass(frozen=True)
class Unequip:
    item: str


@dataclass(frozen=True)
class Discard:
    """Return an item to the bag (item) or coins to the supply."""

    item: str | None = None
    coins: int = 0


@dataclass(frozen=True)
class Give:
    """Hand an item or coins to a hero on the same tile (no monster there)."""

    to: int
    item: str | None = None
    coins: int = 0


@dataclass(frozen=True)
class Take:
    """Take an item or coins from a hero on the same tile (no monster there)."""

    source: int
    item: str | None = None
    coins: int = 0


@dataclass(frozen=True)
class Lose:
    """Stunned: the equipment token that goes back to the bag."""

    item: str


@dataclass(frozen=True)
class Steer:
    """Several shortest paths: where the marching monster goes."""

    to: Hex


@dataclass(frozen=True)
class Done:
    """Finished repacking: everything fits."""


@dataclass(frozen=True)
class EndTurn:
    pass


Action = (
    Move
    | Battle
    | Drink
    | Fight
    | Reroll
    | Bonus
    | Resolve
    | Retreat
    | Rest
    | Market
    | Seal
    | Wall
    | Trap
    | Work
    | Upgrade
    | Wish
    | ChooseUpgrade
    | Equip
    | Unequip
    | Discard
    | Give
    | Take
    | Lose
    | Steer
    | Done
    | EndTurn
)

NAMES: dict[type, str] = {
    Move: "move",
    Battle: "battle",
    Drink: "drink",
    Fight: "fight",
    Reroll: "reroll",
    Bonus: "bonus",
    Resolve: "resolve",
    Retreat: "retreat",
    Rest: "rest",
    Market: "market",
    Seal: "seal",
    Wall: "wall",
    Trap: "trap",
    Work: "work",
    Upgrade: "upgrade",
    Wish: "wish",
    ChooseUpgrade: "choose_upgrade",
    Equip: "equip",
    Unequip: "unequip",
    Discard: "discard",
    Give: "give",
    Take: "take",
    Lose: "lose",
    Steer: "steer",
    Done: "done",
    EndTurn: "end_turn",
}
TYPES = {v: k for k, v in NAMES.items()}


class BadAction(ValueError):
    pass


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadAction(f"{name} must be an integer")
    return value


def _str(value: object, name: str) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 32:
        raise BadAction(f"{name} must be a string")
    return value


def _hex(value: object, name: str) -> Hex:
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise BadAction(f"{name} must be [col, row]")
    return (_int(value[0], name), _int(value[1], name))


def from_json(data: object) -> Action:
    if not isinstance(data, dict):
        raise BadAction("action must be an object")
    cls = TYPES.get(data.get("type"))  # type: ignore[arg-type]
    if cls is None:
        raise BadAction("unknown action")
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if f.type == "Hex":
            kwargs[f.name] = _hex(value, f.name)
        elif f.name in ("sell", "dice"):
            if not isinstance(value, list | tuple) or len(value) > 6:
                raise BadAction(f"{f.name} must be a list")
            items = [_str(v, f.name) if f.name == "sell" else _int(v, f.name) for v in value]
            kwargs[f.name] = tuple(sorted(items))  # type: ignore[type-var]
        elif f.name in ("item", "monster"):
            kwargs[f.name] = None if value is None and f.name == "item" else _str(value, f.name)
        else:
            kwargs[f.name] = _int(value, f.name)
    try:
        return cls(**kwargs)
    except TypeError:
        raise BadAction("missing fields") from None


def to_json(action: Action) -> dict[str, Any]:
    out: dict[str, Any] = {"type": NAMES[type(action)]}
    for f in fields(action):
        value = getattr(action, f.name)
        out[f.name] = list(value) if isinstance(value, tuple) else value
    return out
