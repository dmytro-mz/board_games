"""Bots: legal moves only, the incremental evaluation, obvious tactics, strength order, the time budget."""

from __future__ import annotations

import importlib.util
import random
import time
from pathlib import Path

import pytest

from sumo.bots import ALL, REGISTRY, RandomBot, SearchBot, make_bot
from sumo.bots.search import Searcher, gen_captures
from sumo.game.board import LAYOUTS
from sumo.game.engine import Game, Move, View, gen_moves, marbles_of
from sumo.runner import play_game

_spec = importlib.util.spec_from_file_location("sumo_engine_tests", Path(__file__).with_name("test_engine.py"))
assert _spec and _spec.loader
_engine_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_engine_tests)
position = _engine_tests.position


def fresh_terms(s: Searcher) -> tuple[list[int], list[int], int]:
    """The evaluation terms counted from scratch for the searcher's current cells."""
    other = Searcher(View(tuple(s.cells), 0, (s.out[0], s.out[1]), 0, 0), None, random.Random(0))
    return other.ring, other.adj, other.hash


def test_incremental_evaluation_matches_a_fresh_count() -> None:
    rng = random.Random(5)
    g = Game("daisy")
    s = Searcher(g.view(), None, rng)
    side = 0
    stack = []
    for _ in range(400):
        moves = gen_moves(s.cells, side)
        if not moves or max(s.out) >= 6:
            break
        mv = rng.choice(moves)
        stack.append((mv, side, s.make(mv, side)))
        side = 1 - side
        assert (s.ring, s.adj, s.hash) == fresh_terms(s)
        assert s.evaluate(0) == -s.evaluate(1)
        if rng.random() < 0.3:
            mv, side, undo = stack.pop()
            s.unmake(mv, side, undo)
            assert (s.ring, s.adj, s.hash) == fresh_terms(s)


def test_capture_generator_finds_exactly_the_captures() -> None:
    rng = random.Random(2)
    g = Game("wide")
    for _ in range(200):
        if g.over:
            break
        for side in (0, 1):
            caps = {(tuple(sorted(marbles_of(m))), m[2]) for m in gen_captures(g.cells, side)}
            ref = {(tuple(sorted(marbles_of(m))), m[2]) for m in gen_moves(g.cells, side) if m[5]}
            assert caps == ref
        moves = g.legal_internal()
        pushes = [m for m in moves if m[4]]
        g.step(g.current, Move.of(rng.choice(pushes if pushes and rng.random() < 0.6 else moves)))


@pytest.mark.parametrize("key", list(ALL))
def test_every_bot_plays_legal_moves(key: str) -> None:
    rng = random.Random(1)
    bot = make_bot(key, 3, budget=0.05)
    for layout in LAYOUTS:
        g = Game(layout)
        for _ in range(6):
            if g.over:
                break
            if g.current == 0:
                move = bot.act(g.view())
                assert move in g.legal_moves()
            else:
                move = rng.choice(g.legal_moves())
            g.step(g.current, move)


def test_registry_is_what_the_lobby_offers() -> None:
    assert list(REGISTRY) == ["rookie", "ozeki", "yokozuna"]
    assert [b.stars for b in REGISTRY.values()] == [1, 3, 5]


@pytest.mark.parametrize("key", ["ozeki", "yokozuna", "d3"])
def test_bot_takes_the_winning_push(key: str) -> None:
    g = position("E6 E7 E8 C4 C5", "E9 D4", out=(0, 5))
    move = make_bot(key, 1, budget=0.3).act(g.view())
    g.step(0, move)
    assert g.result is not None and g.result.winner == 0


@pytest.mark.parametrize("key", ["ozeki", "yokozuna"])
def test_bot_saves_its_last_marble_in_danger(key: str) -> None:
    # White threatens E7-E8 → E9 (the sixth black marble out); Black moves first.
    g = position("E9 C3", "E7 E8", current=0, out=(5, 0))
    move = make_bot(key, 2, budget=0.3).act(g.view())
    g.step(0, move)
    assert not any(m[5] for m in gen_moves(g.cells, 1)), Move.of(gen_moves(g.cells, 1)[0])


def test_strength_order() -> None:
    def score(a: str, b: str, n: int) -> int:
        wins = 0
        for i in range(n):
            bots = [make_bot(a, i), make_bot(b, 100 + i)]
            if i % 2:
                bots.reverse()
            game = play_game(bots, layout="daisy", move_limit=60)
            assert game.result is not None
            w = game.result.winner
            wins += w is not None and (w == 0) == (i % 2 == 0)
        return wins

    assert score("rookie", "random", 4) == 4
    assert score("d2", "rookie", 4) >= 3


def test_time_budget_is_respected() -> None:
    bot = SearchBot(1, budget=0.25)
    started = time.perf_counter()
    bot.act(Game("classic").view())
    assert time.perf_counter() - started < 0.8
    assert bot.last_depth >= 2


def test_random_bot() -> None:
    g = Game()
    assert RandomBot(1).act(g.view()) in g.legal_moves()
