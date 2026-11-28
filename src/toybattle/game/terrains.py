"""The eight terrains (original layouts): bases, paths, H.Q.s, medal regions and each terrain's special bases.

Coordinates live in a 100 × 160 box, y pointing down. Red (side 1) sits at the top, Blue (side 0) at the bottom.
Most terrains are point-symmetric: they are written as their top half (plus the middle row) and `_build` adds the
mirror image, so both players get exactly the same board seen from their own side. A name ending in `'` refers to
the mirror image of a top-half node.

A region is a closed area surrounded by paths and bases; `ring` lists its border in order (it may pass through an
H.Q., which is not a base). Whoever occupies every base of a region takes its medals.

Special base effects (the terrain's `effect`):
  recall   Castle Field     you may return 1 of your other visible troops from the board to your rack
  restrict Tropical Pool   only the listed strengths (or a joker) may be placed on these bases and the H.Q.s
  draw     City of Clouds      you may draw 1 troop
  move     Volcanic Jungle  you may move 1 visible enemy troop adjacent to this base to a base adjacent to it
  revive   Cursed Cemetery   you may take 1 of your troops from the discard back to your rack
  none     Caribbean Sea   no special bases, but Blue has two H.Q.s
  shield   Station Metal-X   troop effects are not applied when a troop is placed here (no Paper Plane airdrop)
  snipe    Battlefield    a random troop of your opponent's rack is pinned: they can't place it on their next turn
"""

from __future__ import annotations

from dataclasses import dataclass, field

W, H = 100, 160


@dataclass(frozen=True)
class Node:
    id: int
    name: str
    kind: str  # "base" | "special" | "hq"
    x: float
    y: float
    side: int | None = None  # owner of an H.Q.
    allow: frozenset[int] | None = None  # restrict: kinds allowed (jokers always fit)

    @property
    def is_base(self) -> bool:
        return self.kind != "hq"


@dataclass(frozen=True)
class Region:
    id: int
    ring: tuple[int, ...]  # border nodes in order (bases and maybe an H.Q.)
    bases: tuple[int, ...]  # the bases to occupy
    medals: int
    cx: float
    cy: float


@dataclass(frozen=True)
class Terrain:
    key: str
    name: str
    effect: str
    effect_title: str
    effect_text: str
    blurb: str
    objective: tuple[int, int]  # medals to win, per side (Blue, Red)
    nodes: tuple[Node, ...]
    edges: tuple[tuple[int, int], ...]
    regions: tuple[Region, ...]
    palette: str  # art theme for the client
    first_game: bool = False
    adj: tuple[tuple[int, ...], ...] = field(default=(), compare=False)

    def hqs(self, side: int) -> tuple[int, ...]:
        return tuple(n.id for n in self.nodes if n.kind == "hq" and n.side == side)

    @property
    def medals(self) -> int:
        return sum(r.medals for r in self.regions)

    def public(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "effect": self.effect,
            "effect_title": self.effect_title,
            "effect_text": self.effect_text,
            "blurb": self.blurb,
            "objective": list(self.objective),
            "palette": self.palette,
            "first_game": self.first_game,
            "medals": self.medals,
            "nodes": [
                {
                    "id": n.id,
                    "kind": n.kind,
                    "x": n.x,
                    "y": n.y,
                    "side": n.side,
                    "allow": sorted(n.allow) if n.allow is not None else None,
                }
                for n in self.nodes
            ],
            "edges": [list(e) for e in self.edges],
            "regions": [
                {"id": r.id, "ring": list(r.ring), "bases": list(r.bases), "medals": r.medals, "cx": r.cx, "cy": r.cy}
                for r in self.regions
            ],
        }


Spec = tuple[float, float, str] | tuple[float, float, str, tuple[int, ...]]


