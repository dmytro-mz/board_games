"""Rules of Agent Avenue (official rulebook): simple mode, advanced mode and the team variant."""

from __future__ import annotations

import random

import pytest

from avenue.game.cards import (
    BRAINWASHING,
    CODEBREAKER,
    DAREDEVIL,
    DISTRACTION,
    DOUBLE_AGENT,
    DOUBLE_TROUBLE,
    ENFORCER,
    GETAWAY,
    LEADER,
    MASTERPLAN,
    MOLE,
    N_MARKET,
    OUTPOST,
    SABOTEUR,
    SECRET_RECRUIT,
    SECURITY,
    SENTINEL,
    SIDEKICK,
    SINISTER_TWIN,
    SMOKE_SCREEN,
    SPYCATION,
    SUPERCOMPUTER,
    TOTAL_AGENTS,
    TRUCK,
    WATCHTOWER,
    base_move,
)
from avenue.game.engine import HIDDEN, Game, IllegalMove, Phase


def game(teams: list[int] | None = None, advanced: bool = False, first: int = 0, seed: int = 1) -> Game:
    return Game(teams or [0, 1], advanced=advanced, seed=seed, first=first)


def turn(g: Game, up: int, down: int, take: str) -> list[dict]:
    """Active (solo) player plays up/down; the other side recruits 'up' or 'down'."""
    p = g.sides[g.active][0]
    g.hands[p][:2] = [up, down]
    events = g.step(p, ("play", up, down))
    other = g.sides[1 - g.active][0]
    events += g.step(other, ("recruit", 0 if take == "up" else 1))
    return events


# ---------------------------------------------------------------------- setup
def test_setup_simple():
    g = game()
    assert [len(h) for h in g.hands] == [4, 4]
    assert len(g.deck) == TOTAL_AGENTS - 8 == 30
    assert g.pos == [0, 7] and g.distance(0) == 7 and g.distance(1) == 7
    assert g.supply == [] and g.market_deck == []
    assert g.discards_left == [4, 4]
    assert g.phase == Phase.PLAY


def test_setup_advanced_and_teams():
    g = game([0, 1, 0, 1], advanced=True)
    assert len(g.supply) == 3 and len(g.market_deck) == N_MARKET - 3
    assert len(g.deck) == TOTAL_AGENTS - 16
    assert g.discards_left == [2, 2, 2, 2]
    g3 = game([0, 0, 1])
    assert g3.discards_left == [2, 2, 4]  # the lone player discards up to 4 times


def test_card_icons():
    assert [base_move(DOUBLE_AGENT, n) for n in (1, 2, 3, 4, 6)] == [-1, 6, -1, -1, -1]
    assert [base_move(ENFORCER, n) for n in (1, 2, 3)] == [1, 2, 3]
    assert [base_move(CODEBREAKER, n) for n in (1, 2, 3)] == [0, 0, 0]
    assert [base_move(SABOTEUR, n) for n in (1, 2, 3)] == [-1, -1, -2]
    assert [base_move(DAREDEVIL, n) for n in (1, 2, 3)] == [2, 3, 0]
    assert [base_move(SENTINEL, n) for n in (1, 2, 3)] == [0, 2, 6]
    assert base_move(SIDEKICK, 1) == 4 and base_move(MOLE, 1) == -3


# ---------------------------------------------------------------------- play step
def test_play_needs_two_different_names():
    g = game()
    g.hands[0] = [ENFORCER, ENFORCER, SENTINEL, MOLE]
    with pytest.raises(IllegalMove):
        g.step(0, ("play", ENFORCER, ENFORCER))
    with pytest.raises(IllegalMove):
        g.step(1, ("play", ENFORCER, SENTINEL))  # not your turn
    g.step(0, ("play", ENFORCER, SENTINEL))
    assert g.phase == Phase.RECRUIT
    assert len(g.hands[0]) == 4  # drew back up to 4 after playing both


def test_identical_cards_only_if_whole_hand_is_one_name():
    g = game()
    g.hands[0] = [SABOTEUR] * 4
    assert g.legal(0) and all(a[1] == a[2] == SABOTEUR for a in g.legal(0) if a[0] == "play")
    g.step(0, ("play", SABOTEUR, SABOTEUR))


