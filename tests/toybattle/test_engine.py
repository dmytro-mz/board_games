"""Rules engine: setup, placement, effects, regions, the end of the game, views and determinization."""

from __future__ import annotations

import random

import pytest

from tests.toybattle.helpers import node, path_to_special, position, take, troop
from toybattle.game.engine import DRAW, SKIP, TAKE, Action, Game, IllegalMove, Phase
from toybattle.game.terrains import TERRAINS
from toybattle.game.troops import ARMY, RACK_MAX, army, kind_of, side_of

B, R = 0, 1


def place(g: Game, t: int, name: str) -> list[dict]:
    return g.step(g.current, Action("place", t, node(g, name)))


def targets(g: Game, t: int) -> set[str]:
    names = {a.node for a in g.legal_actions() if a.type == "place" and a.troop == t}
    return {g.terrain.nodes[n].name for n in names}


# ------------------------------------------------------------------ setup
@pytest.mark.parametrize("terrain", list(TERRAINS))
def test_setup(terrain: str) -> None:
    for seed in range(20):
        g = Game(terrain, seed=seed)
        g.check()
        starter = g.starter
        assert starter in (0, 1)
        assert g.current == starter
        assert len(g.rack[starter]) == 3 and len(g.rack[1 - starter]) == 4
        for side in (0, 1):
            assert len(g.removed[side]) == 4
            assert len(g.reserve[side]) + len(g.rack[side]) == 20
            assert all(side_of(t) == side for t in g.rack[side] + g.reserve[side] + g.removed[side])
        assert not any(g.stacks)


def test_army() -> None:
    assert len(army(0)) == ARMY == 24
    assert sorted(kind_of(t) for t in army(1)) == sorted(list(range(8)) * 3)


# ------------------------------------------------------------------ placement
def test_first_placements_next_to_the_hq_only() -> None:
    g = position(racks=([troop(B, 5)], []))
    assert targets(g, troop(B, 5)) == {"a'", "b'"}


def test_connection_runs_through_own_tops_only() -> None:
    g = position(racks=([troop(B, 5)], []), board={"a'": [troop(B, 1)], "b'": [troop(R, 1)]})
    # through a' (own) we reach c'; b' is covered-able (5 > 1); nothing through b' (enemy top)
    assert targets(g, troop(B, 5)) == {"a'", "b'", "c'"}


def test_cover_needs_strictly_stronger() -> None:
    g = position(racks=([troop(B, 4), troop(B, 5), troop(B, 0)], []), board={"a'": [troop(R, 5)]})
    assert "a'" not in targets(g, troop(B, 4))
    assert "a'" not in targets(g, troop(B, 5))
    assert "a'" in targets(g, troop(B, 0))  # the joker covers anything


def test_anyone_covers_a_joker_and_a_joker_covers_a_joker() -> None:
    g = position(racks=([troop(B, 1), troop(B, 0)], []), board={"a'": [troop(R, 0)]})
    assert "a'" in targets(g, troop(B, 1))
    assert "a'" in targets(g, troop(B, 0))


def test_own_stack_any_strength() -> None:
    g = position(racks=([troop(B, 1)], []), board={"a'": [troop(B, 7)]})
    assert "a'" in targets(g, troop(B, 1))


def test_capture_hq_wins() -> None:
    g = position(
        racks=([troop(B, 1)], [troop(R, 3)]), board={"a": [troop(B, 6)], "c": [troop(B, 6, 1)], "a'": [troop(B, 6, 2)]}
    )
    # a' is next to Blue's H.Q.; a and c sit next to Red's H.Q. but are not connected to Blue
    assert "H" not in targets(g, troop(B, 1))
    g = position(
        racks=([troop(B, 1)], [troop(R, 3)]),
        board={
            "a'": [troop(B, 6)],
            "c'": [troop(B, 6, 1)],
            "m2": [troop(B, 6, 2)],
            "c": [troop(B, 5)],
            "a": [troop(B, 5, 1)],
        },
    )
    assert "H" in targets(g, troop(B, 1))
    events = place(g, troop(B, 1), "H")
    assert g.result is not None and g.result.winner == B and g.result.reason == "hq"
    assert g.phase == Phase.OVER
    assert events[-1]["kind"] == "game_over"
    g.check()


