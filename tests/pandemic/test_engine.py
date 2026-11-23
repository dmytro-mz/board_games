from __future__ import annotations

import random

import pytest
from pandemic_helpers import cubes, hand, new_game, top_infection, top_player

from pandemic.game import actions as A
from pandemic.game.actions import (
    Airlift,
    Build,
    CharterFlight,
    Continue,
    Cure,
    DirectFlight,
    Discard,
    Dispatch,
    DrawCards,
    Drive,
    Forecast,
    ForecastOrder,
    Give,
    GovernmentGrant,
    OneQuietNight,
    OpsFlight,
    Pass,
    ResilientPopulation,
    ShuttleFlight,
    Take,
    TakeEvent,
    Treat,
)
from pandemic.game.engine import Game, IllegalMove, RulesConfig, Step
from pandemic.game.model import CITIES, COLORS, CUBES_PER_COLOR, EPIDEMIC, EVENTS, Role

M, S, R, Q = Role.MEDIC, Role.SCIENTIST, Role.RESEARCHER, Role.QUARANTINE_SPECIALIST
D, OPS, P = Role.DISPATCHER, Role.OPERATIONS_EXPERT, Role.CONTINGENCY_PLANNER


def state(game: Game) -> tuple:
    return (
        list(game.location),
        [list(h) for h in game.hands],
        {c: dict(v) for c, v in game.cubes.items()},
        list(game.stations),
        dict(game.cures),
        game.actions_left,
        game.step,
        list(game.player_discard),
    )


def illegal(game: Game, seat: int, action: A.Action, match: str = "") -> None:
    before = state(game)
    with pytest.raises(IllegalMove, match=match):
        game.play(seat, action)
    assert state(game) == before


def end_actions(game: Game) -> None:
    game.play(game.current, Pass())


# ------------------------------------------------------------------ setup
@pytest.mark.parametrize("n", [2, 3, 4])
@pytest.mark.parametrize("epidemics", [4, 5, 6])
def test_setup(n, epidemics):
    game = Game(n, seed=n * 10 + epidemics, rules=RulesConfig(epidemics=epidemics))
    assert len(set(game.roles)) == n
    assert game.location == ["atl"] * n and game.stations == ["atl"]
    counts = sorted(sum(v.values()) for v in game.cubes.values() if sum(v.values()))
    assert counts == [1, 1, 1, 2, 2, 2, 3, 3, 3]
    assert len(game.infection_discard) == 9 and len(game.infection_deck) == 39
    assert all(len(h) == {2: 4, 3: 3, 4: 2}[n] for h in game.hands)
    assert game.card_count() == 53 + epidemics
    # one epidemic in each pile, the bigger piles on top
    deck = game.player_deck[::-1]
    sizes = game.pile_sizes
    assert sum(sizes) == len(deck) and sizes == sorted(sizes, reverse=True) and max(sizes) - min(sizes) <= 1
    start = 0
    for size in sizes:
        assert deck[start : start + size].count(EPIDEMIC) == 1
        start += size
    top = lambda s: max((CITIES[c].population for c in game.hands[s] if c in CITIES), default=0)  # noqa: E731
    assert top(game.current) == max(top(s) for s in range(n))
    assert game.step == Step.ACTIONS and game.actions_left == 4


def test_chosen_roles_are_kept():
    game = Game(3, seed=2, rules=RulesConfig(roles=(M, None, S)))
    assert game.roles[0] == M and game.roles[2] == S and game.roles[1] not in (M, S)
    with pytest.raises(ValueError):
        Game(2, rules=RulesConfig(roles=(M, M)))


# ------------------------------------------------------------------ movement
def test_drive_and_actions_run_out():
    game = new_game(S, R)
    me = game.current
    illegal(game, me, Drive("lon"), "isn't connected")
    illegal(game, 1 - me, Drive("chi"), "not your turn")
    for city in ("chi", "mon", "ny", "lon"):
        game.play(me, Drive(city))
    assert game.location[me] == "lon" and game.step == Step.DRAW and game.actions_left == 0
    illegal(game, me, Drive("par"), "no actions left")


def test_flights():
    game = new_game(S, R)
    me = game.current
    hand(game, me, "tok", "atl", "lag")
    illegal(game, me, DirectFlight("bag"), "need the Baghdad card")
    game.play(me, DirectFlight("tok"))
    assert game.location[me] == "tok" and "tok" in game.player_discard and "tok" not in game.hands[me]
    illegal(game, me, CharterFlight("lim"), "need the Tokyo card")
    game.play(me, DirectFlight("lag"))
    hand(game, me, "lag")
    game.play(me, CharterFlight("syd"))
    assert game.location[me] == "syd" and game.hands[me] == []
    game2 = new_game(S, R)
    me2 = game2.current
    illegal(game2, me2, ShuttleFlight("hk"), "no research station in Hong Kong")
    game2.stations.append("hk")
    game2.play(me2, ShuttleFlight("hk"))
    assert game2.location[me2] == "hk"