def test_discard_and_draw():
    g = game()
    deck = len(g.deck)
    g.step(0, ("discard", g.hands[0][0]))
    assert len(g.hands[0]) == 4 and len(g.discards[0]) == 1 and len(g.deck) == deck - 1
    assert g.discards_left[0] == 3
    for _ in range(3):
        g.step(0, ("discard", g.hands[0][0]))
    assert g.discards_left[0] == 0
    assert not any(a[0] == "discard" for a in g.legal(0))


def test_no_discard_with_empty_deck():
    g = game()
    g.deck = []
    assert not any(a[0] == "discard" for a in g.legal(0))


def test_no_more_draws_when_deck_is_empty():
    g = game()
    g.deck = []
    g.hands[1] = [SENTINEL, ENFORCER, MOLE, CODEBREAKER]
    turn(g, ENFORCER, SENTINEL, "up")
    assert len(g.hands[0]) == 2


# ---------------------------------------------------------------------- recruit + movement
def test_recruit_moves_both_meeples():
    g = game()
    turn(g, DOUBLE_AGENT, SIDEKICK, "up")  # blue takes the Double Agent (-1), green keeps the Sidekick (+4)
    assert g.tableau[1][DOUBLE_AGENT] == 1 and g.tableau[0][SIDEKICK] == 1
    assert g.pos == [4, 6]
    assert g.active == 1 and g.turn == 2


def test_second_and_third_copy_use_lower_icons():
    g = game()
    g.tableau[0][DOUBLE_AGENT] = 1
    turn(g, ENFORCER, DOUBLE_AGENT, "up")  # green gets its 2nd Double Agent: +6
    assert g.pos[0] == 6
    g2 = game()
    g2.tableau[0][DOUBLE_AGENT] = 5
    turn(g2, ENFORCER, DOUBLE_AGENT, "up")  # 6th copy counts as the 3rd: -1
    assert g2.pos[0] == -1


def test_catch_by_reaching_or_passing():
    g = game()
    g.pos = [0, 4]
    turn(g, ENFORCER, SIDEKICK, "up")  # green +4 would reach blue, but blue escapes 1 forward with the Enforcer
    assert g.result is None and g.pos == [4, 5]
    g = game()
    g.pos = [0, 3]
    events = turn(g, MOLE, SIDEKICK, "up")  # blue -3 → 0, green +4 → 4: passed
    assert g.result is not None and g.result["winner"] == 0 and "caught" in g.result["reasons"]
    assert events[-1]["kind"] == "game_over"


def test_escape_forward_in_the_same_turn():
    g = game()
    g.pos = [0, 2]
    g.tableau[1][DOUBLE_AGENT] = 1
    turn(g, DOUBLE_AGENT, ENFORCER, "up")  # green +1 = 1, blue +6 = 8 escapes
    assert g.result is None


def test_moving_backward_onto_the_other_meeple_is_caught():
    g = game()
    g.pos = [5, 7]
    turn(g, MOLE, SENTINEL, "up")  # blue -3 → 4, green 0
    assert g.result["winner"] == 0


def test_blue_catches_green_around_the_loop():
    g = game(first=1)
    g.pos = [0, 10]  # blue is 4 behind green
    g.hands[1][:2] = [MOLE, SIDEKICK]
    g.step(1, ("play", MOLE, SIDEKICK))
    g.step(0, ("recruit", 0))  # green takes the Mole (-3) → -3; blue +4 → 14 ≥ -3 + 14
    assert g.result["winner"] == 1


def test_three_codebreakers_win_and_three_daredevils_lose():
    g = game()
    g.tableau[1][CODEBREAKER] = 2
    turn(g, CODEBREAKER, ENFORCER, "up")
    assert g.result["winner"] == 1 and g.result["reasons"] == ["codebreakers"]
    g = game()
    g.tableau[0][DAREDEVIL] = 2
    turn(g, ENFORCER, DAREDEVIL, "up")
    assert g.result["winner"] == 1 and "opponent_daredevils" in g.result["reasons"]