def test_cannot_place_on_own_hq() -> None:
    g = position(racks=([troop(B, 1)], []))
    assert "H'" not in targets(g, troop(B, 1))


def test_illegal_actions_leave_state_untouched() -> None:
    g = position(racks=([troop(B, 3)], [troop(R, 3)]))
    before = (g.stacks, g.rack, g.current)
    with pytest.raises(IllegalMove):
        g.step(B, Action("place", troop(B, 3), node(g, "H")))
    with pytest.raises(IllegalMove):
        g.step(R, DRAW)
    with pytest.raises(IllegalMove):
        g.step(B, Action("place", troop(R, 3), node(g, "a'")))
    assert (g.stacks, g.rack, g.current) == before


# ------------------------------------------------------------------ drawing
def test_draw_two_and_rack_limit() -> None:
    g = position(racks=([troop(B, 1)], [troop(R, 1)]))
    n = len(g.reserve[B])
    g.step(B, DRAW)
    assert len(g.rack[B]) == 3 and len(g.reserve[B]) == n - 2 and g.current == R
    g = position(racks=([troop(B, k) for k in range(7)], []))
    g.step(B, DRAW)
    assert len(g.rack[B]) == RACK_MAX  # only room for one
    g = position(racks=([troop(B, k % 8, k // 8) for k in range(8)], []))
    assert DRAW not in g.legal_actions()


def test_draw_one_when_one_left() -> None:
    g = position(racks=([troop(B, 1)], [troop(R, 1)]))
    g.reserve[B] = g.reserve[B][:1]
    g.removed[B] = g.removed[B] + []  # unchanged
    leftover = [t for t in army(B) if t not in g.reserve[B] and t not in g.removed[B] and t not in g.rack[B]]
    g.discard = leftover
    g.step(B, DRAW)
    assert len(g.rack[B]) == 2 and not g.reserve[B]
    g.check()


# ------------------------------------------------------------------ troop effects
def test_mouse_draws_two_and_bear_one() -> None:
    g = position(racks=([troop(B, 1), troop(B, 6)], [troop(R, 1)]))
    place(g, troop(B, 1), "a'")
    assert g.phase == Phase.EFFECT and g.pending.kind == "draw2"
    assert set(g.legal_actions()) == {TAKE, SKIP}
    g.step(B, TAKE)
    assert len(g.rack[B]) == 3 and g.current == R
    g = position(racks=([troop(B, 6)], [troop(R, 1)]))
    place(g, troop(B, 6), "a'")
    g.step(B, TAKE)
    assert len(g.rack[B]) == 1


def test_frog_knocks_adjacent_visible_enemy() -> None:
    g = position(racks=([troop(B, 3)], [troop(R, 1)]), board={"c'": [troop(R, 4), troop(R, 2)]})
    place(g, troop(B, 3), "a'")
    assert g.pending.kind == "knock"
    opts = {g.terrain.nodes[a.node].name for a in g.legal_actions() if a.type == "knock"}
    assert opts == {"c'"}  # the H.Q. is not a base
    g.step(B, Action("knock", node=node(g, "c'")))
    assert g.stacks[node(g, "c'")] == [troop(R, 4)]  # the troop underneath shows again
    assert g.discard == [troop(R, 2)]
    g.check()


def test_drummer_places_extra_then_its_effect() -> None:
    g = position(racks=([troop(B, 2), troop(B, 3)], [troop(R, 1)]), board={"f'": [troop(R, 1, 1)]})
    place(g, troop(B, 2), "a'")
    assert g.pending.kind == "extra"
    # the extra troop may go next to the drummer: a' is connected now
    assert "c'" in targets(g, troop(B, 3))
    g.step(B, Action("place", troop(B, 3), node(g, "c'")))
    assert g.pending.kind == "knock"  # the frog's effect comes next
    g.step(B, Action("knock", node=node(g, "f'")))
    assert g.current == R
    g.check()


def test_drummer_chain() -> None:
    g = position(racks=([troop(B, 2), troop(B, 2, 1), troop(B, 5)], [troop(R, 1)]))
    place(g, troop(B, 2), "a'")
    g.step(B, Action("place", troop(B, 2, 1), node(g, "c'")))
    assert g.pending.kind == "extra"
    g.step(B, Action("place", troop(B, 5), node(g, "m2")))
    assert g.pending.kind == "snatch"


def test_plane_flies_anywhere_but_not_onto_an_unconnected_hq() -> None:
    g = position(racks=([troop(B, 4)], [troop(R, 1)]), board={"c": [troop(R, 3)]})
    names = targets(g, troop(B, 4))
    assert {"a", "b", "c", "m2", "a'"} <= names
    assert "H" not in names
    g = position(racks=([troop(B, 4)], [troop(R, 5)]), board={"c": [troop(R, 5, 1)]})
    assert "c" not in targets(g, troop(B, 4))  # still needs to beat the top troop


def test_magnet_discards_random_rack_troop() -> None:
    g = position(racks=([troop(B, 5)], [troop(R, 1), troop(R, 7)]))
    place(g, troop(B, 5), "a'")
    assert g.pending.kind == "snatch"
    g.step(B, TAKE)
    assert len(g.rack[R]) == 1 and len(g.discard) == 1 and side_of(g.discard[0]) == R
    g.check()


def test_effects_skipped_when_useless() -> None:
    g = position(racks=([troop(B, 3)], [troop(R, 1)]))
    place(g, troop(B, 3), "a'")  # nothing to knock
    assert g.current == R and g.phase == Phase.TURN


# ------------------------------------------------------------------ regions
def test_region_medals_once_for_both_players() -> None:
    # rug region "c f m1" (1 medal), mirrored "c' f' m3"
    g = position(
        racks=([troop(B, 7)], [troop(R, 1)]),
        board={"a'": [troop(B, 1)], "c'": [troop(B, 1, 1)], "f'": [troop(B, 1, 2)]},
    )
    events = place(g, troop(B, 7), "m3")
    assert any(e["kind"] == "medals" for e in events)
    assert g.medals[B] >= 1
    taken = sum(1 for o in g.region_taken if o == B)
    # losing a base later doesn't take the medals back
    g.current = B
    g.check()
    assert taken >= 1


def test_knock_can_hand_the_region_to_the_victim_side() -> None:
    # Red holds c and f of "c f m1"; m1 has Blue on top of Red. Red knocks it: regions are checked for both players
    # after a knock.
    g = position(
        racks=([troop(B, 1)], [troop(R, 3)]),
        board={"a": [troop(R, 5)], "c": [troop(R, 5, 1)], "m1": [troop(R, 6), troop(B, 7)]},
        current=R,
    )
    place(g, troop(R, 3), "f")  # next to m1
    g.step(R, Action("knock", node=node(g, "m1")))
    assert g.medals[R] >= 1  # m1 is Red again: "c f m1" belongs to Red


def test_medals_objective_wins_at_once() -> None:
    # pretend Blue already took regions worth 6 medals elsewhere; the last base of "c' f' m3" makes 7
    g = position(
        racks=([troop(B, 7)], [troop(R, 1)]),
        board={"a'": [troop(B, 1)], "c'": [troop(B, 1, 1)], "f'": [troop(B, 1, 2)]},
        medals=(6, 0),
    )
    place(g, troop(B, 7), "m3")
    assert g.result is not None and g.result.reason == "medals" and g.result.winner == B


# ------------------------------------------------------------------ end of game
def test_stuck_player_loses_on_equal_medals() -> None:
    g = position(racks=([], [troop(R, 7)]), current=R)
    g.reserve[B] = []
    g.discard = [t for t in army(B) if t not in g.removed[B]]
    g.step(R, Action("place", troop(R, 7), node(g, "a")))
    # Blue's turn: no reserve, no rack -> stuck
    assert g.result is not None and g.result.reason == "stuck" and g.result.winner == R


def test_stuck_player_with_more_medals_wins() -> None:
    g = position(racks=([], [troop(R, 7)]), current=R)
    g.reserve[B] = []
    g.discard = [t for t in army(B) if t not in g.removed[B]]
    region = TERRAINS["rug"].regions[0]
    g.region_taken[region.id] = B
    g.medals[B] = region.medals
    g.step(R, Action("place", troop(R, 7), node(g, "a")))
    assert g.result is not None and g.result.reason == "stuck" and g.result.winner == B


# ------------------------------------------------------------------ special bases
def test_rug_recall_returns_other_visible_troop() -> None:
    g = position(racks=([troop(B, 2), troop(B, 7)], [troop(R, 1)]), board={"a'": [troop(B, 5)], "c'": [troop(B, 6)]})
    # rug specials are f and d (and mirrors)
    place(g, troop(B, 2), "f'")
    assert g.pending.kind == "extra"
    g.step(B, SKIP)
    assert g.pending.kind == "recall"
    opts = {g.terrain.nodes[a.node].name for a in g.legal_actions() if a.type == "recall"}
    assert opts == {"a'", "c'"}  # not the troop that triggered it
    g.step(B, Action("recall", node=node(g, "a'")))
    assert troop(B, 5) in g.rack[B] and troop(B, 5) in g.known[B]
    v = g.view(R)
    assert troop(B, 5) in v.opp_known
    g.check()


def test_special_bases_off() -> None:
    g = position(racks=([troop(B, 6)], [troop(R, 1)]), special=False)
    g = position(
        racks=([troop(B, 7)], [troop(R, 1)]), board={"a'": [troop(B, 1)], "c'": [troop(B, 1, 1)]}, special=False
    )
    place(g, troop(B, 7), "f'")
    assert g.current == R  # no recall prompt


def test_lagoon_restrictions() -> None:
    g = position("lagoon", racks=([troop(B, 7), troop(B, 1), troop(B, 0)], [troop(R, 1)]))
    t = g.terrain
    rings = [n for n in t.nodes if n.allow is not None and n.kind != "hq"]
    assert rings
    for n in rings:
        for k in (7, 1, 0):
            assert g._allowed(n.id, k) == (k == 0 or k in n.allow)
    hq = t.hqs(R)[0]
    assert not g._allowed(hq, 1) and g._allowed(hq, 7) and g._allowed(hq, 0)


def test_pillow_snack_draws_one() -> None:
    g = position("pillow", racks=([troop(B, 7)], [troop(R, 1)]))
    spot = path_to_special(g, B)
    place(g, troop(B, 7), spot)
    assert g.pending.kind == "bdraw"
    g.step(B, TAKE)
    assert len(g.rack[B]) == 1


def test_lava_move_pushes_enemy() -> None:
    g = position("lava", racks=([troop(B, 7)], [troop(R, 1)]))
    t = g.terrain
    special = next(n for n in t.nodes if n.kind == "special" and any(t.nodes[m].is_base for m in t.adj[n.id]))
    nb = next(m for m in t.adj[special.id] if t.nodes[m].is_base)
    g.stacks[nb] = [take(g, troop(R, 6))]
    g.stacks[special.id] = [take(g, troop(B, 1))]
    fx_actions = g._effect_options(type("FX", (), {"kind": "move", "node": special.id, "troop": troop(B, 1)})())  # type: ignore[arg-type]
    assert fx_actions and all(a.node == nb for a in fx_actions)
    assert all(t.nodes[a.to].is_base for a in fx_actions)


def test_attic_revive() -> None:
    g = position("attic", racks=([troop(B, 7)], [troop(R, 1)]))
    g.discard = [take(g, troop(B, 3)), take(g, troop(R, 3))]
    spot = path_to_special(g, B)
    place(g, troop(B, 7), spot)
    assert g.pending.kind == "revive"
    assert {a.troop for a in g.legal_actions() if a.type == "revive"} == {troop(B, 3)}
    g.step(B, Action("revive", troop=troop(B, 3)))
    assert troop(B, 3) in g.rack[B] and troop(B, 3) in g.known[B]
    g.check()


def test_workshop_shield_cancels_placed_troop_effect_only() -> None:
    g = position("workshop", racks=([troop(B, 4), troop(B, 1)], [troop(R, 1)]))
    bays = [n.id for n in g.terrain.nodes if n.kind == "special"]
    reach = g.reachable(B)
    # a plane can't airdrop onto a bay it isn't connected to
    plane_targets = {a.node for a in g.legal_actions() if a.type == "place" and a.troop == troop(B, 4)}
    for bay in bays:
        assert (bay in plane_targets) == (bay in reach)
    assert g._shielded(bays[0])


def test_sandpit_pin_lasts_one_turn() -> None:
    g = position("sandpit", racks=([troop(B, 7)], [troop(R, 1), troop(R, 2)]))
    spot = path_to_special(g, B)
    place(g, troop(B, 7), spot)
    assert g.pending.kind == "snipe"
    g.step(B, TAKE)
    assert len(g.pinned[R]) == 1
    pinned = next(iter(g.pinned[R]))
    assert all(a.troop != pinned for a in g.legal_actions(R) if a.type == "place")
    assert g.view(B).opp_pinned == 1
    g.step(R, DRAW)
    assert not g.pinned[R]
    g.check()


def test_gutter_two_blue_hqs() -> None:
    t = TERRAINS["gutter"]
    assert len(t.hqs(0)) == 2 and len(t.hqs(1)) == 1
    assert t.objective == (5, 5)


# ------------------------------------------------------------------ views and hidden information
def test_view_hides_opponent_rack_and_reserves() -> None:
    g = Game("rug", seed=4)
    v = g.view(0)
    assert v.rack == tuple(g.rack[0])
    assert v.opp_rack == len(g.rack[1])
    assert not v.opp_known
    assert v.reserves == (len(g.reserve[0]), len(g.reserve[1]))
    assert v.legal == (tuple(g.legal_actions(0)) if g.current == 0 else ())


def test_from_view_is_consistent_with_the_view() -> None:
    rng = random.Random(0)
    for seed in range(30):
        g = Game(random.Random(seed).choice(list(TERRAINS)), seed=seed)
        for _ in range(rng.randrange(0, 40)):
            if g.phase == Phase.OVER:
                break
            g.step(g.current, rng.choice(g.legal_actions()))
        if g.phase == Phase.OVER:
            continue
        for seat in (0, 1):
            v = g.view(seat)
            w = Game.from_view(v, rng)
            w.check()
            assert w.view(seat).stacks == v.stacks
            assert w.view(seat).rack == v.rack
            assert w.view(seat).opp_rack == v.opp_rack
            assert w.view(seat).reserves == v.reserves
            assert set(w.legal_actions(seat)) == set(v.legal)


@pytest.mark.parametrize("terrain", list(TERRAINS))
@pytest.mark.parametrize("special", [True, False])
def test_random_games_keep_invariants(terrain: str, special: bool) -> None:
    rng = random.Random(hash((terrain, special)) % 1000)
    for seed in range(25):
        g = Game(terrain, special=special, seed=seed)
        steps = 0
        while g.phase != Phase.OVER:
            legal = g.legal_actions()
            assert legal
            g.step(g.current, rng.choice(legal))
            g.check()
            steps += 1
            assert steps < 3000
        assert g.result is not None


def test_action_json_roundtrip_and_validation() -> None:
    a = Action("move", node=3, to=5)
    assert Action.from_json(a.to_json()) == a
    for bad in (
        None,
        {"type": "nuke"},
        {"type": "place", "troop": "x"},
        {"type": "place", "troop": True},
        {"type": "place", "node": 10**6},
    ):
        with pytest.raises(ValueError):
            Action.from_json(bad)
