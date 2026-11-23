"""Cards, the deck and the ten phases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Color(StrEnum):
    RED = "red"
    BLUE = "blue"
    GREEN = "green"
    YELLOW = "yellow"


class Kind(StrEnum):
    NUMBER = "number"
    WILD = "wild"
    SKIP = "skip"


MIN_VALUE, MAX_VALUE = 1, 12
COPIES = 2  # each number appears twice in each colour
WILDS = 8
SKIPS = 4
DECK_SIZE = (MAX_VALUE - MIN_VALUE + 1) * len(Color) * COPIES + WILDS + SKIPS  # 108


@dataclass(frozen=True, slots=True)
class Card:
    id: int
    kind: Kind
    value: int = 0  # 1..12 for number cards, 0 otherwise
    color: Color | None = None

    @property
    def wild(self) -> bool:
        return self.kind == Kind.WILD

    @property
    def skip(self) -> bool:
        return self.kind == Kind.SKIP

    @property
    def natural(self) -> bool:
        return self.kind == Kind.NUMBER

    @property
    def points(self) -> int:
        """Penalty for holding this card when someone goes out."""
        if self.kind == Kind.WILD:
            return 25
        if self.kind == Kind.SKIP:
            return 15
        return 5 if self.value <= 9 else 10

    def label(self) -> str:
        if self.kind == Kind.WILD:
            return "Wild"
        if self.kind == Kind.SKIP:
            return "Skip"
        return f"{self.color} {self.value}"

    def to_json(self) -> dict[str, Any]:
        k = {Kind.NUMBER: "n", Kind.WILD: "w", Kind.SKIP: "s"}[self.kind]
        return {"id": self.id, "k": k, "v": self.value, "c": self.color.value if self.color else None}


def make_deck() -> list[Card]:
    cards: list[Card] = []
    for color in Color:
        for value in range(MIN_VALUE, MAX_VALUE + 1):
            for _ in range(COPIES):
                cards.append(Card(len(cards), Kind.NUMBER, value, color))
    for _ in range(WILDS):
        cards.append(Card(len(cards), Kind.WILD))
    for _ in range(SKIPS):
        cards.append(Card(len(cards), Kind.SKIP))
    assert len(cards) == DECK_SIZE
    return cards


class GroupKind(StrEnum):
    SET = "set"  # cards of the same number
    RUN = "run"  # cards in numerical order
    COLOR = "color"  # cards of one colour


@dataclass(frozen=True, slots=True)
class Req:
    kind: GroupKind
    size: int

    def label(self) -> str:
        if self.kind == GroupKind.COLOR:
            return f"{self.size} cards of one color"
        return f"{self.kind.value} of {self.size}"


S, R, C = GroupKind.SET, GroupKind.RUN, GroupKind.COLOR

PHASES: tuple[tuple[Req, ...], ...] = (
    (Req(S, 3), Req(S, 3)),
    (Req(S, 3), Req(R, 4)),
    (Req(S, 4), Req(R, 4)),
    (Req(R, 7),),
    (Req(R, 8),),
    (Req(R, 9),),
    (Req(S, 4), Req(S, 4)),
    (Req(C, 7),),
    (Req(S, 5), Req(S, 2)),
    (Req(S, 5), Req(S, 3)),
)


def phase_label(phase: int) -> str:
    """'2 sets of 3', '1 set of 3 + 1 run of 4', ... for phase 1..10."""
    reqs = PHASES[phase - 1]
    if len(reqs) == 2 and reqs[0] == reqs[1]:
        return f"2 {reqs[0].kind.value}s of {reqs[0].size}"
    return " + ".join(r.label() if r.kind == GroupKind.COLOR else f"1 {r.label()}" for r in reqs)


def phases_public() -> list[dict[str, Any]]:
    return [
        {
            "phase": i + 1,
            "label": phase_label(i + 1),
            "reqs": [{"kind": r.kind.value, "size": r.size} for r in reqs],
        }
        for i, reqs in enumerate(PHASES)
    ]