def _build(
    key: str,
    name: str,
    effect: str,
    effect_title: str,
    effect_text: str,
    blurb: str,
    objective: tuple[int, int],
    nodes: dict[str, Spec],
    edges: str,
    regions: list[tuple[str, int]],
    palette: str,
    symmetric: bool = True,
    hq_allow: tuple[int, ...] | None = None,
    first_game: bool = False,
) -> Terrain:
    """Turn a readable description into a Terrain. `nodes`: name -> (x, y, kind[, allowed kinds])."""
    names: dict[str, int] = {}
    built: list[Node] = []

    def add(nm: str, x: float, y: float, kind: str, allow: tuple[int, ...] | None) -> int:
        side = None
        if kind in ("hq", "hq0", "hq1"):
            side = 0 if kind == "hq0" or (kind == "hq" and y > H / 2) else 1
            kind = "hq"
            allow = hq_allow
        node = Node(len(built), nm, kind, x, y, side, frozenset(allow) if allow is not None else None)
        built.append(node)
        names[nm] = node.id
        return node.id

    at: dict[tuple[float, float], str] = {}
    for nm, spec in nodes.items():
        x, y, kind = spec[0], spec[1], spec[2]
        allow = spec[3] if len(spec) > 3 else None  # type: ignore[misc]
        add(nm, x, y, kind, allow)
        at[(x, y)] = nm

    def mirror_name(nm: str) -> str:
        if nm.endswith("'"):
            return nm[:-1]
        n = built[names[nm]]
        twin = at.get((W - n.x, H - n.y))
        return twin if twin is not None else nm + "'"

    if symmetric:
        for nm in list(nodes):
            n = built[names[nm]]
            mx, my = W - n.x, H - n.y
            if (mx, my) in at:
                continue
            add(nm + "'", mx, my, n.kind if n.kind != "hq" else "hq", tuple(n.allow) if n.allow is not None else None)
            at[(mx, my)] = nm + "'"

    edge_set: set[tuple[int, int]] = set()
    for pair in edges.split():
        a, b = pair.split("-")
        for x, y in ((a, b), (mirror_name(a), mirror_name(b))) if symmetric else ((a, b),):
            i, j = names[x], names[y]
            edge_set.add((min(i, j), max(i, j)))

    region_list: list[Region] = []
    seen: set[frozenset[int]] = set()
    for ring_text, medals in regions:
        rings = [ring_text.split()]
        if symmetric:
            rings.append([mirror_name(x) for x in ring_text.split()])
        for ring_names in rings:
            ring = tuple(names[x] for x in ring_names)
            if frozenset(ring) in seen:
                continue
            seen.add(frozenset(ring))
            bases = tuple(i for i in ring if built[i].is_base)
            cx = sum(built[i].x for i in ring) / len(ring)
            cy = sum(built[i].y for i in ring) / len(ring)
            region_list.append(Region(len(region_list), ring, bases, medals, round(cx, 2), round(cy, 2)))

    adj: list[list[int]] = [[] for _ in built]
    for a, b in sorted(edge_set):
        adj[a].append(b)
        adj[b].append(a)
    return Terrain(
        key=key,
        name=name,
        effect=effect,
        effect_title=effect_title,
        effect_text=effect_text,
        blurb=blurb,
        objective=objective,
        nodes=tuple(built),
        edges=tuple(sorted(edge_set)),
        regions=tuple(region_list),
        palette=palette,
        first_game=first_game,
        adj=tuple(tuple(sorted(a)) for a in adj),
    )


RUG = _build(
    "rug",
    "Castle Field",
    "recall",
    "Toy chest",
    "You may take 1 of your other visible troops anywhere on the board back to your rack.",
    "A cosy carpet battlefield, the best place for a first game.",
    (7, 7),
    {
        "H": (50, 8, "hq"),
        "a": (16, 20, "base"),
        "b": (84, 20, "base"),
        "c": (36, 34, "base"),
        "e": (64, 34, "base"),
        "f": (12, 50, "special"),
        "d": (88, 50, "special"),
        "m1": (20, 80, "base"),
        "m2": (50, 80, "base"),
        "m3": (80, 80, "base"),
    },
    "H-a H-b a-c b-e c-f c-m1 c-m2 e-d e-m2 e-m3 f-m1 d-m3",
    [("c f m1", 1), ("e d m3", 1), ("c m1 e' m2", 2), ("H a c m2 e b", 3)],
    palette="rug",
    first_game=True,
)

