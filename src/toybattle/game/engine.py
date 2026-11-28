"""The rules engine: one match between Blue (side 0, bottom) and Red (side 1, top). Seat number = side.

Turn: either DRAW 2 troops (rack holds at most 8) or PLACE 1 troop on a slot connected to your H.Q. Then the
placed troop's effect, then (if it stands on a special base) the base's effect. Every "you may" effect becomes a
decision (`Phase.EFFECT`, with "skip" always allowed); effects that can't do anything are skipped silently.
Cap'n-style extra placements resolve the extra troop's effect first; special base effects come after all troop
effects of the turn, in placement order.

Regions are checked after every change to the board, for both players: whoever occupies every base around a
region takes its medals (once per region). The game ends at once when a troop lands on an enemy H.Q., when a
player reaches their medals objective, or at the start of a turn when the player can neither draw nor place
(more medals wins; on a tie the stuck player loses).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from toybattle.game.terrains import TERRAINS, Terrain
from toybattle.game.troops import (
    ARMY,
    JOKER,
    KIND_INFO,
    RACK_MAX,
    REMOVED_AT_SETUP,
    START_RACK,
    army,
    beats,
    kind_of,
    side_of,
)

Event = dict[str, Any]

BASE_EFFECTS = {"recall": "recall", "draw": "bdraw", "move": "move", "revive": "revive", "snipe": "snipe"}
DRAW_COUNT = {"draw2": 2, "draw1": 1, "bdraw": 1}


class Phase(StrEnum):
    TURN = "turn"
    EFFECT = "effect"
    OVER = "over"


class IllegalMove(Exception):
    """The action is not legal now; the game state is unchanged."""


class BadAction(ValueError):
    """Malformed action JSON."""


ACTION_TYPES = ("draw", "place", "skip", "take", "knock", "recall", "move", "revive")


@dataclass(frozen=True, slots=True)
class Action:
    """draw · place(troop, node) · skip · take (accept a draw / magnet / snipe effect) · knock(node) ·
    recall(node) · move(node -> to) · revive(troop)."""

    type: str
    troop: int = -1
    node: int = -1
    to: int = -1

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.troop >= 0:
            out["troop"] = self.troop
        if self.node >= 0:
            out["node"] = self.node
        if self.to >= 0:
            out["to"] = self.to
        return out

    @staticmethod
    def from_json(data: object) -> Action:
        if not isinstance(data, dict) or data.get("type") not in ACTION_TYPES:
            raise BadAction("unknown action")
        values = {}
        for key in ("troop", "node", "to"):
            v = data.get(key, -1)
            if not isinstance(v, int) or isinstance(v, bool) or not -1 <= v < 1000:
                raise BadAction(f"bad {key}")
            values[key] = v
        return Action(str(data["type"]), **values)


DRAW = Action("draw")
SKIP = Action("skip")
TAKE = Action("take")


@dataclass(slots=True)
class Effect:
    kind: str  # draw2 draw1 extra knock snatch | recall bdraw move revive snipe
    troop: int  # the troop whose placement triggered it
    node: int  # where that troop was placed

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "troop": self.troop, "node": self.node}


@dataclass
class Result:
    winner: int
    reason: str  # "hq" | "medals" | "stuck"
    medals: list[int]


@dataclass(frozen=True)
class View:
    """Everything one player may know (what a player at the table sees and could remember)."""

    seat: int
    terrain: str
    special: bool
    phase: Phase
    current: int
    turn: int
    stacks: tuple[tuple[int, ...], ...]
    rack: tuple[int, ...]
    pinned: frozenset[int]
    opp_rack: int
    opp_pinned: int
    opp_known: frozenset[int]  # troops publicly known to be on the opponent's rack
    my_known: frozenset[int]  # troops of mine the opponent knows about
    reserves: tuple[int, int]
    discard: tuple[int, ...]
    medals: tuple[int, int]
    region_taken: tuple[int | None, ...]
    pending: Effect | None
    troop_fx: tuple[Effect, ...]
    base_fx: tuple[Effect, ...]
    legal: tuple[Action, ...]


@dataclass
class Game:
    terrain_key: str = "rug"
    special: bool = True  # special base effects on (the rulebook suggests off for first games)
    seed: int | None = None
    starter: int | None = None
    rng: random.Random = field(init=False)
    terrain: Terrain = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.terrain = TERRAINS[self.terrain_key]
        t = self.terrain
        self.stacks: list[list[int]] = [[] for _ in t.nodes]
        self.reserve: list[list[int]] = []
        self.removed: list[list[int]] = []
        for side in range(2):
            pool = army(side)
            self.rng.shuffle(pool)
            self.removed.append(pool[:REMOVED_AT_SETUP])
            self.reserve.append(pool[REMOVED_AT_SETUP:])
        if self.starter is None:
            self.starter = self.rng.randrange(2)
        self.rack: list[list[int]] = [[], []]
        for side in range(2):
            n = START_RACK[0] if side == self.starter else START_RACK[1]
            for _ in range(n):
                self.rack[side].append(self.reserve[side].pop())
        self.discard: list[int] = []
        self.medals = [0, 0]
        self.region_taken: list[int | None] = [None] * len(t.regions)
        self.pinned: list[set[int]] = [set(), set()]
        self.known: list[set[int]] = [set(), set()]  # troops on a rack the opponent knows
        self.current = self.starter
        self.turn = 1
        self.phase = Phase.TURN
        self.pending: Effect | None = None
        self.troop_fx: list[Effect] = []
        self.base_fx: list[Effect] = []
        self.result: Result | None = None
        self.placed_this_turn = 0
        self._events: list[Event] = []
        self._begin_turn()

    # ------------------------------------------------------------------ copying (bots search on copies)
    def clone(self) -> Game:
        g = object.__new__(Game)
        g.terrain_key = self.terrain_key
        g.special = self.special
        g.seed = self.seed
        g.starter = self.starter
        g.rng = random.Random(self.rng.random())
        g.terrain = self.terrain
        g.stacks = [list(s) for s in self.stacks]
        g.reserve = [list(r) for r in self.reserve]
        g.removed = [list(r) for r in self.removed]
        g.rack = [list(r) for r in self.rack]
        g.discard = list(self.discard)
        g.medals = list(self.medals)
        g.region_taken = list(self.region_taken)
        g.pinned = [set(p) for p in self.pinned]
        g.known = [set(k) for k in self.known]
        g.current = self.current
        g.turn = self.turn
        g.phase = self.phase
        g.pending = self.pending
        g.troop_fx = list(self.troop_fx)
        g.base_fx = list(self.base_fx)
        g.result = self.result
        g.placed_this_turn = self.placed_this_turn
        g._events = []
        return g

    # ------------------------------------------------------------------ board queries
    def top(self, node: int) -> int | None:
        s = self.stacks[node]
        return s[-1] if s else None

    def owner(self, node: int) -> int | None:
        s = self.stacks[node]
        return s[-1] // ARMY if s else None

    def _shielded(self, node: int) -> bool:
        return self.special and self.terrain.effect == "shield" and self.terrain.nodes[node].kind == "special"

    def _allowed(self, node: int, kind: int) -> bool:
        n = self.terrain.nodes[node]
        if not self.special or n.allow is None or self.terrain.effect != "restrict":
            return True
        return kind == JOKER or kind in n.allow

    def connected(self, side: int) -> set[int]:
        """Bases occupied by `side` that a continuous path of its own bases links to one of its H.Q.s."""
        t = self.terrain
        seen: set[int] = set()
        todo = list(t.hqs(side))
        stacks = self.stacks
        nodes = t.nodes
        while todo:
            cur = todo.pop()
            for nb in t.adj[cur]:
                if nb in seen or not nodes[nb].is_base:
                    continue
                s = stacks[nb]
                if s and s[-1] // ARMY == side:
                    seen.add(nb)
                    todo.append(nb)
        return seen

    def reachable(self, side: int) -> set[int]:
        """Slots a connected placement could go to: neighbours of the H.Q.s and of connected bases."""
        t = self.terrain
        conn = self.connected(side)
        out: set[int] = set(conn)
        for src in (*t.hqs(side), *conn):
            out.update(t.adj[src])
        out.difference_update(t.hqs(side))
        return out

    def can_land(self, side: int, kind: int, node: int) -> bool:
        """The slot rule (not the connection rule)."""
        n = self.terrain.nodes[node]
        if n.kind == "hq":
            return n.side != side and self._allowed(node, kind)
        if not self._allowed(node, kind):
            return False
        s = self.stacks[node]
        if not s:
            return True
        top = s[-1]
        return top // ARMY == side or beats(kind, kind_of(top))

    def targets(self, side: int, kind: int, reach: set[int] | None = None) -> list[int]:
        """Nodes a troop of this kind may be placed on now."""
        if reach is None:
            reach = self.reachable(side)
        nodes = self.terrain.nodes
        if kind == 4:  # Paper Plane: any base, connected or not (but not a shielded special base); H.Q. needs it
            out = [
                n.id
                for n in nodes
                if (n.is_base and (n.id in reach or not self._shielded(n.id))) or (n.kind == "hq" and n.id in reach)
            ]
        else:
            out = sorted(reach)
        return [n for n in out if self.can_land(side, kind, n)]

    def usable(self, side: int) -> list[int]:
        return [t for t in self.rack[side] if t not in self.pinned[side]]

    def placements(self, side: int) -> list[Action]:
        reach = self.reachable(side)
        by_kind: dict[int, list[int]] = {}
        out: list[Action] = []
        for troop in self.usable(side):
            k = kind_of(troop)
            if k not in by_kind:
                by_kind[k] = self.targets(side, k, reach)
            out.extend(Action("place", troop, node) for node in by_kind[k])
        return out

    def can_draw(self, side: int) -> bool:
        return len(self.rack[side]) < RACK_MAX and bool(self.reserve[side])

    # ------------------------------------------------------------------ legal actions
    def legal_actions(self, seat: int | None = None) -> list[Action]:
        if self.phase == Phase.OVER or (seat is not None and seat != self.current):
            return []
        side = self.current
        if self.phase == Phase.TURN:
            out = [DRAW] if self.can_draw(side) else []
            return out + self.placements(side)
        assert self.pending is not None
        return [*self._effect_options(self.pending), SKIP]

    def _effect_options(self, fx: Effect) -> list[Action]:
        side = self.current
        enemy = 1 - side
        t = self.terrain
        k = fx.kind
        if k in DRAW_COUNT:
            return [TAKE] if self.can_draw(side) else []
        if k == "extra":
            return self.placements(side)
        if k == "knock":
            return [
                Action("knock", node=n)
                for n in t.adj[fx.node]
                if t.nodes[n].is_base and self.owner(n) == enemy and self.top(fx.node) == fx.troop
            ]
        if k == "snatch":
            return [TAKE] if self.rack[enemy] else []
        if k == "snipe":
            return [TAKE] if any(x not in self.pinned[enemy] for x in self.rack[enemy]) else []
        if len(self.rack[side]) >= RACK_MAX and k in ("recall", "revive"):
            return []
        if k == "recall":
            return [
                Action("recall", node=n.id)
                for n in t.nodes
                if n.is_base and self.owner(n.id) == side and self.top(n.id) != fx.troop
            ]
        if k == "revive":
            seen: set[int] = set()
            out = []
            for troop in self.discard:
                if side_of(troop) == side and troop not in seen:
                    seen.add(troop)
                    out.append(Action("revive", troop=troop))
            return out
        if k == "move":
            return [
                Action("move", node=n, to=m)
                for n in t.adj[fx.node]
                if t.nodes[n].is_base and self.owner(n) == enemy
                for m in t.adj[n]
                if t.nodes[m].is_base
            ]
        raise AssertionError(k)

    def is_legal(self, seat: int, action: Action) -> bool:
        if self.phase == Phase.OVER or seat != self.current:
            return False
        side = seat
        if action.type == "place" and (self.phase == Phase.TURN or (self.pending and self.pending.kind == "extra")):
            if action.troop not in self.rack[side] or action.troop in self.pinned[side]:
                return False
            if not 0 <= action.node < len(self.terrain.nodes):
                return False
            return action.node in self.targets(side, kind_of(action.troop))
        if self.phase == Phase.TURN:
            return action == DRAW and self.can_draw(side)
        if action == SKIP:
            return True
        assert self.pending is not None
        return action in self._effect_options(self.pending)

    # ------------------------------------------------------------------ stepping
    def step(self, seat: int, action: Action) -> list[Event]:
        if not self.is_legal(seat, action):
            raise IllegalMove(f"illegal action {action.to_json()}")
        self._events = []
        side = seat
        if self.phase == Phase.TURN:
            if action.type == "draw":
                self._draw(side, 2, "action")
                self._end_turn()
            else:
                self._place(side, action.troop, action.node)
                self._advance()
        else:
            fx = self.pending
            assert fx is not None
            self.pending = None
            self.phase = Phase.TURN  # transient; _advance sets the real phase
            if action.type == "skip":
                self._emit({"kind": "skip", "seat": side, "effect": fx.kind})
            else:
                self._resolve(side, fx, action)
            if self.result is None:
                self._advance()
        events, self._events = self._events, []
        return events

    def _emit(self, event: Event) -> None:
        self._events.append(event)

    def _draw(self, side: int, n: int, source: str) -> None:
        n = min(n, RACK_MAX - len(self.rack[side]), len(self.reserve[side]))
        drawn = [self.reserve[side].pop() for _ in range(n)]
        self.rack[side].extend(drawn)
        self._emit({"kind": "draw", "seat": side, "troops": drawn, "source": source})

    def _leave_rack(self, side: int, troop: int) -> None:
        self.rack[side].remove(troop)
        self.known[side].discard(troop)
        self.pinned[side].discard(troop)

    def _place(self, side: int, troop: int, node: int) -> None:
        self._leave_rack(side, troop)
        covered = self.top(node)
        self.stacks[node].append(troop)
        self.placed_this_turn += 1
        self._emit({"kind": "place", "seat": side, "troop": troop, "node": node, "covered": covered})
        if self.terrain.nodes[node].kind == "hq":
            self._finish(side, "hq")
            return
        self._regions()
        if self.result is not None:
            return
        effect = KIND_INFO[kind_of(troop)].effect
        if effect and effect != "airdrop" and not self._shielded(node):
            self.troop_fx.append(Effect(effect, troop, node))
        if self.special and self.terrain.nodes[node].kind == "special" and self.terrain.effect in BASE_EFFECTS:
            self.base_fx.append(Effect(BASE_EFFECTS[self.terrain.effect], troop, node))

    def _resolve(self, side: int, fx: Effect, action: Action) -> None:
        enemy = 1 - side
        k = fx.kind
        if k in DRAW_COUNT:
            self._draw(side, DRAW_COUNT[k], k)
        elif k == "extra":
            self._emit({"kind": "rally", "seat": side, "troop": fx.troop})
            self._place(side, action.troop, action.node)
        elif k == "knock":
            victim = self.stacks[action.node].pop()
            self.discard.append(victim)
            self._emit({"kind": "knock", "seat": side, "troop": victim, "node": action.node, "by": fx.node})
            self._regions()
        elif k == "snatch":
            victim = self.rng.choice(self.rack[enemy])
            self._leave_rack(enemy, victim)
            self.discard.append(victim)
            self._emit({"kind": "snatch", "seat": side, "troop": victim})
        elif k == "snipe":
            standing = [x for x in self.rack[enemy] if x not in self.pinned[enemy]]
            victim = self.rng.choice(standing)
            self.pinned[enemy].add(victim)
            self._emit({"kind": "pin", "seat": side, "target": enemy, "troop": victim})
        elif k == "recall":
            troop = self.stacks[action.node].pop()
            self.rack[side].append(troop)
            self.known[side].add(troop)
            self._emit({"kind": "recall", "seat": side, "troop": troop, "node": action.node})
            self._regions()
        elif k == "revive":
            self.discard.remove(action.troop)
            self.rack[side].append(action.troop)
            self.known[side].add(action.troop)
            self._emit({"kind": "revive", "seat": side, "troop": action.troop})
        elif k == "move":
            troop = self.stacks[action.node].pop()
            self.stacks[action.to].append(troop)
            self._emit({"kind": "move", "seat": side, "troop": troop, "node": action.node, "to": action.to})
            self._regions()
        else:
            raise AssertionError(k)

    def _advance(self) -> None:
        """Open the next effect that can do something, or end the turn."""
        if self.result is not None:
            return
        while self.troop_fx or self.base_fx:
            fx = self.troop_fx.pop() if self.troop_fx else self.base_fx.pop(0)
            if fx.kind in BASE_EFFECTS.values() and self.top(fx.node) != fx.troop:
                continue  # the troop no longer stands on its special base
            if self._effect_options(fx):
                self.pending = fx
                self.phase = Phase.EFFECT
                return
        self._end_turn()

    def _end_turn(self) -> None:
        side = self.current
        if self.pinned[side]:
            self._emit({"kind": "unpin", "seat": side, "troops": sorted(self.pinned[side])})
            self.pinned[side].clear()
        self.pending = None
        self.current = 1 - side
        self.turn += 1
        self.placed_this_turn = 0
        self.phase = Phase.TURN
        self._emit({"kind": "turn", "seat": self.current, "turn": self.turn})
        self._begin_turn()

    def _begin_turn(self) -> None:
        side = self.current
        if self.can_draw(side) or self.placements(side):
            return
        other = 1 - side
        winner = side if self.medals[side] > self.medals[other] else other
        self._emit({"kind": "stuck", "seat": side})
        self._finish(winner, "stuck")

    def _regions(self) -> None:
        t = self.terrain
        stacks = self.stacks
        for region in t.regions:
            if region.medals == 0 or self.region_taken[region.id] is not None:
                continue
            owner = None
            for b in region.bases:
                s = stacks[b]
                o = s[-1] // ARMY if s else None
                if o is None or (owner is not None and o != owner):
                    owner = None
                    break
                owner = o
            if owner is not None:
                self.region_taken[region.id] = owner
                self.medals[owner] += region.medals
                self._emit({"kind": "medals", "seat": owner, "region": region.id, "medals": region.medals})
        for side in (self.current, 1 - self.current):
            if self.medals[side] >= t.objective[side] and self.result is None:
                self._finish(side, "medals")

    def _finish(self, winner: int, reason: str) -> None:
        self.result = Result(winner, reason, list(self.medals))
        self.phase = Phase.OVER
        self.pending = None
        self.troop_fx.clear()
        self.base_fx.clear()
        self._emit({"kind": "game_over", "winner": winner, "reason": reason, "medals": list(self.medals)})

    # ------------------------------------------------------------------ views
    def view(self, seat: int) -> View:
        enemy = 1 - seat
        return View(
            seat=seat,
            terrain=self.terrain_key,
            special=self.special,
            phase=self.phase,
            current=self.current,
            turn=self.turn,
            stacks=tuple(tuple(s) for s in self.stacks),
            rack=tuple(self.rack[seat]),
            pinned=frozenset(self.pinned[seat]),
            opp_rack=len(self.rack[enemy]),
            opp_pinned=len(self.pinned[enemy]),
            opp_known=frozenset(self.known[enemy]),
            my_known=frozenset(self.known[seat]),
            reserves=(len(self.reserve[0]), len(self.reserve[1])),
            discard=tuple(self.discard),
            medals=(self.medals[0], self.medals[1]),
            region_taken=tuple(self.region_taken),
            pending=self.pending,
            troop_fx=tuple(self.troop_fx),
            base_fx=tuple(self.base_fx),
            legal=tuple(self.legal_actions(seat)) if seat == self.current else (),
        )

    @classmethod
    def from_view(cls, view: View, rng: random.Random, opp_pinned_pool: list[int] | None = None) -> Game:
        """A full game consistent with what `view.seat` knows: hidden troops dealt at random (determinization)."""
        g = object.__new__(Game)
        me, enemy = view.seat, 1 - view.seat
        g.terrain_key = view.terrain
        g.special = view.special
        g.seed = None
        g.starter = None
        g.rng = random.Random(rng.random())
        g.terrain = TERRAINS[view.terrain]
        g.stacks = [list(s) for s in view.stacks]
        public = {x for s in view.stacks for x in s} | set(view.discard)
        mine_unknown = [x for x in army(me) if x not in public and x not in view.rack]
        rng.shuffle(mine_unknown)
        n_res = view.reserves[me]
        g.reserve = [[], []]
        g.removed = [[], []]
        g.reserve[me] = mine_unknown[:n_res]
        g.removed[me] = mine_unknown[n_res:]
        theirs = [x for x in army(enemy) if x not in public and x not in view.opp_known]
        rng.shuffle(theirs)
        hidden_rack = view.opp_rack - len(view.opp_known)
        rack_e = sorted(view.opp_known) + theirs[:hidden_rack]
        rest = theirs[hidden_rack:]
        n_res_e = view.reserves[enemy]
        g.reserve[enemy] = rest[:n_res_e]
        g.removed[enemy] = rest[n_res_e:]
        g.rack = [[], []]
        g.rack[me] = list(view.rack)
        g.rack[enemy] = rack_e
        g.discard = list(view.discard)
        g.medals = list(view.medals)
        g.region_taken = list(view.region_taken)
        g.pinned = [set(), set()]
        g.pinned[me] = set(view.pinned)
        hidden_part = rack_e[len(view.opp_known) :]
        g.pinned[enemy] = set(hidden_part[: view.opp_pinned]) if view.opp_pinned else set()
        g.known = [set(), set()]
        g.known[me] = set(view.my_known)
        g.known[enemy] = set(view.opp_known)
        g.current = view.current
        g.turn = view.turn
        g.phase = view.phase
        g.pending = view.pending
        g.troop_fx = list(view.troop_fx)
        g.base_fx = list(view.base_fx)
        g.result = None
        g.placed_this_turn = 0
        g._events = []
        return g

    # ------------------------------------------------------------------ invariants
    def check(self) -> None:
        seen: list[int] = []
        for s in self.stacks:
            seen.extend(s)
        for side in range(2):
            seen.extend(self.rack[side])
            seen.extend(self.reserve[side])
            seen.extend(self.removed[side])
            assert len(self.rack[side]) <= RACK_MAX, "rack overflow"
            assert self.pinned[side] <= set(self.rack[side]), "pinned troop not on rack"
            assert self.known[side] <= set(self.rack[side]), "known troop not on rack"
            assert len(self.removed[side]) == REMOVED_AT_SETUP
        seen.extend(self.discard)
        assert sorted(seen) == list(range(2 * ARMY)), "every troop exactly once"
        for node in self.terrain.nodes:
            if node.kind == "hq":
                assert len(self.stacks[node.id]) <= 1
                if self.stacks[node.id]:
                    assert self.result is not None and self.result.reason == "hq"
        assert sum(r.medals for r in self.terrain.regions if self.region_taken[r.id] is not None) == sum(self.medals)
        assert (self.phase == Phase.EFFECT) == (self.pending is not None)
        assert (self.phase == Phase.OVER) == (self.result is not None)