def test_tie_goes_to_the_active_player():
    g = game(first=1)
    g.tableau[0][CODEBREAKER] = 2
    g.tableau[1][CODEBREAKER] = 2
    g.hands[1][:2] = [CODEBREAKER, ENFORCER]
    g.deck.append(CODEBREAKER)
    g.hands[1][2] = CODEBREAKER
    g.step(1, ("play", CODEBREAKER, ENFORCER))
    # green takes the Enforcer, blue keeps the Codebreaker: only blue wins
    g2 = g.clone()
    g2.step(0, ("recruit", 1))
    assert g2.result["winner"] == 1 and not g2.result["tie"]
    # both win (green 3 Codebreakers, blue catches green) → active blue wins
    g3 = game(first=1)
    g3.tableau[0][CODEBREAKER] = 2
    g3.pos = [0, 12]
    g3.hands[1][:2] = [CODEBREAKER, SIDEKICK]
    g3.step(1, ("play", CODEBREAKER, SIDEKICK))
    g3.step(0, ("recruit", 0))
    assert g3.result["winner"] == 1 and g3.result["tie"]


def test_win_and_lose_condition_for_one_player_goes_to_active():
    g = game(first=0)
    g.tableau[1][DAREDEVIL] = 2
    g.pos = [0, 3]
    g.hands[0][:2] = [DAREDEVIL, MOLE]
    g.step(0, ("play", DAREDEVIL, MOLE))
    g.step(1, ("recruit", 1))  # blue: Mole -3 → 0 = green → green wins; green: DD +2. fine
    assert g.result["winner"] == 0
    g = game(first=1)
    g.tableau[0][DAREDEVIL] = 2
    g.tableau[0][CODEBREAKER] = 2
    g.hands[1][:2] = [DAREDEVIL, CODEBREAKER]
    g.step(1, ("play", CODEBREAKER, DAREDEVIL))
    g.step(0, ("recruit", 0))  # green gets its 3rd Codebreaker (win) — blue keeps the Daredevil
    assert g.result["winner"] == 0
    g = game(first=1)
    g.tableau[1][DAREDEVIL] = 2
    g.tableau[1][CODEBREAKER] = 2
    g.hands[1][:3] = [DAREDEVIL, CODEBREAKER, ENFORCER]
    g.step(1, ("play", ENFORCER, CODEBREAKER))
    g.step(0, ("recruit", 0))
    assert g.result["winner"] == 1  # 3 Codebreakers, no losing condition


def test_running_out_of_cards():
    g = game()
    g.deck = []
    g.hands[1] = [ENFORCER]  # blue can't play next turn
    g.hands[0] = [SENTINEL, SABOTEUR]
    g.pos = [0, 5]  # green is 5 away, blue 9 away
    g.step(0, ("play", SENTINEL, SABOTEUR))
    g.step(1, ("recruit", 0))  # blue takes the Sentinel (0), green the Saboteur (-1): green 6 away, blue 8
    assert g.result["winner"] == 0 and g.result["reasons"] == ["out_of_cards"]


def test_running_out_tie_goes_to_active():
    g = game(first=0)
    g.deck = []
    g.hands[1] = [ENFORCER]
    g.hands[0] = [SENTINEL, CODEBREAKER]
    g.step(0, ("play", SENTINEL, CODEBREAKER))
    g.step(1, ("recruit", 0))
    assert g.pos == [0, 7] and g.result["winner"] == 0 and g.result["tie"]


def test_game_goes_on_when_next_player_can_still_play():
    g = game()
    g.deck = []
    g.hands[1] = [ENFORCER, SENTINEL]
    g.hands[0] = [SENTINEL, SABOTEUR]
    g.step(0, ("play", SENTINEL, SABOTEUR))
    g.step(1, ("recruit", 0))
    assert g.result is None and g.active == 1


# ---------------------------------------------------------------------- advanced mode
def adv(first: int = 0, seed: int = 1) -> Game:
    g = game(advanced=True, first=first, seed=seed)
    return g


def test_landing_exactly_on_a_market_space_takes_a_card():
    g = adv()
    g.supply = [TRUCK, SMOKE_SCREEN, OUTPOST]
    g.market_deck = [SECURITY]
    turn(g, ENFORCER, SENTINEL, "down")  # blue Sentinel 0, green Enforcer +1
    assert g.phase == Phase.PLAY  # 1 is not a market space
    g = adv()
    g.supply = [WATCHTOWER, SMOKE_SCREEN, OUTPOST]
    g.market_deck = [SECURITY]
    g.tableau[0][DAREDEVIL] = 0
    turn(g, ENFORCER, DAREDEVIL, "up")  # green +2 → space 2 (market); blue +1 → 8
    assert g.phase == Phase.MARKET and g.queue == [0]
    assert g.legal(1) == [] and g.legal(0) == [("market", 0), ("market", 1), ("market", 2)]
    g.step(0, ("market", 0))
    assert g.owned[0] == [WATCHTOWER] and g.supply == [SECURITY, SMOKE_SCREEN, OUTPOST]
    assert g.phase == Phase.PLAY and g.active == 1


