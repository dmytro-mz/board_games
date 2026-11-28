"""Static evaluation of a position, from one side's point of view (positive = good for `me`).

The evaluator only reads the game it is given. Bots call it on *determinized* copies (hidden troops dealt at
random from what the bot may know), never on the real game.

Ingredients, per side: medals (more so close to the objective), region potential (how much of each open region
the side holds, damped by enemy troops that are hard to cover), connected bases, distance to the enemy H.Q.,
troops on the rack and in reserve. On top: immediate wins for the side to move, and threats of the other side
that the side to move cannot parry with one placement.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from toybattle.game.engine import Game, Phase
from toybattle.game.terrains import TERRAINS, Terrain
from toybattle.game.troops import ARMY, COPIES

WIN = 10_000.0


@dataclass(frozen=True)
class Weights:
    medal: float = 20.0
    near: float = 120.0  # extra for (medals / objective) ** 3
    region: float = 24.0  # per medal of region potential
    conn: float = 5.0
    reach: float = 1.5  # per base a side could place on
    dist: float = 7.0
    reserve: float = 0.75
    pinned: float = 0.7
    tempo: float = 15.0
    parried: float = 45.0  # a threat the side to move must spend its turn on
    hq_guard: float = 5.0  # own troops next to own H.Q. (scaled by how hard they are to cover)
    kind_value: tuple[float, ...] = (14, 9, 13, 11, 10, 9, 9, 13)
    lock: tuple[float, ...] = (0.3, 0.35, 0.35, 0.4, 0.45, 0.5, 0.65, 0.88)  # how firmly a troop blocks a region
    secure: tuple[float, ...] = (0.6, 0.72, 0.76, 0.8, 0.84, 0.88, 0.93, 1.0)  # how safely a troop holds a base
    step_cost: tuple[float, ...] = (1.4, 1.3, 1.4, 1.6, 1.8, 2.1, 2.6, 3.6)  # path cost through an enemy troop


@dataclass
class _Board:
    """Per-terrain tables."""

    terrain: Terrain
    is_base: list[bool]
    adj: list[tuple[int, ...]]
    hqs: tuple[tuple[int, ...], tuple[int, ...]]
    hq_nb: tuple[frozenset[int], frozenset[int]]  # bases next to each side's H.Q.s
    regions: list[tuple[int, tuple[int, ...], int]] = field(default_factory=list)  # (id, bases, medals)


_BOARDS: dict[str, _Board] = {}


def board(key: str) -> _Board:
    b = _BOARDS.get(key)
    if b is None:
        t = TERRAINS[key]
        hqs = (t.hqs(0), t.hqs(1))
        b = _Board(
            terrain=t,
            is_base=[n.is_base for n in t.nodes],
            adj=list(t.adj),
            hqs=hqs,
            hq_nb=tuple(frozenset(m for h in hqs[s] for m in t.adj[h] if t.nodes[m].is_base) for s in (0, 1)),  # type: ignore[arg-type]
            regions=[(r.id, r.bases, r.medals) for r in t.regions if r.medals > 0],
        )
        _BOARDS[key] = b
    return b


def usable_kinds(g: Game, side: int) -> set[int]:
    pinned = g.pinned[side]
    return {(t % ARMY) // COPIES for t in g.rack[side] if t not in pinned}


def reach_from(g: Game, side: int, conn: set[int]) -> set[int]:
    adj = g.terrain.adj
    out = set(conn)
    for src in g.terrain.hqs(side):
        out.update(adj[src])
    for src in conn:
        out.update(adj[src])
    return out


def win_nodes(g: Game, side: int, conn: set[int] | None = None, kinds: set[int] | None = None) -> list[int]:
    """Nodes where one placement by `side` wins at once (an enemy H.Q., or a base that reaches the objective)."""
    if kinds is None:
        kinds = usable_kinds(g, side)
    if not kinds:
        return []
    if conn is None:
        conn = g.connected(side)
    b = board(g.terrain_key)
    adj = b.adj
    out: list[int] = []
    for h in b.hqs[1 - side]:
        if any(m in conn for m in adj[h]) and any(g._allowed(h, k) for k in kinds):
            out.append(h)
    if 2 in kinds and not out:
        out.extend(_rally_hq(g, side, conn, kinds))
    gap = g.terrain.objective[side] - g.medals[side]
    stacks = g.stacks
    gain: dict[int, int] = {}
    taken = g.region_taken
    for rid, bases, medals in b.regions:
        if taken[rid] is not None:
            continue
        missing = -1
        for base in bases:
            s = stacks[base]
            if not s or s[-1] // ARMY != side:
                if missing >= 0:
                    missing = -2
                    break
                missing = base
        if missing >= 0:
            gain[missing] = gain.get(missing, 0) + medals
    if gain:
        reach = None
        for node, got in gain.items():
            if got < gap:
                continue
            if reach is None:
                reach = reach_from(g, side, conn)
            for k in kinds:
                if (node in reach or (k == 4 and not g._shielded(node))) and g.can_land(side, k, node):
                    out.append(node)
                    break
    return out


def _rally_hq(g: Game, side: int, conn: set[int], kinds: set[int]) -> list[int]:
    """Enemy H.Q.s a chain of Tin Drummers reaches this turn: each drummer lands next to the connected bases
    (possibly reconnecting cut-off ones) and the last extra placement lands on the H.Q. The board is changed in
    place and restored."""
    pinned = g.pinned[side]
    usable = [t for t in g.rack[side] if t not in pinned]
    drummers = sum(1 for t in usable if (t % ARMY) // COPIES == 2)
    steps = min(drummers, len(usable) - 1)
    if steps <= 0:
        return []
    b = board(g.terrain_key)
    finals = [h for h in b.hqs[1 - side] if any(g._allowed(h, k) for k in kinds)]
    if not finals:
        return []
    drummer = side * ARMY + 2 * COPIES
    stacks = g.stacks

    def search(conn: set[int], left: int) -> list[int]:
        for x in reach_from(g, side, conn):
            if not b.is_base[x] or x in conn or g._shielded(x) or not g.can_land(side, 2, x):
                continue
            stacks[x].append(drummer)
            try:
                now = g.connected(side)
                hit = [h for h in finals if any(m in now for m in b.adj[h])]
                if hit:
                    return hit
                if left > 1:
                    hit = search(now, left - 1)
                    if hit:
                        return hit
            finally:
                stacks[x].pop()
        return []

    return search(conn, steps)


def can_parry(g: Game, mover: int, attacker: int, kinds: set[int] | None = None) -> bool:
    """Can `mover` remove every immediate win of `attacker` with a single placement (covering, occupying, or a
    Slingshot Frog knock)? The board is changed in place and restored."""
    if kinds is None:
        kinds = usable_kinds(g, mover)
    if not kinds:
        return False
    conn_a = g.connected(attacker)
    threats = win_nodes(g, attacker, conn_a)
    if not threats:
        return True
    reach = reach_from(g, mover, g.connected(mover))
    b = board(g.terrain_key)
    candidates = set(conn_a)
    candidates.update(n for n in threats if b.is_base[n])
    candidates.update(b.hq_nb[mover])  # block the bases a drummer would step on
    stacks = g.stacks
    a_kinds = usable_kinds(g, attacker)
    order = sorted(kinds, key=lambda k: -k if k else 1)  # strongest first, the joker (anyone covers it) last
    for node in candidates:
        for k in order:
            if not (node in reach or (k == 4 and not g._shielded(node))) or not g.can_land(mover, k, node):
                continue
            stacks[node].append(mover * ARMY + k * COPIES)
            ok = not win_nodes(g, attacker, None, a_kinds)
            stacks[node].pop()
            if ok:
                return True
            break  # the owner is what matters here; another kind would not change the outcome
    if 3 in kinds:  # Slingshot Frog: land next to an attacker troop and knock it off
        for node in reach:
            if not b.is_base[node] or g._shielded(node) or not g.can_land(mover, 3, node):
                continue
            for m in b.adj[node]:
                s = stacks[m]
                if not b.is_base[m] or not s or s[-1] // ARMY != attacker:
                    continue
                stacks[node].append(mover * ARMY + 3 * COPIES)
                victim = s.pop()
                ok = not win_nodes(g, attacker, None, a_kinds)
                s.append(victim)
                stacks[node].pop()
                if ok:
                    return True
    return False


class Evaluator:
    def __init__(self, weights: Weights | None = None) -> None:
        self.w = weights or Weights()

    def mover(self, g: Game) -> int:
        """Who acts next with a free placement: the current player, unless only effects of their turn remain."""
        if g.phase == Phase.TURN or (g.pending is not None and g.pending.kind == "extra"):
            return g.current
        return 1 - g.current

    def __call__(self, g: Game, me: int) -> float:
        if g.result is not None:
            return WIN if g.result.winner == me else -WIN
        mover = self.mover(g)
        other = 1 - mover
        conn = (g.connected(0), g.connected(1))
        kinds = (usable_kinds(g, 0), usable_kinds(g, 1))
        sign = 1.0 if mover == me else -1.0
        if win_nodes(g, mover, conn[mover], kinds[mover]):
            return sign * 0.9 * WIN
        extra = self.w.tempo
        if win_nodes(g, other, conn[other], kinds[other]):
            if not can_parry(g, mover, other, kinds[mover]):
                return -sign * 0.85 * WIN
            extra -= self.w.parried
        v0 = self.side(g, 0, conn)
        v1 = self.side(g, 1, conn)
        diff = v0 - v1 if me == 0 else v1 - v0
        return diff + sign * extra

    def side(self, g: Game, s: int, conn: tuple[set[int], set[int]]) -> float:
        w = self.w
        b = board(g.terrain_key)
        t = b.terrain
        stacks = g.stacks
        obj = t.objective[s]
        m = g.medals[s]
        v = w.medal * m + w.near * (min(m, obj) / obj) ** 3
        # region potential
        region = 0.0
        taken = g.region_taken
        for rid, bases, medals in b.regions:
            if taken[rid] is not None:
                continue
            mine = 0.0
            block = 1.0
            for base in bases:
                st = stacks[base]
                if not st:
                    continue
                top = st[-1]
                k = (top % ARMY) // COPIES
                if top // ARMY == s:
                    mine += w.secure[k]
                else:
                    block *= 1.0 - w.lock[k]
            p = mine / len(bases)
            region += medals * p * p * block
        v += w.region * region
        # presence
        my_conn = conn[s]
        v += w.conn * len(my_conn)
        v += w.reach * len(reach_from(g, s, my_conn) - my_conn - set(b.hqs[s]))
        # guard of own H.Q.
        guard = 0.0
        for n in b.hq_nb[s]:
            st = stacks[n]
            if st and st[-1] // ARMY == s:
                guard += w.secure[(st[-1] % ARMY) // COPIES]
        v += w.hq_guard * guard
        # distance to the enemy H.Q.
        v -= w.dist * self.distance(g, s)
        # troops
        kv = w.kind_value
        pinned = g.pinned[s]
        for troop in g.rack[s]:
            val = kv[(troop % ARMY) // COPIES]
            v += val * w.pinned if troop in pinned else val
        v += w.reserve * len(g.reserve[s])
        return v

    def distance(self, g: Game, s: int) -> float:
        """Cheapest path from `s`'s H.Q.s to an enemy H.Q.: own troops are free, empty bases cost 1, enemy troops
        more the stronger they are."""
        b = board(g.terrain_key)
        stacks = g.stacks
        cost = self.w.step_cost
        targets = set(b.hqs[1 - s])
        dist: dict[int, float] = {}
        heap: list[tuple[float, int]] = [(0.0, h) for h in b.hqs[s]]
        while heap:
            d, n = heapq.heappop(heap)
            if n in dist:
                continue
            dist[n] = d
            if n in targets:
                return d
            for m in b.adj[n]:
                if m in dist:
                    continue
                if not b.is_base[m]:
                    if m in targets:
                        heapq.heappush(heap, (d, m))
                    continue
                st = stacks[m]
                if not st:
                    step = 1.0
                elif st[-1] // ARMY == s:
                    step = 0.0
                else:
                    step = cost[(st[-1] % ARMY) // COPIES]
                heapq.heappush(heap, (d + step, m))
        return 12.0
