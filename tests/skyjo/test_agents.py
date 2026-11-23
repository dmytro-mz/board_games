from __future__ import annotations

import itertools
import pickle

import pytest

from skyjo.agents import ExpertAgent, make_agent, parse_spec
from skyjo.agents.expert import column_score_pmf
from skyjo.evaluation import run_tournament
from skyjo.game import FLIP_BASE, Phase, RulesConfig
from skyjo.game.cards import HIDDEN, REMOVED, STANDARD_COMPOSITION, VALUES
from skyjo.game.observation import Observation
from skyjo.runner import play_game


def test_parse_spec() -> None:
    assert parse_spec("ev") == ("ev", {})
    assert parse_spec("ev:reveal_bonus=0.5,pair_weight=1") == ("ev", {"reveal_bonus": 0.5, "pair_weight": 1})
    assert parse_spec("ppo:runs/a/policy.npz") == ("ppo", {"path": "runs/a/policy.npz"})


@pytest.mark.parametrize("spec", ["random", "greedy", "ev", "expert"])
@pytest.mark.parametrize("n_players", [2, 4, 8])
def test_agents_play_legal_games(spec: str, n_players: int) -> None:
    agents = [make_agent(spec, seed=i) for i in range(n_players)]
    for seed in range(3):
        result = play_game(agents, RulesConfig(n_players=n_players), seed=seed)
        assert result.winners


def test_agents_are_picklable() -> None:
    for spec in ["random", "greedy", "ev", "expert"]:
        pickle.loads(pickle.dumps(make_agent(spec)))


def test_tournament_is_reproducible_and_rotates_seats() -> None:
    lineup = [make_agent("greedy"), make_agent("random")]
    a = run_tournament(lineup, n_games=10, seed=7, workers=1)
    b = run_tournament(lineup, n_games=10, seed=7, workers=1)
    assert a.to_dict() == b.to_dict()
    assert abs(sum(s.win_rate for s in a.summaries) - 1.0) < 1e-9


def test_heuristics_beat_random() -> None:
    result = run_tournament([make_agent("ev"), make_agent("random")], n_games=20, seed=0, workers=1)
    assert result.by_label()["ev"].win_rate > 0.8


def _obs(boards: tuple[tuple[int, ...], ...], phase: Phase, **kw: object) -> Observation:
    fields: dict[str, object] = {
        "player": 0,
        "n_players": len(boards),
        "phase": phase,
        "boards": boards,
        "discard_top": None,
        "hand": None,
        "deck_size": 100,
        "unknown_counts": tuple(STANDARD_COMPOSITION[v] for v in VALUES),
        "finisher": None,
        "totals": (0,) * len(boards),
        "round_index": 0,
        "turn": 10,
    }
    fields.update(kw)
    return Observation(**fields)  # type: ignore[arg-type]


H = HIDDEN


@pytest.mark.parametrize(
    "col", [(H, H, H), (5, H, H), (5, 5, H), (5, 7, H), (-2, -2, H), (3, 3, 3), (14, 14, 14), (1, 2, 3)]
)
def test_column_score_pmf_matches_enumeration(col: tuple[int, int, int]) -> None:
    probs = [(-2, 0.1), (0, 0.3), (5, 0.4), (7, 0.2)]
    expected: dict[int, float] = {}
    slots = [i for i, s in enumerate(col) if s == HIDDEN]
    for combo in itertools.product(probs, repeat=len(slots)):
        cards = list(col)
        p = 1.0
        for i, (v, pv) in zip(slots, combo, strict=True):
            cards[i] = v
            p *= pv
        score = 0 if cards[0] == REMOVED or cards[0] == cards[1] == cards[2] else sum(cards)
        expected[score] = expected.get(score, 0.0) + p
    got = {k: v for k, v in column_score_pmf(col, probs).items() if abs(v) > 1e-12}
    assert got.keys() == {k for k, v in expected.items() if v > 1e-12}
    assert all(abs(got[k] - expected[k]) < 1e-12 for k in got)


def test_expert_reveals_setup_cards_in_different_columns() -> None:
    agent = ExpertAgent(seed=0)
    board = (4,) + (HIDDEN,) * 11
    for _ in range(50):
        legal = [FLIP_BASE + p for p in range(1, 12)]
        action = agent.act(_obs((board, (HIDDEN,) * 12), Phase.SETUP), legal)
        assert action - FLIP_BASE not in (1, 2)


def test_expert_denies_a_column_completing_discard() -> None:
    # A drawn 9 is normally discarded (+ flip), but the opponent's (9, 9, 1) column would clear
    # with it, so the expert buries it in a face-down slot instead.
    me = (0, 1, 2) + (HIDDEN,) * 9
    opp = (9, 9, 1) + (HIDDEN,) * 9
    legal = list(range(12)) + [FLIP_BASE + p for p in range(3, 12)]
    obs = _obs((me, opp), Phase.PLACE_DRAWN, hand=9, discard_top=4)
    assert ExpertAgent(deny=0.0).act(obs, legal) >= FLIP_BASE
    assert 3 <= ExpertAgent().act(obs, legal) < 12


@pytest.mark.parametrize("n_players", [2, 8])
def test_expert_breaks_last_card_standoffs(n_players: int) -> None:
    # One hidden card left, opponents level: early on the expert prefers a harmless swap,
    # but after a long round it ends it. "Long" is counted in own turns, not table turns.
    me = (HIDDEN, 2, 2, 3, 1, 0, 2, 1, 0, 1, 0, 2)
    opp = (HIDDEN, 1, 2, 3, 1, 0, 2, 1, 0, 2, 0, 2)
    boards = (me,) + (opp,) * (n_players - 1)
    legal = list(range(12))
    early = _obs(boards, Phase.PLACE_DISCARD, hand=3, discard_top=5, turn=20 * n_players)
    late = _obs(boards, Phase.PLACE_DISCARD, hand=3, discard_top=5, turn=60 * n_players)
    assert ExpertAgent().act(early, legal) != 0
    assert ExpertAgent().act(late, legal) == 0