def test_landing_on_market_space_backward_counts_passing_does_not():
    g = adv(first=1)
    g.pos = [0, 10]  # blue on space 10: a Saboteur (-1) lands it on space 9, a market space
    g.hands[1][:2] = [SABOTEUR, SENTINEL]
    g.step(1, ("play", SENTINEL, SABOTEUR))
    g.step(0, ("recruit", 0))
    assert g.phase == Phase.MARKET and g.queue == [1]
    g = adv()
    g.hands[0][:2] = [SIDEKICK, SENTINEL]
    g.step(0, ("play", SENTINEL, SIDEKICK))
    g.step(1, ("recruit", 0))  # green +4 → 4, passing space 2
    assert g.phase == Phase.PLAY


def test_zero_move_on_a_market_space_takes_nothing():
    g = adv()
    g.pos = [2, 7]
    turn(g, ENFORCER, SENTINEL, "up")  # green Sentinel: 0
    assert g.phase == Phase.PLAY


def test_both_land_active_first():
    g = adv()
    g.pos = [1, 8]  # green +1 → 2 (market), blue +1 → 9 (market)
    g.market_deck = [SECURITY, LEADER]
    g.hands[0][:2] = [ENFORCER, SABOTEUR]
    g.owned[1] = [DISTRACTION]  # blue's Saboteur moves +1
    g.supply = [WATCHTOWER, GETAWAY, MASTERPLAN]
    g.step(0, ("play", ENFORCER, SABOTEUR))
    g.step(1, ("recruit", 1))  # blue takes the Saboteur (+1 with Distraction) → 9; green Enforcer +1 → 2
    assert g.queue == [0, 1] and g.phase == Phase.MARKET
    assert g.legal(1) == []
    g.step(0, ("market", 0))
    assert g.queue == [1] and g.legal(1)
    g.step(1, ("market", 0))
    assert g.owned[0] == [WATCHTOWER] and g.owned[1] == [DISTRACTION, LEADER]  # top of the deck = last


def _land_and_take(g: Game, card: int, top: int | None = None) -> None:
    """Put `card` in the supply and make green (active) land on space 2 and take it.

    Green plays Sentinel face up and Enforcer face down; blue takes the Sentinel (0), green the Enforcer (+1).
    `top` is put on top of the agent deck after green has drawn back up.
    """
    g.supply = [card, *[m for m in range(N_MARKET) if m != card][:2]]
    g.market_deck = [m for m in range(N_MARKET) if m not in g.supply][:5]
    g.pos[0] = 1
    if g.pos[1] < 2 or g.pos[1] > 15:
        g.pos[1] = 10
    g.hands[0][:2] = [ENFORCER, SENTINEL]
    g.step(0, ("play", SENTINEL, ENFORCER))
    if top is not None:
        g.deck.append(top)
    g.step(1, ("recruit", 0))  # green Enforcer +1 → space 2
    assert g.phase == Phase.MARKET
    g.step(0, ("market", 0))


def test_ongoing_abilities_modify_movement():
    g = adv()
    g.owned[0] = [DISTRACTION, WATCHTOWER, SINISTER_TWIN, SUPERCOMPUTER]
    assert g.move_value(0, SABOTEUR, 3) == 2
    assert g.move_value(0, ENFORCER, 1) == 3
    assert g.move_value(0, DOUBLE_AGENT, 2) == 12 and g.move_value(0, DOUBLE_AGENT, 1) == -2
    assert g.move_value(0, CODEBREAKER, 1) == 3 and g.move_value(0, CODEBREAKER, 3) == 3
    assert g.move_value(1, SABOTEUR, 1) == -1


def test_ongoing_has_no_effect_on_the_card_just_recruited():
    g = adv()
    _land_and_take(g, WATCHTOWER)
    assert g.pos[0] == 2 and g.owned[0] == [WATCHTOWER]


def test_leader_of_the_pack_wins_with_three_daredevils():
    g = adv()
    g.owned[0] = [LEADER]
    g.tableau[0][DAREDEVIL] = 2
    turn(g, ENFORCER, DAREDEVIL, "up")
    assert g.result["winner"] == 0 and "leader_of_the_pack" in g.result["reasons"]