LAGOON = _build(
    "lagoon",
    "Tropical Pool",
    "restrict",
    "Rubber rings",
    "Only the strengths shown on a ring (or a Jack) may be placed there. Both H.Q.s of a side take only 6 or 7.",
    "Soap bubbles, a rubber duck fleet and very picky floating rings. Two H.Q.s each: taking either one wins.",
    (6, 6),
    {
        "H1": (15, 16, "hq"),
        "H2": (85, 16, "hq"),
        "t": (50, 17, "base"),
        "a": (16, 40, "base"),
        "c": (50, 43, "base"),
        "r1": (84, 40, "special", (1, 2)),
        "r2": (83, 63, "base"),
        "l1": (15, 66, "special", (3, 4, 5)),
        "m": (50, 80, "special", (6, 7)),
    },
    "H1-c H2-t t-c t-r1 c-r1 a-c a-m c-m a-l1 l1-r2' r1-r2 r2-m",
    [("t c r1", 1), ("a c m", 1), ("c r1 r2 m", 2), ("a l1 r2' m", 2)],
    palette="lagoon",
    hq_allow=(6, 7),
)

PILLOW = _build(
    "pillow",
    "City of Clouds",
    "draw",
    "Snack stash",
    "You may draw 1 troop from your reserve.",
    "Cushion ramparts, blanket tunnels and secret cookie stashes.",
    (8, 8),
    {
        "H": (50, 9, "hq"),
        "s1": (50, 34, "special"),
        "s2": (50, 62, "special"),
        "a1": (12, 23, "base"),
        "a2": (12, 50, "base"),
        "a3": (12, 80, "base"),
        "b1": (88, 23, "base"),
        "b2": (88, 50, "base"),
    },
    "H-a1 H-b1 s1-a1 s1-a2 s1-b1 s1-b2 s2-a2 s2-a3 s2-b2 s2-a3' a1-a2 a2-a3 a3-b2' b2'-b1'",
    [
        ("H a1 s1 b1", 1),
        ("a1 a2 s1", 1),
        ("b1 b2 s1", 1),
        ("s1 a2 s2 b2", 2),
        ("a2 a3 s2", 1),
        ("b2 a3' s2", 1),
        ("s2 a3 s2' a3'", 2),
    ],
    palette="pillow",
)

LAVA = _build(
    "lava",
    "Volcanic Jungle",
    "move",
    "Hot floor",
    "You may push 1 visible enemy troop adjacent to this base onto any base adjacent to where it stands.",
    "Hop from sofa to stool: one wrong step and you're toast.",
    (7, 7),
    {
        "a": (19, 13, "base"),
        "b": (50, 13, "base"),
        "H": (86, 13, "hq"),
        "d": (50, 45, "base"),
        "e": (85, 45, "base"),
        "s": (13, 43, "special"),
        "f": (13, 80, "base"),
        "m": (50, 80, "base"),
    },
    "a-b b-H b-d d-m b-e H-e e-f' f-m a-s s-d s-f",
    [("a b d s", 2), ("s d m f", 2), ("b e f' m d", 3)],
    palette="lava",
)

ATTIC = _build(
    "attic",
    "Cursed Cemetery",
    "revive",
    "Old trunk",
    "You may take 1 of your troops from the discard back to your rack.",
    "Dusty trunks, creaky floorboards and toys that come back at night.",
    (7, 7),
    {
        "H": (83, 13, "hq"),
        "a": (30, 15, "base"),
        "b": (54, 37, "base"),
        "c": (33, 57, "base"),
        "d": (69, 56, "base"),
        "p": (15, 37, "special"),
        "q": (86, 37, "special"),
        "e": (13, 80, "base"),
        "m": (50, 80, "base"),
    },
    "a-H b-H a-b a-p p-c a-c b-q b-d q-d c-d d-m c-m c-e e-d'",
    [("a p c", 1), ("a b d c", 2), ("b q d", 1), ("c d m", 1), ("c e d' m", 2)],
    palette="attic",
)