def test_dispatcher_moves_other_pawns():
    game = new_game(D, M)
    game.current = 0
    hand(game, 0, "lim", "atl")
    game.play(0, Drive("mia", pawn=1))
    assert game.location == ["atl", "mia"]
    game.play(0, DirectFlight("lim", pawn=1))
    assert game.location[1] == "lim" and "lim" in game.player_discard
    game.play(0, Dispatch(0, "lim"))
    assert game.location[0] == "lim"
    illegal(game, 0, Dispatch(1, "bag"), "No other pawn")
    other = new_game(M, S)
    other.current = 0
    illegal(other, 0, Drive("chi", pawn=1), "Only the Dispatcher")


def test_ops_expert():
    game = new_game(OPS, S)
    game.current = 0
    hand(game, 0, "lag", "kin")
    game.play(0, OpsFlight("syd", "lag"))
    assert game.location[0] == "syd" and game.hands[0] == ["kin"]
    game.play(0, Build())  # no card needed
    assert "syd" in game.stations and game.hands[0] == ["kin"]
    illegal(game, 0, OpsFlight("lim", "kin"), "already used")


# ------------------------------------------------------------------ treat, build, share, cure
def test_treat_one_or_all():
    game = new_game(S, R)
    me = game.current
    cubes(game, "atl", "blue", 3)
    game.play(me, Treat("blue"))
    assert game.cubes["atl"]["blue"] == 2 and game.supply["blue"] == CUBES_PER_COLOR - 2
    illegal(game, me, Treat("red"), "no red cubes")
    game.cures["blue"] = "cured"
    game.play(me, Treat("blue"))
    assert game.cubes["atl"]["blue"] == 0 and game.cures["blue"] == "eradicated"


def test_medic():
    game = new_game(M, S)
    game.current = 0
    cubes(game, "atl", "yellow", 3)
    game.play(0, Treat("yellow"))
    assert game.cubes["atl"]["yellow"] == 0
    game.cures["blue"] = "cured"
    cubes(game, "chi", "blue", 2)
    cubes(game, "mon", "blue", 1)
    events = game.play(0, Drive("chi"))
    assert game.cubes["chi"]["blue"] == 0
    assert any(e["kind"] == "medic_clear" for e in events)
    top_infection(game, "chi")
    end_actions(game)
    game.play(0, DrawCards()) if game.step == Step.DRAW else None
    while game.step == Step.EPIDEMIC:
        game.play(0, Continue())
    game.hands[0] = game.hands[0][:7]
    top_infection(game, "chi")
    game.play(0, Continue())
    assert game.cubes["chi"]["blue"] == 0


def test_build_moves_the_sixth_station():
    game = new_game(S, R)
    me = game.current
    game.stations = ["atl", "hk", "cai", "lim", "par", "syd"]
    game.location[me] = "chi"
    hand(game, me, "chi")
    illegal(game, me, Build(), "pick one to move")
    game.play(me, Build(remove="syd"))
    assert sorted(game.stations) == sorted(["atl", "hk", "cai", "lim", "par", "chi"])
    assert "chi" in game.player_discard


def test_share_knowledge():
    game = new_game(S, M)
    game.current = 0
    hand(game, 0, "atl", "bag")
    hand(game, 1, "chi")
    illegal(game, 0, Give("bag", 1), "Only the Atlanta card")
    game.play(0, Give("atl", 1))
    assert "atl" in game.hands[1]
    game.play(0, Take("atl", 1))
    assert "atl" in game.hands[0]
    game.location[1] = "chi"
    illegal(game, 0, Give("atl", 1), "same city")


def test_researcher_shares_any_card():
    game = new_game(R, S)
    game.current = 0
    hand(game, 0, "bag", "tok")
    game.play(0, Give("bag", 1))
    assert "bag" in game.hands[1]
    game.current = 1
    game.actions_left = 4
    game.play(1, Take("tok", 0))
    assert "tok" in game.hands[1]


