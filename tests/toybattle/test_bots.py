"""Bots see only their own `View`, answer legally, take obvious wins, parry obvious losses, beat weaker play."""

from __future__ import annotations

import pytest

from tests.toybattle.helpers import node, position, troop
from toybattle.bots import REGISTRY, GeneralBot, GreedyBot, RandomBot, make_bot
from toybattle.bots.evaluate import Evaluator, can_parry, win_nodes
from toybattle.game.engine import Action, Game, Phase, View
from toybattle.game.terrains import TERRAINS
from toybattle.runner import play_game

B, R = 0, 1


def fast(seed: int = 0) -> GeneralBot:
    return GeneralBot(seed, budget=None, worlds=2, top=6, beams=(4,))


def test_registry_offers_one_strong_bot() -> None:
    assert list(REGISTRY) == ["general"]
    assert REGISTRY["general"].stars == 5
    assert isinstance(make_bot("general", 1), GeneralBot)
    assert isinstance(make_bot("g:w2:t5:b3-2", 1), GeneralBot)


@pytest.mark.parametrize("terrain", list(TERRAINS))
def test_general_plays_legal_games(terrain: str) -> None:
    game = play_game([fast(1), RandomBot(2)], terrain=terrain, seed=3)
    assert game.result is not None
    game.check()


def test_bot_only_gets_a_view() -> None:
    seen: list[object] = []

    class Spy(GeneralBot):
        def act(self, view: View) -> Action:
            seen.append(view)
            return super().act(view)

    play_game([Spy(0, budget=None, worlds=1, top=4, beams=(3,)), RandomBot(1)], seed=2)
    assert seen and all(isinstance(v, View) for v in seen)


def test_determinized_worlds_never_use_the_real_hidden_troops() -> None:
    """The bot's worlds are dealt from what its view allows: two games that differ only in hidden troops give the
    same decision."""
    g1 = position(racks=([troop(B, 5), troop(B, 6)], [troop(R, 7), troop(R, 7, 1)]), board={"a": [troop(R, 3)]})
    g2 = position(racks=([troop(B, 5), troop(B, 6)], [troop(R, 1), troop(R, 2)]), board={"a": [troop(R, 3)]})
    v1, v2 = g1.view(B), g2.view(B)
    assert v1.legal == v2.legal and v1.opp_rack == v2.opp_rack
    a1 = GeneralBot(7, budget=None, worlds=3).act(v1)
    a2 = GeneralBot(7, budget=None, worlds=3).act(v2)
    assert a1 == a2


def test_takes_the_hq_when_it_can() -> None:
    g = position(
        racks=([troop(B, 1), troop(B, 6)], [troop(R, 7)]),
        board={
            "a'": [troop(B, 6, 1)],
            "c'": [troop(B, 6, 2)],
            "m2": [troop(B, 5)],
            "c": [troop(B, 5, 1)],
            "a": [troop(B, 5, 2)],
        },
    )
    for bot in (fast(), GreedyBot(0)):
        a = bot.act(g.view(B))
        assert a.type == "place" and g.terrain.nodes[a.node].kind == "hq"


def test_parries_a_threat_on_its_hq() -> None:
    # Red sits on a' (next to Blue's H.Q.), connected to its own H.Q. through c', m2, c and a.
    g = position(
        racks=([troop(B, 7), troop(B, 1)], [troop(R, 3), troop(R, 4)]),
        board={
            "a": [troop(R, 2)],
            "c": [troop(R, 2, 1)],
            "m2": [troop(R, 2, 2)],
            "c'": [troop(R, 1)],
            "a'": [troop(R, 1, 1)],
        },
    )
    assert win_nodes(g, R)  # Red threatens the Blue H.Q.
    assert can_parry(g, B, R)
    a = fast().act(g.view(B))
    g.step(B, a)
    while g.phase == Phase.EFFECT and g.current == B:
        g.step(B, fast().act(g.view(B)))
    assert not win_nodes(g, R), a


def test_evaluator_is_antisymmetric() -> None:
    ev = Evaluator()
    for seed in range(5):
        g = Game("rug", seed=seed)
        for _ in range(12):
            if g.phase == Phase.OVER:
                break
            g.step(g.current, g.legal_actions()[seed % len(g.legal_actions())])
        if g.phase == Phase.OVER:
            continue
        assert ev(g, 0) == pytest.approx(-ev(g, 1))


def test_general_beats_random() -> None:
    """Strength against stronger opponents is measured with `bg toybattle eval` (too slow for unit tests)."""
    wins = 0
    for seed in range(8):
        swap = seed % 2
        bots = [RandomBot(seed), fast(seed)] if swap else [fast(seed), RandomBot(seed)]
        g = play_game(bots, terrain=list(TERRAINS)[seed], seed=seed)
        wins += g.result is not None and g.result.winner == (1 if swap else 0)
    assert wins == 8


def test_time_budget_is_respected() -> None:
    import time

    g = Game("attic", seed=1)
    bot = GeneralBot(0, budget=0.3)
    for _ in range(6):
        if g.phase == Phase.OVER:
            break
        t = time.perf_counter()
        a = bot.act(g.view(g.current))
        assert time.perf_counter() - t < 2.0
        g.step(g.current, a)


def test_node_helper() -> None:
    g = position()
    assert g.terrain.nodes[node(g, "H")].kind == "hq"