def test_masterplan_seven_different_agents():
    g = adv()
    g.owned[0] = [MASTERPLAN]
    for c in (DOUBLE_AGENT, CODEBREAKER, SABOTEUR, DAREDEVIL, SIDEKICK, MOLE):
        g.tableau[0][c] = 1
    g.pos = [20, 30]
    turn(g, ENFORCER, SENTINEL, "down")  # green recruits its 7th different agent (Enforcer)
    assert g.result["winner"] == 0 and "masterplan" in g.result["reasons"]


def test_security_system():
    g = adv(first=1)
    g.owned[0] = [SECURITY]
    g.pos = [3, 15]  # blue -1 → 14, which is green's home space
    g.hands[1][:2] = [SABOTEUR, SENTINEL]
    g.step(1, ("play", SENTINEL, SABOTEUR))
    g.step(0, ("recruit", 0))  # green Sentinel 0, blue Saboteur -1 → 14 ≡ green home
    assert g.result["winner"] == 0 and g.result["reasons"] == ["security_system"]


def test_getaway_car_moves_three_after_landing_on_a_home():
    g = adv()
    g.owned[0] = [GETAWAY]
    g.pos = [3, 12]
    turn(g, ENFORCER, MOLE, "up")  # green Mole -3 → 0 (own home) → +3
    assert g.pos[0] == 3
    g = adv()
    g.owned[0] = [GETAWAY]
    g.tableau[0][ENFORCER] = 2
    g.pos = [4, 16]
    turn(g, SENTINEL, ENFORCER, "up")  # green Enforcer 3rd: +3 → 7 (blue's home) → 10
    assert g.pos[0] == 10


def test_truck_moves_one():
    g = adv()
    _land_and_take(g, TRUCK)
    assert g.pos[0] == 3 and g.market_discard == [TRUCK]


def test_smoke_screen_recruits_top_card_and_chains():
    g = adv()
    _land_and_take(g, SMOKE_SCREEN, top=SIDEKICK)
    assert g.tableau[0][SIDEKICK] == 1 and g.pos[0] == 6


def test_smoke_screen_landing_on_another_market_space_takes_again():
    g = adv()
    _land_and_take(g, SMOKE_SCREEN, top=SABOTEUR)  # Saboteur -1 → space 1: no new card
    assert g.pos[0] == 1 and g.phase == Phase.PLAY
    g = adv()
    g.tableau[0][DAREDEVIL] = 1
    _land_and_take(g, SMOKE_SCREEN, top=DAREDEVIL)  # 2nd Daredevil +3 → space 5: another market space
    assert g.pos[0] == 5 and g.phase == Phase.MARKET and g.queue == [0]
    assert g.legal(0)  # green takes another card before anything else


def test_outpost_recruits_a_sentinel_from_hand_and_refills():
    g = adv()
    g.hands[0][2] = SENTINEL
    deck = len(g.deck)
    _land_and_take(g, OUTPOST)
    assert g.tableau[0][SENTINEL] == 1 and SENTINEL not in g.hands[0][:1]
    assert len(g.hands[0]) == 4 and len(g.deck) == deck - 3  # 2 after playing, 1 after Outpost
    assert g.market_discard == [OUTPOST]


def test_outpost_without_sentinel_is_ignored():
    g = adv()
    g.hands[0][2:] = [MOLE, MOLE]
    g.deck = [MOLE] * 6
    _land_and_take(g, OUTPOST)
    assert g.tableau[0][SENTINEL] == 0 and g.phase == Phase.PLAY


def test_brainwashing_device_takes_an_agent_into_hand():
    g = adv()
    g.tableau[1][CODEBREAKER] = 2
    g.tableau[1][MOLE] = 1
    _land_and_take(g, BRAINWASHING)
    assert g.phase == Phase.CHOICE and g.choice["stage"] == "steal"
    assert g.legal(0) == [("choose", c) for c in sorted({CODEBREAKER, MOLE, SENTINEL})]
    g.step(0, ("choose", CODEBREAKER))
    assert g.tableau[1][CODEBREAKER] == 1 and g.hands[0].count(CODEBREAKER) >= 1
    assert len(g.hands[0]) == 5  # hand grows, no draw
    assert CODEBREAKER in g.known[0]
    assert g.pos[1] == 7  # nobody moves