def test_receiving_over_the_limit_forces_a_discard():
    game = new_game(S, M)
    game.current = 0
    hand(game, 0, "atl")
    hand(game, 1, "lon", "par", "ess", "mil", "mad", "stp", "chi")
    game.play(0, Give("atl", 1))
    assert game.waiting_for() == 1
    illegal(game, 0, Drive("chi"), "hand limit")
    illegal(game, 0, Discard("lon"), "don't have to discard")
    game.play(1, Discard("lon"))
    assert game.waiting_for() == 0 and len(game.hands[1]) == 7
    game.play(0, Drive("chi"))


def test_cure_and_win():
    game = new_game(S, M)
    game.current = 0
    hand(game, 0, "tok", "seo", "bei", "sha", "lon")
    illegal(game, 0, Cure(("tok", "seo", "bei", "lon")), "same color")
    illegal(game, 0, Cure(("tok", "seo", "bei")), "needs 4")
    game.location[0] = "chi"
    illegal(game, 0, Cure(("tok", "seo", "bei", "sha")), "research station")
    game.location[0] = "atl"
    game.cures.update({"blue": "cured", "yellow": "cured", "black": "eradicated"})
    events = game.play(0, Cure(("tok", "seo", "bei", "sha")))
    assert game.cures["red"] == "eradicated"  # no red cubes on the board
    assert game.result and game.result.won and game.step == Step.GAME_OVER
    assert events[-1]["kind"] == "game_over"
    illegal(game, 0, Drive("chi"), "over")


def test_medic_clears_on_cure():
    game = new_game(S, M)
    game.current = 0
    game.location[1] = "tok"
    cubes(game, "tok", "red", 2)
    cubes(game, "seo", "red", 1)
    hand(game, 0, "tok", "seo", "bei", "sha")
    game.play(0, Cure(("tok", "seo", "bei", "sha")))
    assert game.cubes["tok"]["red"] == 0 and game.cures["red"] == "cured"


# ------------------------------------------------------------------ infection
def test_outbreak_chain():
    game = new_game(S, R)
    cubes(game, "bag", "black", 3)
    cubes(game, "teh", "black", 3)
    events: list = []
    game._infect("bag", CITIES["bag"].color, 1, events)
    booms = [e["city"] for e in events if e["kind"] == "outbreak"]
    assert booms == ["bag", "teh"] and game.outbreaks == 2
    assert game.cubes["bag"]["black"] == 3 and game.cubes["teh"]["black"] == 3  # no cube back into the chain
    for city in ("ist", "cai", "riy", "kar", "mos", "del"):
        assert game.cubes[city]["black"] >= 1
    assert game.cubes["kar"]["black"] == 2  # next to both


def test_quarantine_specialist_protects():
    game = new_game(Q, S)
    game.location[0] = "bag"
    events: list = []
    game._infect("teh", CITIES["teh"].color, 1, events)
    game._infect("bag", CITIES["bag"].color, 1, events)
    assert game.cubes["teh"]["black"] == 0 and game.cubes["bag"]["black"] == 0
    assert [e["by"] for e in events] == ["quarantine", "quarantine"]
    game._infect("mum", CITIES["mum"].color, 1, events)
    assert game.cubes["mum"]["black"] == 1


def test_eradicated_disease_is_not_placed():
    game = new_game(S, R)
    game.cures["yellow"] = "eradicated"
    events: list = []
    game._infect("lag", CITIES["lag"].color, 3, events)
    assert game.cubes["lag"]["yellow"] == 0 and events[0]["by"] == "eradicated"


def test_turn_end_draw_and_infect():
    game = new_game(S, R)
    me = game.current
    top_player(game, "lon", "par")
    top_infection(game, "lag", "kin")
    end_actions(game)
    illegal(game, me, Continue(), "Nothing to continue")
    game.play(me, DrawCards())
    assert game.hands[me][-2:] == ["lon", "par"] and game.step == Step.INFECT
    game.play(me, Continue())
    assert game.cubes["lag"]["yellow"] == 1 and game.cubes["kin"]["yellow"] == 1
    assert game.current == 1 - me and game.step == Step.ACTIONS and game.turn == 2


def test_epidemic():
    game = new_game(S, R)
    me = game.current
    top_player(game, EPIDEMIC, "lon")
    bottom = game.infection_deck[0]
    discard_before = set(game.infection_discard)
    end_actions(game)
    events = game.play(me, DrawCards())
    assert game.step == Step.EPIDEMIC and game.epidemics_drawn == 1
    assert game.cubes[bottom][CITIES[bottom].color] == 3
    assert any(e["kind"] == "epidemic" for e in events)
    hand(game, 1 - me, "resilient", "airlift")
    illegal(game, 1 - me, Airlift(0, "lim"), "Resilient Population")
    game.play(1 - me, ResilientPopulation(bottom))
    assert bottom in game.removed
    game.play(me, Continue())
    assert game.step == Step.INFECT and game.infection_discard == []
    assert set(game.infection_deck[-len(discard_before) :]) == discard_before
    assert set(game.known_top) == discard_before
    assert game.infection_rate == 2


