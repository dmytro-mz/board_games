"""The Agent Avenue state machine (official rules: simple mode, advanced mode, team variant).

Cards are small ints (indices into `AGENT_LIST` / `MARKET_LIST`). Two *sides* (green = 0, blue = 1) share a meeple
and the cards in play; a side has one player, or two in the team variant. Players are seats 0..n-1.

A turn: the active side plays 2 cards (1 face up, 1 face down; in teams each teammate plays one), the other side
recruits one of them and the active side recruits the other, both meeples move, black market spaces are resolved
(advanced mode), then the End step checks who won.

Actions are tuples: ("discard", card) · ("play", up, down) with -1 for "not this one" (team variant) ·
("recruit", 0 = face up / 1 = face down) · ("market", supply index) · ("choose", option).
`Game.step(player, action)` validates against `Game.legal(player)` and returns a list of event dicts.
Hidden values (cards nobody may see) are -1 in a `redacted()` copy — that is all a bot ever gets.
"""

from __future__ import annotations

import random
from enum import StrEnum
from typing import Any

from avenue.game.cards import (
    AGENT_LIST,
    BRAINWASHING,
    CODEBREAKER,
    DAREDEVIL,
    DECK_COUNTS,
    DISCARDS_SOLO,
    DISCARDS_TEAM,
    DISTRACTION,
    DOUBLE_AGENT,
    DOUBLE_TROUBLE,
    ENFORCER,
    GETAWAY,
    HAND_SIZE,
    HOMES,
    LEADER,
    MARKET_LIST,
    MARKET_SPACES,
    MASTERPLAN,
    N_AGENTS,
    N_MARKET,
    OUTPOST,
    SABOTEUR,
    SECRET_RECRUIT,
    SECURITY,
    SENTINEL,
    SINISTER_TWIN,
    SMOKE_SCREEN,
    SPYCATION,
    SUPERCOMPUTER,
    SUPPLY_SIZE,
    TRACK,
    TRUCK,
    WATCHTOWER,
    base_move,
)

Event = dict[str, Any]
Action = tuple[Any, ...]
HIDDEN = -1


class IllegalMove(Exception):
    """The action is not allowed right now; the game state is unchanged."""


class Phase(StrEnum):
    PLAY = "play"  # the active side plays its 2 cards (and may discard first)
    RECRUIT = "recruit"  # the other side picks the face-up or the face-down card
    MARKET = "market"  # a side landed on a black market space and takes a card from the supply
    CHOICE = "choice"  # a black market ability waits for a decision
    OVER = "over"


def agent_key(card: int) -> str:
    return AGENT_LIST[card].key if card >= 0 else "hidden"


def market_key(card: int) -> str:
    return MARKET_LIST[card].key if card >= 0 else "hidden"