def test_brainwashing_stops_a_third_codebreaker_win():
    g = adv(first=1)
    g.tableau[1][CODEBREAKER] = 2
    g.supply = [BRAINWASHING, WATCHTOWER, MASTERPLAN]
    g.market_deck = [SECURITY]
    g.pos = [1, 10]
    g.hands[1][:2] = [CODEBREAKER, ENFORCER]
    g.step(1, ("play", ENFORCER, CODEBREAKER))
    g.step(0, ("recruit", 0))  # green +1 → 2 (market); blue gets its 3rd Codebreaker
    g.step(0, ("market", 0))  # the only agent blue has in play: resolved straight away
    assert g.result is None and g.tableau[1][CODEBREAKER] == 2 and CODEBREAKER in g.hands[0]


def test_double_trouble():
    g = adv()
    g.hands[0][2:] = [DOUBLE_AGENT, DOUBLE_AGENT]
    g.tableau[0][DOUBLE_AGENT] = 1
    g.pos[1] = 10
    _land_and_take(g, DOUBLE_TROUBLE)
    # single pair → resolved straight away: 2nd Double Agent moves +6
    assert g.tableau[0][DOUBLE_AGENT] == 2 and g.pos[0] == 8
    assert DOUBLE_AGENT in g.known[0]


def test_secret_recruit_needs_a_new_name():
    g = adv()
    g.hands[0][2:] = [MOLE, SIDEKICK]
    g.pos[1] = 10
    _land_and_take(g, SECRET_RECRUIT)
    assert g.phase == Phase.CHOICE and set(g.choice["options"]) >= {MOLE, SIDEKICK}
    assert ENFORCER not in g.choice["options"]  # already in play
    g.step(0, ("choose", SIDEKICK))
    assert g.pos[0] == 6 and g.tableau[0][SIDEKICK] == 1


def test_spycation_take_back_and_recruit_again():
    g = adv()
    g.tableau[0][DOUBLE_AGENT] = 2
    g.pos[1] = 10
    _land_and_take(g, SPYCATION)
    assert g.choice["stage"] == "spy_pick"
    g.step(0, ("choose", DOUBLE_AGENT))
    assert g.tableau[0][DOUBLE_AGENT] == 1 and g.pos[0] == 2  # removing doesn't move
    assert g.choice["stage"] == "spy_recruit" and g.legal(0) == [("choose", 1), ("choose", 0)]
    g.step(0, ("choose", 1))
    assert g.tableau[0][DOUBLE_AGENT] == 2 and g.pos[0] == 8


def test_spycation_keep_in_hand():
    g = adv()
    g.pos[1] = 10
    _land_and_take(g, SPYCATION)
    g.step(0, ("choose", ENFORCER))
    g.step(0, ("choose", 0))
    assert g.tableau[0][ENFORCER] == 0 and g.hands[0].count(ENFORCER) >= 1 and len(g.hands[0]) == 5
    assert g.phase == Phase.PLAY


def test_empty_supply_is_ignored():
    g = adv()
    g.supply = []
    g.market_deck = []
    g.pos[0] = 1
    g.hands[0][:2] = [ENFORCER, SENTINEL]
    g.step(0, ("play", SENTINEL, ENFORCER))
    events = g.step(1, ("recruit", 0))
    assert any(e["kind"] == "market_empty" for e in events) and g.phase == Phase.PLAY


def test_supply_is_not_refilled_when_the_market_deck_is_empty():
    g = adv()
    g.supply = [WATCHTOWER, MASTERPLAN, SECURITY]
    g.market_deck = []
    g.pos[0] = 1
    g.hands[0][:2] = [ENFORCER, SENTINEL]
    g.step(0, ("play", SENTINEL, ENFORCER))
    g.step(1, ("recruit", 0))
    g.step(0, ("market", 1))
    assert g.supply == [WATCHTOWER, SECURITY]