GUTTER = _build(
    "gutter",
    "Caribbean Sea",
    "none",
    "Two harbours",
    "No special bases, but Blue defends two H.Q.s. Capturing either one wins.",
    "Wooden bridges between palm islands. Blue has two docks, Red a single pirate ship.",
    (5, 5),
    {
        "R": (51, 18, "hq1"),
        "a": (16, 18, "base"),
        "b": (16, 47, "base"),
        "c": (49, 48, "base"),
        "d": (76, 32, "base"),
        "e": (88, 63, "base"),
        "f": (16, 81, "base"),
        "g": (50, 81, "base"),
        "h": (86, 100, "base"),
        "i": (16, 110, "base"),
        "j": (41, 110, "base"),
        "k": (65, 119, "base"),
        "l": (48, 148, "base"),
        "B1": (16, 149, "hq0"),
        "B2": (86, 149, "hq0"),
    },
    "R-a R-c a-b b-c b-f c-d c-g d-e d-k e-h f-g f-j g-k h-k h-B2 i-j i-B1 j-l k-l l-B1",
    [
        ("R a b c", 1),
        ("b c g f", 2),
        ("c d k g", 2),
        ("d e h k", 2),
        ("f g k l j", 3),
        ("i j l B1", 1),
    ],
    palette="gutter",
    symmetric=False,
)

WORKSHOP = _build(
    "workshop",
    "Station Metal-X",
    "shield",
    "Repair bay",
    "A troop placed here doesn't apply its effect, and a Paper Plane can't airdrop here.",
    "Conveyor belts and repair bays where every gadget switches off.",
    (7, 7),
    {
        "H": (87, 9, "hq"),
        "t1": (12, 10, "base"),
        "t2": (57, 25, "base"),
        "t3": (12, 44, "base"),
        "t4": (90, 44, "base"),
        "c1": (51, 55, "base"),
        "sl": (30, 80, "special"),
        "sc": (50, 80, "special"),
    },
    "t1-H t1-t3 t1-c1 t2-H t2-c1 t2-t4 t3-c1 t4-c1 t3-sl t4-sl' c1-sl c1-sc c1-sl' sl-sc",
    [
        ("H t1 c1 t2", 1),
        ("t1 t3 c1", 1),
        ("t2 t4 c1", 1),
        ("t3 c1 sl", 1),
        ("t4 c1 sl'", 1),
        ("c1 sl sc", 1),
        ("c1 sc sl'", 1),
    ],
    palette="workshop",
)

SANDPIT = _build(
    "sandpit",
    "Battlefield",
    "snipe",
    "Sandbag bunker",
    "A random troop on your opponent's rack is pinned down: they can't place it on their next turn.",
    "Bucket forts and sandbag trenches. Keep your head down!",
    (8, 8),
    {
        "H": (50, 14, "hq"),
        "a": (21, 16, "base"),
        "b": (79, 16, "base"),
        "c": (22, 43, "base"),
        "d": (79, 43, "base"),
        "k": (50, 40, "special"),
        "l": (11, 80, "special"),
        "m1": (37, 80, "base"),
    },
    "H-a H-b a-c b-d c-k d-k c-l c-m1 k-m1 k-m1' d-m1' d-l'",
    [
        ("H a c k d b", 3),
        ("c k m1", 1),
        ("d k m1'", 1),
        ("c m1 d' l", 2),
        ("k m1 k' m1'", 2),
    ],
    palette="sandpit",
)

TERRAINS: dict[str, Terrain] = {t.key: t for t in (RUG, LAGOON, PILLOW, LAVA, ATTIC, GUTTER, WORKSHOP, SANDPIT)}
DEFAULT_TERRAIN = "rug"