def test_epidemic_on_a_city_with_cubes_outbreaks():
    game = new_game(S, R)
    me = game.current
    top_player(game, EPIDEMIC, "lon")
    bottom = game.infection_deck[0]
    color = CITIES[bottom].color
    cubes(game, bottom, color, 1)
    end_actions(game)
    game.play(me, DrawCards())
    assert game.cubes[bottom][color] == 3 and game.outbreaks == 1


def test_two_epidemics_in_one_draw():
    game = new_game(S, R, epidemics=4)
    me = game.current
    top_player(game, EPIDEMIC, EPIDEMIC)
    end_actions(game)
    game.play(me, DrawCards())
    game.play(me, Continue())
    assert game.step == Step.EPIDEMIC and game.epidemics_drawn == 2
    game.play(me, Continue())
    assert game.step == Step.INFECT


def test_hand_limit_after_drawing():
    game = new_game(S, R)
    me = game.current
    hand(game, me, "lon", "par", "ess", "mil", "mad", "stp", "chi")
    top_player(game, "ny", "was")
    end_actions(game)
    game.play(me, DrawCards())
    assert game.waiting_for() == me
    illegal(game, me, Continue(), "Discard down")
    game.play(me, Discard("ny"))
    game.play(me, Discard("was"))
    game.play(me, Continue())


# ------------------------------------------------------------------ losing
def test_eighth_outbreak_loses():
    game = new_game(S, R)
    game.outbreaks = 7
    cubes(game, "lag", "yellow", 3)
    events: list = []
    game._infect("lag", CITIES["lag"].color, 1, events)
    assert game.result and not game.result.won and game.result.reason == "outbreaks"


def test_running_out_of_cubes_loses():
    game = new_game(S, R)
    game.supply["red"] = 0
    events: list = []
    game._infect("tok", CITIES["tok"].color, 1, events)
    assert game.result and game.result.reason == "cubes" and game.result.color == "red"


def test_empty_deck_loses():
    game = new_game(S, R)
    me = game.current
    game.player_discard += game.player_deck[:-1]
    game.player_deck = game.player_deck[-1:]
    end_actions(game)
    events = game.play(me, DrawCards())
    assert game.result and game.result.reason == "deck"
    assert events[-1]["kind"] == "game_over"


# ------------------------------------------------------------------ events
def test_airlift_and_grant_any_time():
    game = new_game(S, M)
    other = 1 - game.current
    hand(game, other, "airlift", "grant")
    game.cures["red"] = "cured"
    cubes(game, "tok", "red", 2)
    game.play(other, Airlift(1, "tok"))  # out of turn
    assert game.location[1] == "tok" and game.cubes["tok"]["red"] == 0  # the Medic clears on arrival
    game.play(other, GovernmentGrant("lim"))
    assert "lim" in game.stations and game.hands[other] == []
    assert {"airlift", "grant"} <= set(game.player_discard)


def test_one_quiet_night():
    game = new_game(S, R)
    me = game.current
    hand(game, me, "quiet")
    game.play(me, OneQuietNight())
    top_player(game, "lon", "par")
    top_infection(game, "lag", "kin")
    end_actions(game)
    game.play(me, DrawCards())
    events = game.play(me, Continue())
    assert any(e["kind"] == "quiet_night" for e in events)
    assert game.cubes["lag"]["yellow"] == 0 and not game.quiet_night


def test_forecast():
    game = new_game(S, R)
    me = game.current
    hand(game, me, "forecast")
    events = game.play(me, Forecast())
    cards = events[-1]["cards"]
    assert len(cards) == 6 and cards[0] == game.infection_deck[-1]
    illegal(game, me, Drive("chi"), "Forecast")
    with pytest.raises(IllegalMove, match="exactly the cards"):
        game.play(me, ForecastOrder(tuple(cards[:5])))
    order = tuple(reversed(cards))
    game.play(me, ForecastOrder(order))
    assert game.infection_deck[-1] == order[0] and game.infection_deck[-6] == order[5]
    assert game.forecast is None
    game.play(me, Drive("chi"))


def test_contingency_planner():
    game = new_game(P, S)
    game.current = 0
    hand(game, 0)
    hand(game, 1, "airlift")
    hand(game, 1)
    game.player_deck.remove("airlift")
    game.player_discard.append("airlift")
    illegal(game, 0, TakeEvent("forecast"), "isn't in the player discard pile")
    game.play(0, TakeEvent("airlift"))
    assert game.stored[0] == "airlift" and game.hands[0] == []
    game.play(0, Airlift(1, "syd"))
    assert game.stored[0] is None and "airlift" in game.removed and "airlift" not in game.player_discard
    assert game.card_count() == 53 + 4