# ---------------------------------------------------------------------- team variant
def test_team_play_order_and_recruit():
    g = game([0, 1, 0, 1], first=0)  # players 0, 2 green; 1, 3 blue
    assert set(g.waiting()) == {0, 2}
    up = g.hands[2][0]
    g.step(2, ("play", up, -1))
    assert g.waiting() == [0]
    assert len(g.hands[2]) == 4
    down = next((c for c in g.hands[0] if c != up), g.hands[0][0])
    g.step(0, ("play", -1, down))
    assert g.phase == Phase.RECRUIT and set(g.waiting()) == {1, 3}
    g.step(3, ("recruit", 1))
    assert g.tableau[1][down] >= 1 and g.tableau[0][up] >= 1
    assert g.active == 1


def test_team_face_down_must_differ_from_teammates_face_up():
    g = game([0, 1, 0, 1], first=0)
    g.hands[2][0] = ENFORCER
    g.step(2, ("play", ENFORCER, -1))
    g.hands[0] = [ENFORCER, ENFORCER, SENTINEL, MOLE]
    assert ("play", -1, ENFORCER) not in g.legal(0)
    g.hands[0] = [ENFORCER] * 4
    assert [a for a in g.legal(0) if a[0] == "play"] == [("play", -1, ENFORCER)]


def test_team_discards_two_each():
    g = game([0, 1, 0, 1], first=0)
    g.step(0, ("discard", g.hands[0][0]))
    g.step(0, ("discard", g.hands[0][0]))
    assert not any(a[0] == "discard" for a in g.legal(0))
    assert any(a[0] == "discard" for a in g.legal(2))


def test_team_face_up_player_draws_the_last_card():
    g = game([0, 1, 0, 1], first=0)
    g.deck = [MOLE]
    g.step(2, ("play", g.hands[2][0], -1))
    assert len(g.hands[2]) == 4 and g.hands[2][-1] == MOLE and not g.deck


def test_team_running_out_when_an_opponent_has_no_cards():
    g = game([0, 1, 0, 1], first=0)
    g.deck = []
    g.hands[3] = []
    g.hands[1] = [ENFORCER, MOLE]
    up = g.hands[0][0]
    g.step(0, ("play", up, -1))
    g.step(2, ("play", -1, next(c for c in g.hands[2] if c != up) if any(c != up for c in g.hands[2]) else up))
    g.pos = [0, 7]
    g.step(1, ("recruit", 0))
    assert g.result is not None and g.result["reasons"] == ["out_of_cards"]


# ---------------------------------------------------------------------- hidden information
def test_redacted_hides_everything_secret():
    g = game([0, 1], advanced=True)
    g.step(0, ("discard", g.hands[0][0]))
    g.step(0, ("play", *next(a for a in g.legal(0) if a[0] == "play")[1:]))
    v = g.redacted(1)
    assert all(c == HIDDEN for c in v.hands[0])
    assert all(c == HIDDEN for c in v.discards[0])
    assert all(c == HIDDEN for c in v.deck) and all(c == HIDDEN for c in v.market_deck)
    assert v.down is not None and v.down[1] == HIDDEN and v.up == g.up
    assert v.hands[1] == g.hands[1]
    mine = g.redacted(0)
    assert mine.down == g.down and mine.discards[0] == g.discards[0]


def test_known_cards_stay_visible():
    g = adv()
    g.tableau[1][MOLE] = 1
    g.pos[1] = 10
    _land_and_take(g, BRAINWASHING)
    if g.phase == Phase.CHOICE:
        g.step(0, ("choose", MOLE))
    v = g.redacted(1)
    assert MOLE in v.hands[0]


def test_card_conservation_in_random_games():
    rng = random.Random(5)
    for adv_mode in (False, True):
        for teams in ([0, 1], [0, 0, 1], [0, 1, 0, 1]):
            for seed in range(40):
                g = Game(teams, advanced=adv_mode, seed=seed)
                while g.result is None:
                    p = rng.choice(g.waiting())
                    g.step(p, rng.choice(g.legal(p)))
                    assert g.agent_total() == TOTAL_AGENTS
                    piles = (g.supply, g.market_deck, g.market_discard, g.owned[0], g.owned[1])
                    market = sum(len(pile) for pile in piles) + (1 if g.choice else 0)
                    assert market == (N_MARKET if adv_mode else 0)


def test_illegal_moves_leave_state_untouched():
    g = game()
    before = (g.hands[0][:], g.deck[:], g.phase)
    with pytest.raises(IllegalMove):
        g.step(0, ("recruit", 0))
    with pytest.raises(IllegalMove):
        g.step(0, ("play", 99, 98))
    assert (g.hands[0], g.deck, g.phase) == before
