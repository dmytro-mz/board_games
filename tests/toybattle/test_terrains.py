"""The eight boards are well formed: paths don't cross, regions are closed by paths, nothing sits inside a region."""

from __future__ import annotations

import pytest

from toybattle.game.terrains import TERRAINS, H, Terrain, W

Point = tuple[float, float]


def _cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Do segments ab and cd properly intersect (touching at shared endpoints doesn't count)?"""

    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    if {a, b} & {c, d}:
        return False
    d1, d2 = orient(c, d, a), orient(c, d, b)
    d3, d4 = orient(a, b, c), orient(a, b, d)
    return d1 * d2 < 0 and d3 * d4 < 0


def _inside(p: Point, poly: list[Point]) -> bool:
    x, y = p
    inside = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _xy(t: Terrain, n: int) -> Point:
    return (t.nodes[n].x, t.nodes[n].y)


@pytest.mark.parametrize("key", list(TERRAINS))
def test_terrain_is_well_formed(key: str) -> None:
    t = TERRAINS[key]
    assert t.key == key
    assert len(t.hqs(0)) >= 1 and len(t.hqs(1)) >= 1
    for n in t.nodes:
        assert 0 <= n.x <= W and 0 <= n.y <= H
    # connected graph
    seen = {0}
    todo = [0]
    while todo:
        for nb in t.adj[todo.pop()]:
            if nb not in seen:
                seen.add(nb)
                todo.append(nb)
    assert len(seen) == len(t.nodes)
    # H.Q.s are never next to each other
    for h in t.hqs(0):
        assert not set(t.adj[h]) & set(t.hqs(1))
    # paths don't cross
    for i, (a, b) in enumerate(t.edges):
        for c, d in t.edges[i + 1 :]:
            assert not _cross(_xy(t, a), _xy(t, b), _xy(t, c), _xy(t, d)), (
                key,
                t.nodes[a].name,
                t.nodes[b].name,
                t.nodes[c].name,
                t.nodes[d].name,
            )
    edges = set(t.edges)
    for r in t.regions:
        ring = list(r.ring)
        for i in range(len(ring)):
            a, b = ring[i - 1], ring[i]
            assert (min(a, b), max(a, b)) in edges, (key, r.id, t.nodes[a].name, t.nodes[b].name)
        poly = [_xy(t, n) for n in ring]
        for n in t.nodes:
            if n.id not in ring:
                assert not _inside((n.x, n.y), poly), (key, r.id, n.name)
        assert r.bases and all(t.nodes[b].is_base for b in r.bases)
    assert len({frozenset(r.ring) for r in t.regions}) == len(t.regions)
    for side in (0, 1):
        assert 0 < t.objective[side] < t.medals


@pytest.mark.parametrize("key", [k for k in TERRAINS if k != "gutter"])
def test_symmetric_terrains_are_fair(key: str) -> None:
    t = TERRAINS[key]
    assert t.objective[0] == t.objective[1]
    points = {(n.x, n.y, n.kind) for n in t.nodes}
    assert points == {(W - x, H - y, k) for x, y, k in points}
    medals = sorted((round(r.cx, 1), round(r.cy, 1), r.medals) for r in t.regions)
    assert medals == sorted((round(W - x, 1), round(H - y, 1), m) for x, y, m in medals)


def test_one_first_game_terrain_and_effects() -> None:
    assert [k for k, t in TERRAINS.items() if t.first_game] == ["rug"]
    assert {t.effect for t in TERRAINS.values()} == {
        "recall",
        "restrict",
        "draw",
        "move",
        "revive",
        "none",
        "shield",
        "snipe",
    }
    for t in TERRAINS.values():
        has_special = any(n.kind == "special" for n in t.nodes)
        assert has_special == (t.effect not in ("none", "restrict")) or t.effect == "restrict"


def test_tropical_pool_follows_the_published_map() -> None:
    t = TERRAINS["lagoon"]
    assert len(t.hqs(0)) == 2 and len(t.hqs(1)) == 2
    assert len(t.nodes) == 17 and len(t.edges) == 24
    assert sorted(len(r.bases) for r in t.regions) == [3, 3, 3, 3, 4, 4, 4, 4]
    assert sorted(r.medals for r in t.regions) == [1, 1, 1, 1, 2, 2, 2, 2]
    rings = sorted(tuple(sorted(n.allow)) for n in t.nodes if n.kind == "special")
    assert rings == [(1, 2), (1, 2), (3, 4, 5), (3, 4, 5), (6, 7)]
    assert all(n.allow == frozenset({6, 7}) for n in t.nodes if n.kind == "hq")


def test_city_of_clouds_follows_the_published_map() -> None:
    t = TERRAINS["pillow"]
    assert len(t.hqs(0)) == 1 and len(t.hqs(1)) == 1
    assert sum(n.kind == "special" for n in t.nodes) == 4 and sum(n.kind == "base" for n in t.nodes) == 10
    assert len(t.edges) == 28 and len(t.regions) == 13
    assert sorted(r.medals for r in t.regions) == [1] * 10 + [2] * 3
    assert t.medals == 16 and t.objective == (8, 8)


def test_volcanic_jungle_follows_the_published_map() -> None:
    t = TERRAINS["lava"]
    assert len(t.hqs(0)) == 1 and len(t.hqs(1)) == 1
    assert sum(n.kind == "special" for n in t.nodes) == 2 and sum(n.kind == "base" for n in t.nodes) == 11
    assert len(t.edges) == 22 and sorted(r.medals for r in t.regions) == [2, 2, 2, 2, 3, 3]
    assert t.medals == 14 and t.objective == (7, 7)


def test_cursed_cemetery_follows_the_published_map() -> None:
    t = TERRAINS["attic"]
    assert len(t.hqs(0)) == 1 and len(t.hqs(1)) == 1
    assert sum(n.kind == "special" for n in t.nodes) == 4 and sum(n.kind == "base" for n in t.nodes) == 11
    assert len(t.edges) == 28 and sorted(r.medals for r in t.regions) == [1] * 6 + [2] * 4
    assert t.medals == 14 and t.objective == (7, 7)


def test_caribbean_sea_follows_the_published_map() -> None:
    t = TERRAINS["gutter"]
    assert len(t.hqs(0)) == 2 and len(t.hqs(1)) == 1
    assert sum(n.kind == "base" for n in t.nodes) == 12 and not any(n.kind == "special" for n in t.nodes)
    assert len(t.edges) == 20 and sorted(r.medals for r in t.regions) == [1, 1, 2, 2, 2, 3]
    assert t.medals == 11 and t.objective == (5, 5)


def test_station_metal_x_follows_the_published_map() -> None:
    t = TERRAINS["workshop"]
    assert len(t.hqs(0)) == 1 and len(t.hqs(1)) == 1
    assert sum(n.kind == "special" for n in t.nodes) == 3 and sum(n.kind == "base" for n in t.nodes) == 10
    assert len(t.edges) == 28 and [r.medals for r in t.regions] == [1] * 14
    assert t.medals == 14 and t.objective == (7, 7)


def test_battlefield_follows_the_published_map() -> None:
    t = TERRAINS["sandpit"]
    assert len(t.hqs(0)) == 1 and len(t.hqs(1)) == 1
    assert sum(n.kind == "special" for n in t.nodes) == 4 and sum(n.kind == "base" for n in t.nodes) == 10
    assert len(t.edges) == 24 and sorted(r.medals for r in t.regions) == [1] * 4 + [2] * 3 + [3] * 2
    assert t.medals == 16 and t.objective == (8, 8)
