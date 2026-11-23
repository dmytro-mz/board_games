"""Player actions and their JSON form (the web protocol uses `to_json` / `from_json`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from phase10.game.model import GroupKind


@dataclass(frozen=True)
class DrawDeck:
    """Take the top card of the face-down pile."""


@dataclass(frozen=True)
class DrawDiscard:
    """Take the top card of the discard pile (never a Skip)."""


@dataclass(frozen=True)
class GroupSpec:
    kind: GroupKind
    cards: tuple[int, ...]
    low: int | None = None  # runs only: the lowest number, when wilds make it ambiguous


@dataclass(frozen=True)
class LayDown:
    """Lay down the whole phase at once: one group per requirement, in any order."""

    groups: tuple[GroupSpec, ...]


@dataclass(frozen=True)
class Hit:
    """Add one card to any group on the table (only after laying down your own phase)."""

    group: int
    card: int
    end: str | None = None  # runs: "low" or "high"


@dataclass(frozen=True)
class Discard:
    """End the turn. A Skip names the player who loses their next turn."""

    card: int
    target: int | None = None


Action = DrawDeck | DrawDiscard | LayDown | Hit | Discard


class BadAction(ValueError):
    pass


def to_json(action: Action) -> dict[str, Any]:
    match action:
        case DrawDeck():
            return {"type": "draw_deck"}
        case DrawDiscard():
            return {"type": "draw_discard"}
        case LayDown(groups):
            return {
                "type": "lay_down",
                "groups": [{"kind": g.kind.value, "cards": list(g.cards), "low": g.low} for g in groups],
            }
        case Hit(group, card, end):
            return {"type": "hit", "group": group, "card": card, "end": end}
        case Discard(card, target):
            return {"type": "discard", "card": card, "target": target}
    raise BadAction(f"unknown action {action!r}")


def _int(data: dict[str, Any], key: str, optional: bool = False) -> int | None:
    value = data.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadAction(f"{key} must be a number")
    return value


def from_json(data: object) -> Action:
    if not isinstance(data, dict):
        raise BadAction("action must be an object")
    match data.get("type"):
        case "draw_deck":
            return DrawDeck()
        case "draw_discard":
            return DrawDiscard()
        case "lay_down":
            raw = data.get("groups")
            if not isinstance(raw, list) or not 1 <= len(raw) <= 4:
                raise BadAction("groups must be a list")
            groups = []
            for g in raw:
                if not isinstance(g, dict):
                    raise BadAction("each group must be an object")
                try:
                    kind = GroupKind(g.get("kind"))
                except ValueError:
                    raise BadAction("unknown group kind") from None
                cards = g.get("cards")
                if not isinstance(cards, list) or not all(
                    isinstance(c, int) and not isinstance(c, bool) for c in cards
                ):
                    raise BadAction("cards must be a list of card ids")
                groups.append(GroupSpec(kind, tuple(cards), _int(g, "low", optional=True)))
            return LayDown(tuple(groups))
        case "hit":
            end = data.get("end")
            if end not in (None, "low", "high", "any"):
                raise BadAction("end must be low or high")
            return Hit(_int(data, "group"), _int(data, "card"), end)  # type: ignore[arg-type]
        case "discard":
            return Discard(_int(data, "card"), _int(data, "target", optional=True))  # type: ignore[arg-type]
    raise BadAction(f"unknown action type {data.get('type')!r}")
