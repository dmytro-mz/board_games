"""Build hand-made positions for rules tests."""

from __future__ import annotations

from toybattle.game.engine import Game, Phase
from toybattle.game.troops import ARMY, COPIES, army


def troop(side: int, kind: int, copy: int = 0) -> int:
    return side * ARMY + kind * COPIES + copy


def node(g: Game, name: str) -> int:
    return next(n.id for n in g.terrain.nodes if n.name == name)


def position(
    terrain: str = "rug",
    racks: tuple[list[int], list[int]] = ([], []),
    board: dict[str, list[int]] | None = None,
    current: int = 0,
    special: bool = True,
    medals: tuple[int, int] = (0, 0),
) -> Game:
    """A game on `terrain` with exactly these racks and stacks; every other troop sits in its reserve (4 per side
    put back in the box), so `Game.check()` holds."""
    g = Game(terrain, special=special, seed=0, starter=current)
    g.stacks = [[] for _ in g.terrain.nodes]
    used: set[int] = set()
    for name, stack in (board or {}).items():
        g.stacks[node(g, name)] = list(stack)
        used.update(stack)
    for side in (0, 1):
        used.update(racks[side])
    g.rack = [list(racks[0]), list(racks[1])]
    for side in (0, 1):
        rest = [t for t in army(side) if t not in used]
        g.removed[side] = rest[:4]
        g.reserve[side] = rest[4:]
    g.discard = []
    g.medals = list(medals)
    g.region_taken = [None] * len(g.terrain.regions)
    g.pinned = [set(), set()]
    g.known = [set(), set()]
    g.current = current
    g.phase = Phase.TURN
    g.pending = None
    g.troop_fx = []
    g.base_fx = []
    g.result = None
    return g


def take(g: Game, t: int) -> int:
    """Take troop `t` out of its owner's reserve (or the box, swapping in a reserve troop) so a test can put it
    somewhere else."""
    side = t // ARMY
    if t in g.reserve[side]:
        g.reserve[side].remove(t)
    elif t in g.removed[side]:
        g.removed[side].remove(t)
        g.removed[side].append(g.reserve[side].pop())
    else:
        raise ValueError(f"troop {t} is not in the reserve or the box")
    return t


def path_to_special(g: Game, side: int) -> str:
    """Occupy (with `side`'s troops from the reserve) a shortest path from its H.Q. to a special base; returns the
    special base's name, now a legal connected target."""
    from collections import deque

    t = g.terrain
    start = t.hqs(side)
    prev: dict[int, int | None] = {h: None for h in start}
    todo = deque(start)
    goal = None
    while todo:
        cur = todo.popleft()
        if t.nodes[cur].kind == "special":
            goal = cur
            break
        for nb in t.adj[cur]:
            if nb not in prev and t.nodes[nb].kind != "hq":
                prev[nb] = cur
                todo.append(nb)
    assert goal is not None
    step = prev[goal]
    while step is not None and t.nodes[step].kind != "hq":
        spare = next(x for x in g.reserve[side] if x // ARMY == side)
        g.stacks[step] = [take(g, spare)]
        step = prev[step]
    return t.nodes[goal].name