class Game:
    __slots__ = (
        "active",
        "advanced",
        "choice",
        "deck",
        "discards",
        "discards_left",
        "down",
        "first",
        "hands",
        "known",
        "market_deck",
        "market_discard",
        "owned",
        "phase",
        "pos",
        "queue",
        "result",
        "rng",
        "side_of",
        "sides",
        "supply",
        "tableau",
        "turn",
        "up",
    )

    def __init__(
        self,
        teams: list[int] | None = None,
        *,
        advanced: bool = False,
        seed: int | None = None,
        first: int | None = None,
        _blank: bool = False,
    ) -> None:
        if _blank:
            return
        teams = list(teams) if teams is not None else [0, 1]
        sizes = [teams.count(0), teams.count(1)]
        if len(teams) not in (2, 3, 4) or not all(1 <= s <= 2 for s in sizes):
            raise ValueError("need 2-4 players in two sides of 1-2 players")
        self.rng = random.Random(seed)
        self.side_of = teams
        self.sides = [[p for p, t in enumerate(teams) if t == side] for side in (0, 1)]
        self.advanced = advanced
        self.deck = [card for card, n in enumerate(DECK_COUNTS) for _ in range(n)]
        self.rng.shuffle(self.deck)
        self.hands = [[self.deck.pop() for _ in range(HAND_SIZE)] for _ in teams]
        self.discards: list[list[int]] = [[] for _ in teams]
        self.discards_left = [DISCARDS_SOLO if sizes[t] == 1 else DISCARDS_TEAM for t in teams]
        self.known: list[list[int]] = [[] for _ in teams]  # cards everybody knows are in that hand
        self.tableau = [[0] * N_AGENTS, [0] * N_AGENTS]
        self.pos = [HOMES[0], HOMES[1]]  # absolute progress; the space is pos % TRACK
        self.owned: list[list[int]] = [[], []]  # ongoing black market cards in play
        self.market_deck: list[int] = []
        self.supply: list[int] = []
        self.market_discard: list[int] = []
        if advanced:
            self.market_deck = list(range(N_MARKET))
            self.rng.shuffle(self.market_deck)
            self.supply = [self.market_deck.pop() for _ in range(SUPPLY_SIZE)]
        self.first = first if first in (0, 1) else self.rng.randrange(2)
        self.active = self.first
        self.turn = 1
        self.phase = Phase.PLAY
        self.up: tuple[int, int] | None = None  # (player, card)
        self.down: tuple[int, int] | None = None
        self.queue: list[int] = []  # sides waiting to take a black market card (front first)
        self.choice: dict[str, Any] | None = None
        self.result: dict[str, Any] | None = None

    # ------------------------------------------------------------------ copies
    def clone(self) -> Game:
        g = Game(_blank=True)
        g.rng = self.rng  # only used to set up a game
        g.side_of = self.side_of
        g.sides = self.sides
        g.advanced = self.advanced
        g.deck = self.deck[:]
        g.hands = [h[:] for h in self.hands]
        g.discards = [d[:] for d in self.discards]
        g.discards_left = self.discards_left[:]
        g.known = [k[:] for k in self.known]
        g.tableau = [self.tableau[0][:], self.tableau[1][:]]
        g.pos = self.pos[:]
        g.owned = [self.owned[0][:], self.owned[1][:]]
        g.market_deck = self.market_deck[:]
        g.supply = self.supply[:]
        g.market_discard = self.market_discard[:]
        g.first = self.first
        g.active = self.active
        g.turn = self.turn
        g.phase = self.phase
        g.up = self.up
        g.down = self.down
        g.queue = self.queue[:]
        g.choice = dict(self.choice) if self.choice else None
        g.result = self.result
        return g

    def redacted(self, player: int) -> Game:
        """A copy with everything `player` can't see replaced by HIDDEN (and a fresh random generator)."""
        g = self.clone()
        g.rng = random.Random()
        g.deck = [HIDDEN] * len(self.deck)
        g.market_deck = [HIDDEN] * len(self.market_deck)
        for p in range(len(self.hands)):
            if p == player:
                continue
            # Publicly known cards (taken back into a hand by an ability). Whether such a card was later
            # discarded face down is unknown to the others, so it stays "known".
            visible = self.known[p][: len(self.hands[p])]
            g.hands[p] = visible + [HIDDEN] * (len(self.hands[p]) - len(visible))
            g.discards[p] = [HIDDEN] * len(self.discards[p])
        if self.down is not None and self.down[0] != player:
            g.down = (self.down[0], HIDDEN)
        return g

    # ------------------------------------------------------------------ basic queries
    @property
    def n_players(self) -> int:
        return len(self.side_of)

    def solo(self, side: int) -> bool:
        return len(self.sides[side]) == 1

    def square(self, side: int) -> int:
        return self.pos[side] % TRACK

    def distance(self, side: int) -> int:
        """Spaces `side` still has to go to catch the other meeple (<= 0: caught)."""
        if side == 0:
            return self.pos[1] - self.pos[0]
        return self.pos[0] + TRACK - self.pos[1]

    def has(self, side: int, market_card: int) -> bool:
        return self.advanced and market_card in self.owned[side]

    def move_value(self, side: int, agent: int, count: int | None = None) -> int:
        """Spaces `side` moves when recruiting `agent` (count = copies in play including the new one)."""
        if count is None:
            count = self.tableau[side][agent]
        steps = base_move(agent, count)
        if self.advanced and self.owned[side]:
            owned = self.owned[side]
            if agent == DOUBLE_AGENT and SINISTER_TWIN in owned:
                steps *= 2
            elif agent == SABOTEUR and DISTRACTION in owned:
                steps = abs(steps)
            elif agent == ENFORCER and WATCHTOWER in owned:
                steps += 2
            elif agent == CODEBREAKER and SUPERCOMPUTER in owned:
                steps += 3
        return steps

    def can_discard(self, player: int) -> bool:
        return (
            self.phase == Phase.PLAY
            and self.side_of[player] == self.active
            and self.discards_left[player] > 0
            and bool(self.deck)
            and not self._has_played(player)
        )

    def _has_played(self, player: int) -> bool:
        return (self.up is not None and self.up[0] == player) or (self.down is not None and self.down[0] == player)

    def legal(self, player: int) -> list[Action]:
        phase = self.phase
        side = self.side_of[player]
        if phase == Phase.PLAY:
            if side != self.active or self._has_played(player):
                return []
            hand = self.hands[player]
            names = sorted(set(hand))
            out: list[Action] = []
            if self.can_discard(player):
                out.extend(("discard", c) for c in names)
            if self.solo(side):
                if len(names) == 1 and len(hand) >= 2:
                    out.append(("play", names[0], names[0]))
                else:
                    out.extend(("play", a, b) for a in names for b in names if a != b)
            elif self.up is None:
                out.extend(("play", c, -1) for c in names)
            else:
                shown = self.up[1]
                others = [c for c in names if c != shown]
                out.extend(("play", -1, c) for c in (others or names))
            return out
        if phase == Phase.RECRUIT:
            return [("recruit", 0), ("recruit", 1)] if side != self.active else []
        if phase == Phase.MARKET:
            return [("market", i) for i in range(len(self.supply))] if self.queue and side == self.queue[0] else []
        if phase == Phase.CHOICE:
            ch = self.choice
            assert ch is not None
            return [("choose", o) for o in ch["options"]] if ch["player"] == player else []
        return []

    def waiting(self) -> list[int]:
        """Players who may act now."""
        return [p for p in range(self.n_players) if self.legal(p)]

    # ------------------------------------------------------------------ stepping
    def step(self, player: int, action: Action) -> list[Event]:
        if self.phase == Phase.OVER:
            raise IllegalMove("The game is over")
        if not 0 <= player < self.n_players:
            raise IllegalMove("No such player")
        if action not in self.legal(player):
            raise IllegalMove(self._why_illegal(player, action))
        events: list[Event] = []
        kind = action[0]
        if kind == "discard":
            self._discard(player, action[1], events)
        elif kind == "play":
            self._play(player, action[1], action[2], events)
        elif kind == "recruit":
            self._recruit(player, action[1], events)
        elif kind == "market":
            self._take_market(player, action[1], events)
        elif kind == "choose":
            self._choose(player, action[1], events)
        return events

    def _why_illegal(self, player: int, action: Action) -> str:
        if not self.legal(player):
            return "It's not your turn"
        if action and action[0] == "play" and self.phase == Phase.PLAY:
            return "Play 2 cards with different names: 1 face up and 1 face down"
        if action and action[0] == "discard":
            if not self.deck:
                return "The agent deck is empty — you can't discard any more"
            if self.discards_left[player] <= 0:
                return "You have no discards left"
        return "That move is not allowed right now"

    def _draw(self, player: int, events: list[Event]) -> None:
        drawn = []
        while len(self.hands[player]) < HAND_SIZE and self.deck:
            card = self.deck.pop()
            self.hands[player].append(card)
            drawn.append(card)
        if drawn:
            events.append({"kind": "draw", "player": player, "cards": [agent_key(c) for c in drawn]})

    def _forget(self, player: int, card: int) -> None:
        if card in self.known[player]:
            self.known[player].remove(card)

    def _discard(self, player: int, card: int, events: list[Event]) -> None:
        self.hands[player].remove(card)
        self.discards[player].append(card)
        self.discards_left[player] -= 1
        events.append(
            {"kind": "discard", "player": player, "card": agent_key(card), "left": self.discards_left[player]}
        )
        self._draw(player, events)

    def _play(self, player: int, up: int, down: int, events: list[Event]) -> None:
        side = self.side_of[player]
        hand = self.hands[player]
        if up >= 0:
            hand.remove(up)
            self.up = (player, up)
            self._forget(player, up)
        if down >= 0:
            hand.remove(down)
            self.down = (player, down)
        events.append(
            {
                "kind": "play",
                "player": player,
                "side": side,
                "up": agent_key(up) if up >= 0 else None,
                "down": agent_key(down) if down >= 0 else None,
                "slots": [slot for slot, card in (("up", up), ("down", down)) if card >= 0],
            }
        )
        self._draw(player, events)
        if self.up is not None and self.down is not None:
            self.phase = Phase.RECRUIT

    def _recruit(self, player: int, take: int, events: list[Event]) -> None:
        assert self.up is not None and self.down is not None
        active, other = self.active, 1 - self.active
        up_player, up_card = self.up
        down_player, down_card = self.down
        self._forget(down_player, down_card)
        taken, left = (up_card, down_card) if take == 0 else (down_card, up_card)
        self.up = self.down = None
        events.append(
            {
                "kind": "recruit",
                "player": player,
                "side": other,
                "take": "up" if take == 0 else "down",
                "card": agent_key(taken),
                "other": agent_key(left),
                "down": agent_key(down_card),
                "down_player": down_player,
                "up_player": up_player,
            }
        )
        self.tableau[other][taken] += 1
        self.tableau[active][left] += 1
        # Both meeples move; when both land on black market spaces the active side takes a card first.
        landed_active = self._move(active, self.move_value(active, left), events, agent_key(left))
        landed_other = self._move(other, self.move_value(other, taken), events, agent_key(taken))
        self.queue = [s for s, landed in ((active, landed_active), (other, landed_other)) if landed]
        self._continue(events)

    def _move(self, side: int, steps: int, events: list[Event], why: str) -> bool:
        """Move a meeple; returns True when it landed exactly on a black market space (advanced mode)."""
        start = self.pos[side]
        self.pos[side] += steps
        events.append({"kind": "move", "side": side, "steps": steps, "from": start, "to": self.pos[side], "why": why})
        if steps == 0 or not self.advanced:
            return False
        if self.square(side) in HOMES and GETAWAY in self.owned[side]:
            start = self.pos[side]
            self.pos[side] += 3
            events.append(
                {"kind": "move", "side": side, "steps": 3, "from": start, "to": self.pos[side], "why": "getaway_car"}
            )
        return self.square(side) in MARKET_SPACES

    def _continue(self, events: list[Event]) -> None:
        """Run the black market queue until a decision is needed, then the End step."""
        while self.choice is None:
            if not self.queue:
                self._end_step(events)
                return
            if not self.supply:
                side = self.queue.pop(0)
                events.append({"kind": "market_empty", "side": side})
                continue
            self.phase = Phase.MARKET
            return
        self.phase = Phase.CHOICE

    def _take_market(self, player: int, index: int, events: list[Event]) -> None:
        side = self.queue.pop(0)
        card = self.supply[index]
        refill = self.market_deck.pop() if self.market_deck else None
        if refill is None:
            del self.supply[index]
        else:
            self.supply[index] = refill
        events.append(
            {
                "kind": "market",
                "player": player,
                "side": side,
                "card": market_key(card),
                "index": index,
                "refill": market_key(refill) if refill is not None else None,
            }
        )
        if MARKET_LIST[card].ongoing:
            self.owned[side].append(card)
        else:
            self._instant(player, side, card, events)
            if self.choice is None:
                self._finish_instant(card, events)
        self._continue(events)

    def _finish_instant(self, card: int, events: list[Event]) -> None:
        self.market_discard.append(card)
        for p in range(self.n_players):
            self._draw(p, events)

    def _ignored(self, side: int, card: int, events: list[Event]) -> None:
        events.append({"kind": "ability", "side": side, "card": market_key(card), "effect": "none"})

    def _ask(self, player: int, side: int, card: int, stage: str, options: list[int], agent: int = -1) -> None:
        self.choice = {"player": player, "side": side, "card": card, "stage": stage, "options": options, "agent": agent}

    def _instant(self, player: int, side: int, card: int, events: list[Event]) -> None:
        hand = self.hands[player]
        if card == TRUCK:
            if self._move(side, 1, events, "surveillance_truck"):
                self.queue.insert(0, side)
        elif card == SMOKE_SCREEN:
            if not self.deck:
                self._ignored(side, card, events)
            else:
                self._recruit_extra(player, side, self.deck.pop(), card, events)
        elif card == OUTPOST:
            if SENTINEL in hand:
                hand.remove(SENTINEL)
                self._forget(player, SENTINEL)
                self._recruit_extra(player, side, SENTINEL, card, events)
            else:
                self._ignored(side, card, events)
        elif card == SECRET_RECRUIT:
            options = sorted({c for c in hand if self.tableau[side][c] == 0})
            self._offer(player, side, card, "secret", options, events)
        elif card == DOUBLE_TROUBLE:
            options = sorted({c for c in hand if hand.count(c) >= 2})
            self._offer(player, side, card, "double", options, events)
        elif card == BRAINWASHING:
            options = [c for c in range(N_AGENTS) if self.tableau[1 - side][c] > 0]
            self._offer(player, side, card, "steal", options, events)
        elif card == SPYCATION:
            options = [c for c in range(N_AGENTS) if self.tableau[side][c] > 0]
            if options:
                self._ask(player, side, card, "spy_pick", options)
            else:
                self._ignored(side, card, events)

    def _offer(self, player: int, side: int, card: int, stage: str, options: list[int], events: list[Event]) -> None:
        if not options:
            self._ignored(side, card, events)
        elif len(options) == 1:
            self._resolve_choice(player, side, card, stage, options[0], -1, events)
        else:
            self._ask(player, side, card, stage, options)

    def _choose(self, player: int, option: int, events: list[Event]) -> None:
        ch = self.choice
        assert ch is not None
        self.choice = None
        self._resolve_choice(player, ch["side"], ch["card"], ch["stage"], option, ch["agent"], events)
        if self.choice is None:
            self._finish_instant(ch["card"], events)
        self._continue(events)

    def _resolve_choice(
        self, player: int, side: int, card: int, stage: str, option: int, agent: int, events: list[Event]
    ) -> None:
        hand = self.hands[player]
        if stage in ("secret", "double"):
            hand.remove(option)
            self._forget(player, option)
            if stage == "double":
                events.append({"kind": "reveal", "player": player, "cards": [agent_key(option)] * 2})
                if self.known[player].count(option) < hand.count(option):
                    self.known[player].append(option)
            self._recruit_extra(player, side, option, card, events)
        elif stage == "steal":
            self.tableau[1 - side][option] -= 1
            hand.append(option)
            self.known[player].append(option)
            events.append(
                {"kind": "steal", "player": player, "side": side, "from": 1 - side, "card": agent_key(option)}
            )
        elif stage == "spy_pick":
            self.tableau[side][option] -= 1
            hand.append(option)
            self.known[player].append(option)
            events.append({"kind": "spycation", "player": player, "side": side, "card": agent_key(option)})
            self._ask(player, side, card, "spy_recruit", [1, 0], option)
        elif stage == "spy_recruit":
            if option:
                hand.remove(agent)
                self._forget(player, agent)
                self._recruit_extra(player, side, agent, card, events)
            else:
                events.append({"kind": "keep", "player": player, "side": side, "card": agent_key(agent)})

    def _recruit_extra(self, player: int, side: int, agent: int, source: int, events: list[Event]) -> None:
        """Recruit through a black market ability: into play, then move (maybe onto another market space)."""
        self.tableau[side][agent] += 1
        events.append(
            {
                "kind": "ability_recruit",
                "player": player,
                "side": side,
                "card": agent_key(agent),
                "source": market_key(source),
            }
        )
        if self._move(side, self.move_value(side, agent), events, agent_key(agent)):
            self.queue.insert(0, side)

    # ------------------------------------------------------------------ end step
    def win_reasons(self, side: int) -> list[str]:
        reasons = []
        if self.distance(side) <= 0:
            reasons.append("caught")
        if self.tableau[side][CODEBREAKER] >= 3:
            reasons.append("codebreakers")
        if self.advanced:
            owned = self.owned[side]
            if MASTERPLAN in owned and sum(1 for n in self.tableau[side] if n) >= 7:
                reasons.append("masterplan")
            if SECURITY in owned and self.square(1 - side) == HOMES[side]:
                reasons.append("security_system")
            if LEADER in owned and self.tableau[side][DAREDEVIL] >= 3:
                reasons.append("leader_of_the_pack")
        return reasons

    def lose_reasons(self, side: int) -> list[str]:
        if self.tableau[side][DAREDEVIL] >= 3 and not self.has(side, LEADER):
            return ["daredevils"]
        return []

    def _end_step(self, events: list[Event]) -> None:
        active = self.active
        claims: list[list[str]] = [[], []]  # reasons why each side would win
        for side in (0, 1):
            claims[side] += self.win_reasons(side)
            claims[1 - side] += [f"opponent_{r}" for r in self.lose_reasons(side)]
        if claims[0] or claims[1]:
            tie = bool(claims[0]) and bool(claims[1])
            winner = active if tie else (0 if claims[0] else 1)
            self._over(winner, claims[winner], tie, events, claims)
            return
        following = 1 - active
        need = 2 if self.solo(following) else 1
        if not self.deck and any(len(self.hands[p]) < need for p in self.sides[following]):
            d0, d1 = self.distance(0), self.distance(1)
            tie = d0 == d1
            winner = active if tie else (0 if d0 < d1 else 1)
            self._over(winner, ["out_of_cards"], tie, events, [["out_of_cards"], ["out_of_cards"]] if tie else None)
            return
        self.active = following
        self.turn += 1
        self.phase = Phase.PLAY
        events.append({"kind": "turn", "side": following, "turn": self.turn})

    def _over(
        self, winner: int, reasons: list[str], tie: bool, events: list[Event], claims: list[list[str]] | None = None
    ) -> None:
        """`reasons` are the winner's; `claims` what each side could claim (both non-empty on a tie)."""
        self.phase = Phase.OVER
        self.queue = []
        if claims is None:
            claims = [reasons, []] if winner == 0 else [[], reasons]
        self.result = {"winner": winner, "reasons": reasons, "tie": tie, "claims": claims, "turn": self.turn}
        events.append({"kind": "game_over", **self.result})

    # ------------------------------------------------------------------ consistency (tests)
    def agent_total(self) -> int:
        played = (self.up is not None) + (self.down is not None)
        return (
            len(self.deck)
            + sum(len(h) for h in self.hands)
            + sum(len(d) for d in self.discards)
            + sum(sum(t) for t in self.tableau)
            + played
        )
