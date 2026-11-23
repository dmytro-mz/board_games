from __future__ import annotations

import pytest
from pandemic_helpers import cubes, hand, new_game, top_infection

from pandemic.bots import REGISTRY, make_bot
from pandemic.bots.planner import Planner, danger, evaluate
from pandemic.game.actions import (
    Continue,
    Cure,
    Discard,
    Forecast,
    ForecastOrder,
    OneQuietNight,
    ResilientPopulation,
    Treat,
)
from pandemic.game.engine import Game, RulesConfig, Step
from pandemic.game.model import Color, Role
from pandemic.runner import play_game


def table(*roles: Role) -> Game:
    game = new_game(*roles)
    game.current = 0
    return game


@pytest.mark.parametrize("key", list(REGISTRY))
@pytest.mark.parametrize("n", [2, 4])
def test_bots_finish_games(key: str, n: int) -> None:
    game = play_game([make_bot(key, i) for i in range(n)], seed=n, rules=RulesConfig(epidemics=5))
    assert game.result is not None
    assert game.card_count() == 53 + 5


def test_bots_play_from_closed_views() -> None:
    bots = [make_bot("expert", i) for i in range(3)]
    game = play_game(bots, seed=3, rules=RulesConfig(epidemics=4), open_hands=False)
    assert game.result is not None


def test_expert_beats_rookie() -> None:
    def cures(key: str) -> int:
        total = 0
        for seed in range(4):
            game = play_game([make_bot(key, seed * 10 + i) for i in range(2)], seed=seed, rules=RulesConfig(4))
            total += sum(v != "none" for v in game.cures.values())
        return total

    assert cures("expert") > cures("rookie")


def test_cures_when_it_can() -> None:
    game = table(Role.MEDIC, Role.DISPATCHER)
    hand(game, 0, "sf", "chi", "mon", "ny", "was")
    action = Planner(1).act(game.view(0))
    assert isinstance(action, Cure)


def test_treats_a_city_about_to_outbreak() -> None:
    game = table(Role.SCIENTIST, Role.DISPATCHER)
    hand(game, 0, "lim", "kha")
    cubes(game, "atl", Color.BLUE, 3)
    assert Planner(1).act(game.view(0)) == Treat(Color.BLUE)


def test_discards_the_least_useful_card() -> None:
    game = table(Role.MEDIC, Role.DISPATCHER)
    hand(game, 0, "sf", "chi", "mon", "ny", "lim", "kha", "tok", "was")
    hand(game, 1)
    assert game.over_limit() == 0
    action = Planner(1).act(game.view(0))
    assert isinstance(action, Discard)
    assert action.card not in ("sf", "chi", "mon", "ny", "was")


def test_forecast_puts_dangerous_cities_last() -> None:
    game = table(Role.SCIENTIST, Role.DISPATCHER)
    hand(game, 0, "forecast")
    cubes(game, "par", Color.BLUE, 3)
    top_infection(game, "par")
    game.play(0, Forecast())
    action = Planner(1).act(game.view(0))
    assert isinstance(action, ForecastOrder)
    assert action.order[-1] == "par"
    assert danger(game, "par") > danger(game, action.order[0])


def test_resilient_population_on_the_epidemic_city() -> None:
    game = table(Role.SCIENTIST, Role.DISPATCHER)
    hand(game, 0)
    hand(game, 1, "resilient")
    game.step = Step.EPIDEMIC
    game.infection_discard = ["par", "lim"]
    cubes(game, "par", Color.BLUE, 3)
    cubes(game, "lim", Color.YELLOW, 1)
    bot = Planner(2)
    assert bot.react(game.view(1)) == ResilientPopulation("par")
    assert Planner(1).act(game.view(0)) == Continue()


def test_quiet_night_when_an_outbreak_is_coming() -> None:
    game = table(Role.SCIENTIST, Role.DISPATCHER)
    hand(game, 0)
    hand(game, 1, "quiet")
    game.step = Step.INFECT
    for city in ("par", "lon"):
        cubes(game, city, Color.BLUE, 3)
    top_infection(game, "par", "lon")
    game.known_top = ["par", "lon"]
    assert Planner(2).react(game.view(1)) == OneQuietNight()


def test_evaluate_prefers_cures_and_fewer_cubes() -> None:
    game = table(Role.SCIENTIST, Role.DISPATCHER)
    base = evaluate(game)
    worse = game.clone()
    cubes(worse, "par", Color.BLUE, 3)
    better = game.clone()
    better.cures[Color.RED] = "cured"
    assert evaluate(worse) < base < evaluate(better)


def test_bot_actions_are_always_legal() -> None:
    game = Game(3, seed=11, rules=RulesConfig(epidemics=6))
    bots = [make_bot("rookie", i) for i in range(3)]
    for _ in range(400):
        if game.result is not None:
            break
        seat = game.waiting_for()
        assert seat is not None
        game.play(seat, bots[seat].act(game.view(seat)))
