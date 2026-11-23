from __future__ import annotations

from phase10_helpers import rig

from phase10.bots import REGISTRY, make_bot
from phase10.bots.solver import evaluate, lay_down
from phase10.game.actions import Discard, DrawDeck, DrawDiscard, Hit, LayDown
from phase10.game.engine import Game, RulesConfig, Step
from phase10.game.model import PHASES
from phase10.runner import play_game


def test_every_bot_finishes_games():
    for seed in range(3):
        for n in (2, 4, 6):
            keys = [list(REGISTRY)[i % len(REGISTRY)] for i in range(n)]
            bots = [make_bot(k, seed * 10 + i) for i, k in enumerate(keys)]
            result = play_game(bots, seed=seed, rules=RulesConfig(last_phase=4)).result
            assert result is not None and result.winners
            assert all(result.scores[w] == min(result.scores[f] for f in result.finishers) for w in result.winners)


def test_a_full_ten_phase_game():
    bots = [make_bot("pro", 1), make_bot("regular", 2), make_bot("rookie", 3)]
    game = play_game(bots, seed=42)
    assert game.result is not None and game.result.winners and game.card_count() == 108


def test_solver_counts_missing_cards():
    game = Game(2, seed=1)
    hand = rig(game, 0, "r7 b7 g7 y9 r9 r1 b2 g3 y4 r5")
    assert evaluate(hand, PHASES[0]).deficit == 1  # one more 9 (or a wild)
    hand = rig(game, 0, "r7 b7 g7 y9 r9 w r1 b2 g3 y4")
    assert evaluate(hand, PHASES[0]).deficit == 0
    plan = lay_down(hand, PHASES[0])
    assert plan is not None and len(plan.groups) == 2
    assert lay_down(rig(game, 0, "r7 b7 g7 y9 r9 r1 b2 g3 y4 r5"), PHASES[0]) is None


def test_two_sets_of_the_same_number():
    game = Game(2, seed=2)
    hand = rig(game, 0, "r7 b7 g7 y7 r7 b7 r1 b2 g3 y4")
    plan = lay_down(hand, PHASES[0])
    assert plan is not None
    assert all(len(g.cards) >= 3 for g in plan.groups)


def test_bot_moves_are_always_legal():
    for key in REGISTRY:
        game = Game(3, seed=7)
        bot = make_bot(key, 1)
        others = [make_bot("regular", 2 + i) for i in range(3)]
        for _ in range(3000):
            if game.step == Step.GAME_OVER:
                break
            if game.step == Step.HAND_OVER:
                game.next_hand()
                continue
            seat = game.current
            action = (bot if seat == 0 else others[seat]).act(game.view(seat))
            if game.step == Step.DRAW:
                assert isinstance(action, DrawDeck | DrawDiscard)
            else:
                assert isinstance(action, LayDown | Hit | Discard)
            game.play(seat, action)
        assert game.card_count() == 108


def test_pro_bot_skips_the_player_about_to_go_out():
    game = Game(3, seed=3)
    seat = game.current
    rig(game, seat, "s r1 b5 g9 y12 r3 b4 g6 y8 r10")
    danger = (seat + 2) % 3
    game.laid[danger] = True
    rig(game, danger, "r2")
    game.play(seat, DrawDeck())
    action = make_bot("pro", 1).act(game.view(seat))
    assert isinstance(action, Discard) and action.target == danger
