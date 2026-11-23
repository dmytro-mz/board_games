"""The game state machine: `Game.step(seat, action) -> events`, `Game.view(seat)` for bots.

A game is a series of hands. In each hand every player works on their own phase: on a turn they draw a card,
may lay down their phase (all groups at once), may then add cards to any group on the table ("hit"), and end by
discarding. The hand ends when someone gets rid of their last card. Players who laid down advance a phase; all
cards left in hands score penalty points. The game ends after a hand in which someone completes the last phase:
of those, the lowest score wins.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import permutations
from typing import Any

from phase10.game.actions import Action, Discard, DrawDeck, DrawDiscard, Hit, LayDown
from phase10.game.model import PHASES, Card, Req, make_deck
from phase10.game.rules import Group, InvalidGroup

Event = dict[str, Any]


class Step(StrEnum):
    DRAW = "draw"
    PLAY = "play"
    HAND_OVER = "hand_over"
    GAME_OVER = "game_over"


class IllegalMove(ValueError):
    """The action is not allowed now; the game state is unchanged. The message is for the player."""


@dataclass(frozen=True)
class RulesConfig:
    hand_size: int = 10
    last_phase: int = 10  # play phases 1..last_phase
    skip_cooldown: bool = False  # house rule: a skipped player must play a turn before they can be skipped again

    def __post_init__(self) -> None:
        if not 1 <= self.last_phase <= len(PHASES):
            raise ValueError("last_phase must be 1..10")
        if not 1 <= self.hand_size <= 15:
            raise ValueError("hand_size must be 1..15")


@dataclass
class HandResult:
    hand: int
    went_out: int | None  # None: the cards ran out
    phases: list[int]  # the phase each player played this hand
    made: list[bool]  # who laid down their phase
    points: list[int]  # penalty points scored this hand
    left: list[list[Card]]  # cards left in each hand
    played: list[bool]  # who was dealt in (everyone, except in a tie-break hand)
    tiebreak: list[int] = field(default_factory=list)  # set when this hand ended in a tie: who replays the last phase

    def to_json(self) -> dict[str, Any]:
        return {
            "hand": self.hand,
            "went_out": self.went_out,
            "phases": self.phases,
            "made": self.made,
            "points": self.points,
            "left": [[c.to_json() for c in cards] for cards in self.left],
            "played": self.played,
            "tiebreak": self.tiebreak,
        }


@dataclass
class Result:
    winners: list[int]
    finishers: list[int]  # everyone who completed the last phase
    scores: list[int]


@dataclass
class View:
    """Everything one seat may know. Bots decide from this only."""

    seat: int
    n: int
    step: Step
    current: int
    hand: list[Card]
    phases: list[int]
    scores: list[int]
    laid: list[bool]
    hand_counts: list[int]
    groups: list[Group]
    discard_top: Card | None
    draw_size: int
    skipped: set[int]
    rules: RulesConfig
    discards: list[Card] = field(default_factory=list)  # the whole visible discard pile, bottom to top
    skip_targets: list[int] = field(default_factory=list)  # who a Skip may hit right now
    active: list[bool] = field(default_factory=list)  # who is dealt in this hand

    @property
    def reqs(self) -> tuple[Req, ...]:
        return PHASES[self.phases[self.seat] - 1]


class Game:
    def __init__(self, n: int, seed: int | None = None, rules: RulesConfig | None = None) -> None:
        if not 2 <= n <= 6:
            raise ValueError("Phase 10 is for 2 to 6 players")
        self.n = n
        self.rules = rules or RulesConfig()
        self.rng = random.Random(seed)
        self.deck = make_deck()
        self.phases = [1] * n
        self.scores = [0] * n
        self.hand_no = 0
        self.dealer = self.rng.randrange(n)
        self.history: list[HandResult] = []
        self.result: Result | None = None
        self.turn = 0  # counts turns over the whole game
        self.hands: list[list[Card]] = [[] for _ in range(n)]
        self.draw: list[Card] = []  # top is the end of the list
        self.discard: list[Card] = []
        self.groups: list[Group] = []
        self.laid = [False] * n
        self.skipped: set[int] = set()  # will lose their next turn
        self.skip_cards: dict[int, Card] = {}  # the Skip lying in front of a skipped player until their turn
        self.skip_spent: set[int] = set()  # lost a turn and haven't played since (the skip_cooldown house rule)
        self.active = [True] * n  # dealt in; a tie-break hand deals only the tied players
        self.tied: list[int] = []  # finished level on points: replaying the last phase
        self.current = 0
        self.step_ = Step.DRAW
        self.drew_from: str | None = None
        self._next_group = 0
        self.deal_events = self._deal()

    # ------------------------------------------------------------------ hands
    def _deal(self) -> list[Event]:
        self.hand_no += 1
        cards = list(self.deck)
        self.rng.shuffle(cards)
        self.hands = [[] for _ in range(self.n)]
        order = [(self.dealer + 1 + i) % self.n for i in range(self.n)]
        for _ in range(self.rules.hand_size):
            for seat in order:
                if self.active[seat]:
                    self.hands[seat].append(cards.pop())
        self.discard = [cards.pop()]
        self.draw = cards
        self.groups = []
        self.laid = [False] * self.n
        self.skipped = set()
        self.skip_cards = {}
        self.skip_spent = set()
        self.current = self._next_seat(self.dealer)
        deal = {"kind": "deal", "hand": self.hand_no, "dealer": self.dealer, "active": list(self.active)}
        events: list[Event] = [deal]
        if self.discard[-1].skip:
            self.skipped.add(self.current)
        self._begin_turn(events)
        return events

    def next_hand(self) -> list[Event]:
        if self.step_ != Step.HAND_OVER:
            raise IllegalMove("The hand isn't over yet")
        self.dealer = (self.dealer + 1) % self.n
        return self._deal()

    def _next_seat(self, seat: int) -> int:
        """The next player clockwise who is dealt in."""
        for step in range(1, self.n + 1):
            nxt = (seat + step) % self.n
            if self.active[nxt]:
                return nxt
        raise AssertionError("nobody is dealt in")

    def _begin_turn(self, events: list[Event]) -> None:
        while self.current in self.skipped:
            self.skipped.discard(self.current)
            self.skip_spent.add(self.current)
            card = self.skip_cards.pop(self.current, None)
            if card is not None:
                self.discard.append(card)
            events.append({"kind": "skipped", "seat": self.current, "card": card.to_json() if card else None})
            self.current = self._next_seat(self.current)
        self.skip_spent.discard(self.current)
        self.turn += 1
        self.step_ = Step.DRAW
        self.drew_from = None
        events.append({"kind": "turn", "seat": self.current})
        if not self.draw and len(self.discard) <= 1 and not self._discard_drawable():
            events.append({"kind": "dry"})
            self._end_hand(None, events)

    def _discard_drawable(self) -> bool:
        return bool(self.discard) and not self.discard[-1].skip

    def _end_hand(self, went_out: int | None, events: list[Event]) -> None:
        points = [sum(c.points for c in hand) for hand in self.hands]
        result = HandResult(
            hand=self.hand_no,
            went_out=went_out,
            phases=list(self.phases),
            made=list(self.laid),
            points=points,
            left=[list(hand) for hand in self.hands],
            played=list(self.active),
        )
        self.history.append(result)
        for i in range(self.n):
            self.scores[i] += points[i]
        winners: list[int] = []
        if self.tied:
            # A tie-break hand between players who finished level: the first to go out wins.
            finishers = list(self.tied)
            if went_out is not None:
                winners = [went_out]
            else:
                result.tiebreak = list(self.tied)
        else:
            finishers = [i for i in range(self.n) if self.laid[i] and self.phases[i] == self.rules.last_phase]
            for i in range(self.n):
                if self.laid[i] and self.phases[i] < self.rules.last_phase:
                    self.phases[i] += 1
            if finishers:
                best = min(self.scores[i] for i in finishers)
                winners = [i for i in finishers if self.scores[i] == best]
                if len(winners) > 1:
                    # Several finished with the same lowest score: they replay the last phase.
                    self.tied = list(winners)
                    result.tiebreak = list(winners)
                    winners = []
        events.append({"kind": "hand_over", "result": result.to_json(), "scores": list(self.scores)})
        if winners:
            self.result = Result(winners=winners, finishers=finishers, scores=list(self.scores))
            self.step_ = Step.GAME_OVER
            events.append({"kind": "game_over", "winners": winners})
        else:
            self.step_ = Step.HAND_OVER
            if self.tied:
                self.active = [i in self.tied for i in range(self.n)]
                events.append({"kind": "tiebreak", "seats": list(self.tied)})

    # ------------------------------------------------------------------ queries
    @property
    def step(self) -> Step:
        return self.step_

    def reqs(self, seat: int) -> tuple[Req, ...]:
        return PHASES[self.phases[seat] - 1]

    def group(self, gid: int) -> Group:
        for g in self.groups:
            if g.id == gid:
                return g
        raise IllegalMove("That group isn't on the table")

    def skip_targets(self, seat: int) -> list[int]:
        """Not someone with a Skip in front of them; with skip_cooldown, also not someone whose turn was skipped
        and who hasn't played since."""
        return [
            i
            for i in range(self.n)
            if i != seat
            and self.active[i]
            and i not in self.skipped
            and not (self.rules.skip_cooldown and i in self.skip_spent)
        ]

    def options(self, seat: int | None) -> dict[str, Any]:
        """What the seat may try right now (the engine still validates every action)."""
        mine = seat is not None and seat == self.current
        draw = mine and self.step_ == Step.DRAW
        play = mine and self.step_ == Step.PLAY
        return {
            "draw_deck": draw and bool(self.draw or len(self.discard) > 1),
            "draw_discard": draw and self._discard_drawable(),
            "lay_down": play and seat is not None and not self.laid[seat],
            "hit": play and seat is not None and self.laid[seat],
            "discard": play,
            "skip_targets": self.skip_targets(seat) if play and seat is not None else [],
        }

    def view(self, seat: int) -> View:
        return View(
            seat=seat,
            n=self.n,
            step=self.step_,
            current=self.current,
            hand=list(self.hands[seat]),
            phases=list(self.phases),
            scores=list(self.scores),
            laid=list(self.laid),
            hand_counts=[len(h) for h in self.hands],
            groups=[Group(g.id, g.owner, g.kind, list(g.cards), g.value, g.low, g.color) for g in self.groups],
            discard_top=self.discard[-1] if self.discard else None,
            draw_size=len(self.draw),
            skipped=set(self.skipped),
            rules=self.rules,
            discards=list(self.discard),
            skip_targets=self.skip_targets(seat),
            active=list(self.active),
        )

    def card_count(self) -> int:
        """Cards in hands, piles and groups; always the whole deck."""
        return (
            sum(len(h) for h in self.hands)
            + len(self.draw)
            + len(self.discard)
            + len(self.skip_cards)
            + sum(len(g.cards) for g in self.groups)
        )

    # ------------------------------------------------------------------ hand order
    def arrange(self, seat: int, order: list[int]) -> None:
        """Reorder a hand (a free action, any time): `order` must be a permutation of the card ids held."""
        hand = self.hands[seat]
        by_id = {c.id: c for c in hand}
        if sorted(order) != sorted(by_id):
            raise IllegalMove("That's not the cards in your hand")
        self.hands[seat] = [by_id[i] for i in order]

    # ------------------------------------------------------------------ actions
    def play(self, seat: int, action: Action) -> list[Event]:
        """Apply `action` for `seat` (raises IllegalMove and leaves the state untouched if it isn't allowed)."""
        if self.step_ in (Step.HAND_OVER, Step.GAME_OVER):
            raise IllegalMove("The hand is over")
        if seat != self.current:
            raise IllegalMove("It's not your turn")
        events: list[Event] = []
        match action:
            case DrawDeck():
                self._draw_deck(seat, events)
            case DrawDiscard():
                self._draw_discard(seat, events)
            case LayDown():
                self._lay_down(seat, action, events)
            case Hit():
                self._hit(seat, action, events)
            case Discard():
                self._discard(seat, action, events)
            case _:
                raise IllegalMove(f"unknown action {action!r}")
        return events

    def _need(self, step: Step) -> None:
        if self.step_ != step:
            raise IllegalMove("Draw a card first" if step == Step.PLAY else "You already drew a card this turn")

    def _draw_deck(self, seat: int, events: list[Event]) -> None:
        self._need(Step.DRAW)
        if not self.draw:
            if len(self.discard) <= 1:
                raise IllegalMove("The draw pile is empty")
            top = self.discard.pop()
            self.draw = self.discard
            self.rng.shuffle(self.draw)
            self.discard = [top]
            events.append({"kind": "reshuffle", "count": len(self.draw)})
        card = self.draw.pop()
        self.hands[seat].append(card)
        self.step_ = Step.PLAY
        self.drew_from = "deck"
        events.append({"kind": "draw", "seat": seat, "from": "deck", "card": card.to_json()})

    def _draw_discard(self, seat: int, events: list[Event]) -> None:
        self._need(Step.DRAW)
        if not self.discard:
            raise IllegalMove("The discard pile is empty")
        if self.discard[-1].skip:
            raise IllegalMove("A Skip can't be picked up from the discard pile")
        card = self.discard.pop()
        self.hands[seat].append(card)
        self.step_ = Step.PLAY
        self.drew_from = "discard"
        events.append({"kind": "draw", "seat": seat, "from": "discard", "card": card.to_json()})

    def _take(self, seat: int, ids: list[int]) -> list[Card]:
        by_id = {c.id: c for c in self.hands[seat]}
        if len(set(ids)) != len(ids):
            raise IllegalMove("The same card was picked twice")
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise IllegalMove("You don't hold those cards")
        return [by_id[i] for i in ids]

    def _lay_down(self, seat: int, action: LayDown, events: list[Event]) -> None:
        self._need(Step.PLAY)
        if self.laid[seat]:
            raise IllegalMove("You already laid down your phase this hand")
        reqs = self.reqs(seat)
        specs = action.groups
        if len(specs) != len(reqs):
            raise IllegalMove(f"Phase {self.phases[seat]} needs {len(reqs)} group(s), you laid {len(specs)}")
        all_ids = [i for g in specs for i in g.cards]
        self._take(seat, all_ids)
        by_id = {c.id: c for c in self.hands[seat]}
        error: str | None = None
        built: list[Group] | None = None
        for order in permutations(range(len(reqs))):
            if any(specs[i].kind != reqs[j].kind for i, j in enumerate(order)):
                continue
            try:
                built = [
                    Group.build(
                        self._next_group + i,
                        seat,
                        reqs[j].kind,
                        [by_id[c] for c in specs[i].cards],
                        reqs[j].size,
                        specs[i].low,
                    )
                    for i, j in enumerate(order)
                ]
                break
            except InvalidGroup as e:
                error = error or str(e)
        if built is None:
            raise IllegalMove(error or f"Phase {self.phases[seat]} is {', '.join(r.label() for r in reqs)}")
        self._next_group += len(built)
        used = set(all_ids)
        self.hands[seat] = [c for c in self.hands[seat] if c.id not in used]
        self.groups.extend(built)
        self.laid[seat] = True
        events.append({"kind": "lay_down", "seat": seat, "phase": self.phases[seat], "groups": [g.id for g in built]})
        self._check_out(seat, events)

    def _hit(self, seat: int, action: Hit, events: list[Event]) -> None:
        self._need(Step.PLAY)
        if not self.laid[seat]:
            raise IllegalMove("Lay down your own phase before adding cards to groups")
        group = self.group(action.group)
        (card,) = self._take(seat, [action.card])
        try:
            end = group.add(card, action.end)
        except InvalidGroup as e:
            raise IllegalMove(str(e)) from None
        self.hands[seat] = [c for c in self.hands[seat] if c.id != card.id]
        events.append(
            {"kind": "hit", "seat": seat, "group": group.id, "owner": group.owner, "card": card.to_json(), "end": end}
        )
        self._check_out(seat, events)

    def _discard(self, seat: int, action: Discard, events: list[Event]) -> None:
        self._need(Step.PLAY)
        (card,) = self._take(seat, [action.card])
        target = action.target
        if card.skip:
            targets = self.skip_targets(seat)
            if target is None and len(targets) == 1:
                target = targets[0]
            if targets and target not in targets:
                raise IllegalMove("Choose a player to skip" if target is None else "That player can't be skipped")
            if not targets:
                target = None
        else:
            target = None
        self.hands[seat] = [c for c in self.hands[seat] if c.id != card.id]
        events.append({"kind": "discard", "seat": seat, "card": card.to_json(), "target": target})
        if target is None:
            self.discard.append(card)
        else:
            self.skipped.add(target)
            self.skip_cards[target] = card
        if not self.hands[seat]:
            events.append({"kind": "out", "seat": seat})
            self._end_hand(seat, events)
            return
        self.current = self._next_seat(seat)
        self._begin_turn(events)

    def _check_out(self, seat: int, events: list[Event]) -> None:
        if not self.hands[seat]:
            events.append({"kind": "out", "seat": seat})
            self._end_hand(seat, events)


__all__ = ["Event", "Game", "HandResult", "IllegalMove", "Result", "RulesConfig", "Step", "View"]
