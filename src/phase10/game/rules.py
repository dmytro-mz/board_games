"""Pure helpers: what makes a set, a run or a colour group, and what may be added to one.

Every group needs at least one natural (number) card; wilds stand in for anything else. Skips never go in a group.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from phase10.game.model import MAX_VALUE, MIN_VALUE, Card, Color, GroupKind


class InvalidGroup(ValueError):
    """The cards don't form the group; the message says why, in plain words."""


def _naturals(cards: Sequence[Card], what: str) -> list[Card]:
    if any(c.skip for c in cards):
        raise InvalidGroup(f"Skip cards can't be part of a {what}")
    naturals = [c for c in cards if c.natural]
    if not naturals:
        raise InvalidGroup(f"A {what} needs at least one number card, not only wilds")
    return naturals


def set_value(cards: Sequence[Card], size: int) -> int:
    """The number of a valid set of at least `size` cards."""
    if len(cards) < size:
        raise InvalidGroup(f"A set needs at least {size} cards, you picked {len(cards)}")
    naturals = _naturals(cards, "set")
    values = sorted({c.value for c in naturals})
    if len(values) > 1:
        raise InvalidGroup(f"A set is cards of the same number, but these have {', '.join(map(str, values))}")
    return values[0]


def run_lows(cards: Sequence[Card], size: int) -> list[int]:
    """Every lowest number the cards can start a run from (more than one only when wilds sit at an end)."""
    if len(cards) < size:
        raise InvalidGroup(f"A run needs at least {size} cards, you picked {len(cards)}")
    n = len(cards)
    if n > MAX_VALUE - MIN_VALUE + 1:
        raise InvalidGroup(f"A run can't be longer than {MAX_VALUE} cards")
    naturals = _naturals(cards, "run")
    values = [c.value for c in naturals]
    dupes = sorted({v for v in values if values.count(v) > 1})
    if dupes:
        raise InvalidGroup(f"A run can't have the same number twice ({', '.join(map(str, dupes))})")
    lo, hi = min(values), max(values)
    if hi - lo + 1 > n:
        gaps = hi - lo + 1 - len(values)
        wilds = n - len(values)
        raise InvalidGroup(f"From {lo} to {hi} there are {gaps} gaps, but only {wilds} wild(s) to fill them")
    first = max(MIN_VALUE, hi - n + 1)
    last = min(lo, MAX_VALUE - n + 1)
    return list(range(first, last + 1))


def color_of(cards: Sequence[Card], size: int) -> Color:
    if len(cards) < size:
        raise InvalidGroup(f"You need at least {size} cards of one color, you picked {len(cards)}")
    naturals = _naturals(cards, "color group")
    colors = {c.color for c in naturals}
    if len(colors) > 1:
        raise InvalidGroup("All cards must have the same color (wilds are fine)")
    color = colors.pop()
    assert color is not None
    return color


@dataclass
class Group:
    """A set, run or colour group on the table. Run cards are kept in order, low to high."""

    id: int
    owner: int
    kind: GroupKind
    cards: list[Card] = field(default_factory=list)
    value: int = 0  # set
    low: int = 0  # run
    color: Color | None = None  # colour group

    @property
    def high(self) -> int:
        return self.low + len(self.cards) - 1

    @staticmethod
    def build(gid: int, owner: int, kind: GroupKind, cards: Sequence[Card], size: int, low: int | None = None) -> Group:
        """Validate `cards` as a group of `kind` with at least `size` cards (raises InvalidGroup)."""
        if kind == GroupKind.SET:
            return Group(gid, owner, kind, list(cards), value=set_value(cards, size))
        if kind == GroupKind.COLOR:
            return Group(gid, owner, kind, list(cards), color=color_of(cards, size))
        lows = run_lows(cards, size)
        if low is None:
            low = lows[0]
        elif low not in lows:
            span = f"{lows[0]}–{lows[0] + len(cards) - 1}"
            if len(lows) > 1:
                span = " or ".join(f"{s}–{s + len(cards) - 1}" for s in lows)
            raise InvalidGroup(f"These cards can only make the run {span}")
        naturals = {c.value: c for c in cards if c.natural}
        wilds = [c for c in cards if c.wild]
        ordered = [naturals.get(v) or wilds.pop() for v in range(low, low + len(cards))]
        return Group(gid, owner, kind, ordered, low=low)

    def ends_for(self, card: Card) -> list[str]:
        """Where `card` may be added: [] if nowhere; for runs 'low' and/or 'high', otherwise ['any']."""
        if card.skip:
            return []
        if self.kind == GroupKind.SET:
            return ["any"] if card.wild or card.value == self.value else []
        if self.kind == GroupKind.COLOR:
            return ["any"] if card.wild or card.color == self.color else []
        ends = []
        if self.low > MIN_VALUE and (card.wild or card.value == self.low - 1):
            ends.append("low")
        if self.high < MAX_VALUE and (card.wild or card.value == self.high + 1):
            ends.append("high")
        return ends

    def add(self, card: Card, end: str | None = None) -> str:
        """Add `card` (raises InvalidGroup); returns the end it went to."""
        ends = self.ends_for(card)
        if not ends:
            raise InvalidGroup(self._why_not(card))
        if end is None or end == "any":
            end = "high" if "high" in ends else ends[0]
        if end not in ends:
            raise InvalidGroup(f"That card doesn't fit at the {end} end of this run")
        if end == "low":
            self.cards.insert(0, card)
            self.low -= 1
        else:
            self.cards.append(card)
        return end

    def _why_not(self, card: Card) -> str:
        if card.skip:
            return "Skip cards can't be added to groups"
        if self.kind == GroupKind.SET:
            return f"This is a set of {self.value}s"
        if self.kind == GroupKind.COLOR:
            return f"This group is all {self.color}"
        if self.low == MIN_VALUE and self.high == MAX_VALUE:
            return "This run is already complete from 1 to 12"
        fits = [str(v) for v in (self.low - 1, self.high + 1) if MIN_VALUE <= v <= MAX_VALUE]
        return f"This run goes {self.low}–{self.high}; only {' or '.join(fits)} (or a wild) fits"

    def as_values(self) -> list[int | str | None]:
        """What each card counts as: its run position, the set number, or the colour."""
        if self.kind == GroupKind.RUN:
            return list(range(self.low, self.high + 1))
        if self.kind == GroupKind.SET:
            return [self.value] * len(self.cards)
        return [self.color.value if self.color else None] * len(self.cards)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "owner": self.owner,
            "kind": self.kind.value,
            "cards": [c.to_json() for c in self.cards],
            "as": self.as_values(),
            "value": self.value,
            "low": self.low,
            "high": self.high if self.kind == GroupKind.RUN else 0,
            "color": self.color.value if self.color else None,
        }