# ------------------------------------------------------------------ undo
def test_undo():
    game = new_game(S, R)
    me = game.current
    hand(game, me, "tok")
    before = state(game)
    game.play(me, Drive("chi"))
    game.play(me, DirectFlight("tok"))
    game.undo(me)
    assert game.location[me] == "chi" and "tok" in game.hands[me]
    game.undo(me)
    assert state(game) == before
    with pytest.raises(IllegalMove):
        game.undo(me)
    game.play(me, Drive("chi"))
    end_actions(game)
    game.play(me, DrawCards())
    assert not game.can_undo(me)


def test_undo_is_cleared_by_an_event():
    game = new_game(S, R)
    me = game.current
    hand(game, 1 - me, "quiet")
    game.play(me, Drive("chi"))
    game.play(1 - me, OneQuietNight())
    assert not game.can_undo(me)


# ------------------------------------------------------------------ protocol, views, random games
def test_json_round_trip():
    samples = [
        Drive("chi"),
        Drive("chi", 1),
        DirectFlight("tok"),
        CharterFlight("lim", 2),
        ShuttleFlight("hk"),
        Dispatch(1, "atl"),
        OpsFlight("syd", "lag"),
        Build(),
        Build("hk"),
        Treat("red"),
        Give("atl", 1),
        Take("atl", 0),
        Cure(("tok", "seo", "bei", "sha", "hk")),
        TakeEvent("airlift"),
        Pass(),
        DrawCards(),
        Continue(),
        Discard("lon"),
        Airlift(0, "syd"),
        GovernmentGrant("lim", "hk"),
        OneQuietNight(),
        Forecast(),
        ForecastOrder(("lag", "kin")),
        ResilientPopulation("lag"),
    ]
    for action in samples:
        assert A.from_json(A.to_json(action)) == action
    for bad in [
        None,
        {"type": "fly"},
        {"type": "drive"},
        {"type": "drive", "to": 5},
        {"type": "treat", "color": "x"},
        {"type": "give", "card": "atl", "to": "1"},
    ]:
        with pytest.raises(A.BadAction):
            A.from_json(bad)


def test_closed_view_hides_other_hands():
    game = new_game(S, R, M)
    view = game.view(1, open_hands=False)
    assert view.hands[1] == game.hands[1] and view.hands[0] is None and view.hand_counts[0] == len(game.hands[0])
    sandbox = view.sandbox()
    assert sandbox.location == game.location and len(sandbox.hands[0]) == len(game.hands[0])


def test_sandbox_agrees_with_the_game():
    game = Game(3, seed=4)
    me = game.current
    sandbox = game.view(me).sandbox()
    assert {repr(a) for a in sandbox.turn_actions(me)} == {repr(a) for a in game.turn_actions(me)}


def _random_game(seed: int) -> Game:
    rng = random.Random(seed)
    n = 2 + seed % 3
    game = Game(n, seed=seed, rules=RulesConfig(epidemics=4 + seed % 3))
    total = 53 + game.rules.epidemics
    for _ in range(5000):
        if game.result is not None:
            break
        seat = game.waiting_for()
        assert seat is not None
        if rng.random() < 0.05:
            other = rng.randrange(n)
            if game.event_actions(other):
                seat = other
        choices = game.legal_actions(seat)
        assert choices
        action = rng.choice(choices)
        if isinstance(action, ForecastOrder):
            order = list(action.order)
            rng.shuffle(order)
            action = ForecastOrder(tuple(order))
        if game.can_undo(seat) and rng.random() < 0.05:
            game.undo(seat)
        else:
            trial = game.clone()
            trial.play(seat, action)  # clones play the same
            game.play(seat, action)
            assert trial.location == game.location and trial.cubes == game.cubes
        assert game.card_count() == total
        assert game.infection_count() == 48
        for color in COLORS:
            assert sum(c[color] for c in game.cubes.values()) + game.supply[color] == CUBES_PER_COLOR
            assert all(0 <= c[color] <= 3 for c in game.cubes.values())
        assert all(len(h) <= 9 for h in game.hands)  # 7 + the 2 just drawn
        assert len(game.stations) <= 6
        assert all(c in EVENTS for c in game.stored if c)
    assert game.result is not None
    return game


def test_random_games_keep_the_invariants():
    for seed in range(120):
        _random_game(seed)
