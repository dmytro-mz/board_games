from __future__ import annotations

import random

import pytest

from skyjo.game import DRAW_DECK, FLIP_BASE, TAKE_DISCARD, Game, IllegalActionError, Phase, Round, RulesConfig
from skyjo.game.board import FACE_UP, GONE, Board
from skyjo.game.cards import HIDDEN, REMOVED, STANDARD_COMPOSITION, build_deck


def _round(n_players: int = 2, seed: int = 0, **rules: object) -> Round:
    return Round(RulesConfig(n_players=n_players, **rules), random.Random(seed))  # type: ignore[arg-type]


def _finish_setup(rnd: Round) -> None:
    while rnd.phase == Phase.SETUP:
        rnd.step(rnd.legal_actions()[0])


def test_deck_composition() -> None:
    deck = build_deck()
    assert len(deck) == 150
    assert sum(STANDARD_COMPOSITION.values()) == 150
    assert deck.count(-2) == 5 and deck.count(0) == 15 and deck.count(12) == 10


def test_deal_conserves_cards() -> None:
    rnd = _round(4)
    on_boards = sum(len(b.values) for b in rnd.boards)
    assert on_boards == 48
    assert on_boards + len(rnd.deck) + len(rnd.discard) == 150


def test_setup_flips_then_highest_sum_starts() -> None:
    rnd = _round(3, seed=5)
    assert rnd.phase == Phase.SETUP
    _finish_setup(rnd)
    sums = [b.visible_score() for b in rnd.boards]
    assert all(sum(s == FACE_UP for s in b.status) == 2 for b in rnd.boards)
    assert rnd.current == sums.index(max(sums))
    assert rnd.phase == Phase.CHOOSE_SOURCE


def test_take_discard_must_replace() -> None:
    rnd = _round()
    _finish_setup(rnd)
    top = rnd.discard[-1]
    rnd.step(TAKE_DISCARD)
    assert rnd.phase == Phase.PLACE_DISCARD
    assert all(a < FLIP_BASE for a in rnd.legal_actions())
    player = rnd.current
    old = rnd.boards[player].values[0]
    rnd.step(0)
    assert rnd.boards[player].values[0] == top
    assert rnd.discard[-1] == old or rnd.boards[player].status[0] == GONE


def test_draw_then_discard_and_flip() -> None:
    rnd = _round()
    _finish_setup(rnd)
    player = rnd.current
    rnd.step(DRAW_DECK)
    drawn = rnd.hand
    hidden = rnd.boards[player].hidden_positions()[0]
    rnd.step(FLIP_BASE + hidden)
    assert rnd.discard[-1] == drawn or rnd.boards[player].status[hidden] == GONE
    assert rnd.boards[player].status[hidden] in (FACE_UP, GONE)
    assert rnd.current != player


def test_illegal_action_rejected() -> None:
    rnd = _round()
    _finish_setup(rnd)
    with pytest.raises(IllegalActionError):
        rnd.step(0)


def test_column_clear_on_replace() -> None:
    rnd = _round(setup_flips=0)
    board = rnd.boards[rnd.current]
    board.values[0:3] = [7, 7, 3]
    board.status[0:2] = [FACE_UP, FACE_UP]
    rnd.discard.append(7)
    rnd._discard_counts[7 + 2] += 1
    rnd.step(TAKE_DISCARD)
    rnd.step(2)
    assert board.status[0:3] == [GONE, GONE, GONE]
    assert board.view()[0:3] == (REMOVED, REMOVED, REMOVED)
    assert rnd.discard[-4:] == [3, 7, 7, 7]  # swapped card first, triplet on top


def test_board_view_hides_cards() -> None:
    b = Board(list(range(12)))
    b.reveal(4)
    view = b.view()
    assert view[4] == 4 and view.count(HIDDEN) == 11


def _scored(finisher: list[int], other: list[int], **rules: object) -> tuple[int, ...]:
    rnd = _round(setup_flips=0, **rules)
    rnd.boards = [Board(finisher), Board(other)]
    rnd.finisher = 0
    rnd._finish()
    assert rnd.result is not None
    return rnd.result.scores


# Column-major boards built from (a, b, c) repeated: no column is ever three-of-a-kind.
LOW = [0, 1, 2] * 4  # 12
MID = [1, 2, 3] * 4  # 24


def test_finisher_doubled_when_beaten() -> None:
    assert _scored(MID, LOW) == (48, 12)


def test_finisher_doubled_on_tie() -> None:
    assert _scored(MID, MID) == (48, 24)
    assert _scored(MID, MID, double_on_tie=False) == (24, 24)


def test_finisher_not_doubled_when_strictly_lowest() -> None:
    assert _scored(LOW, MID) == (12, 24)


def test_non_positive_finisher_score_never_doubled() -> None:
    neg = [-2, -1, 0] * 4  # -12
    assert _scored(neg, [-2, -2, -1] * 4) == (-12, -20)


def test_full_turn_cycle_ends_round_after_final_turns() -> None:
    rnd = _round(setup_flips=0)
    rnd.current = 0
    rnd.boards[0].status = [FACE_UP] * 11 + [0]
    rnd.step(DRAW_DECK)
    rnd.step(FLIP_BASE + 11)
    assert rnd.finisher == 0 and not rnd.is_over
    rnd.step(DRAW_DECK)
    rnd.step(0)
    assert rnd.is_over


def test_final_reveal_clears_columns() -> None:
    rnd = _round(setup_flips=0)
    b = rnd.boards[0]
    b.values[0:3] = [9, 9, 9]
    rnd._finish()
    assert b.status[0:3] == [GONE, GONE, GONE]


@pytest.mark.parametrize("n_players", [2, 3, 4, 6, 8])
def test_random_games_terminate_and_conserve_cards(n_players: int) -> None:
    rng = random.Random(n_players)
    for seed in range(20):
        game = Game(RulesConfig(n_players=n_players), seed=seed)
        while not game.is_over:
            rnd = game.round
            on_table = sum(sum(s != GONE for s in b.status) for b in rnd.boards)
            held = int(rnd.hand is not None)
            # removed columns live on the discard pile
            assert on_table + len(rnd.deck) + len(rnd.discard) + held == 150
            assert sum(rnd._discard_counts) == len(rnd.discard)
            game.step(rng.choice(game.legal_actions()))
        res = game.result
        assert res is not None
        assert max(res.totals) >= 100 or len(res.rounds) >= game.rules.max_rounds
        assert min(res.totals) == res.totals[res.winners[0]]


def test_unknown_counts_are_consistent() -> None:
    game = Game(RulesConfig(n_players=3), seed=1)
    rng = random.Random(0)
    for _ in range(200):
        if game.is_over:
            break
        obs = game.observe(game.current_player)
        assert all(c >= 0 for c in obs.unknown_counts)
        visible_cards = sum(1 for b in obs.boards for v in b if v <= 12)
        held = int(obs.hand is not None)
        assert sum(obs.unknown_counts) == 150 - visible_cards - len(game.round.discard) - held
        game.step(rng.choice(game.legal_actions()))


def test_next_round_starts_with_finisher() -> None:
    game = Game(RulesConfig(n_players=2), seed=3)
    rng = random.Random(3)
    while not game.rounds:
        game.step(rng.choice(game.legal_actions()))
    finisher = game.rounds[0].finisher
    if not game.is_over and finisher is not None:
        while game.phase == Phase.SETUP:
            game.step(game.legal_actions()[0])
        assert game.current_player == finisher
