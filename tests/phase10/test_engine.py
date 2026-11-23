from __future__ import annotations

import random
from collections import Counter

import pytest
from phase10_helpers import ids, rig

from phase10.bots import make_bot
from phase10.game.actions import BadAction, Discard, DrawDeck, DrawDiscard, GroupSpec, Hit, LayDown, from_json, to_json
from phase10.game.engine import Game, IllegalMove, RulesConfig, Step
from phase10.game.model import PHASES, Card, GroupKind, Kind, make_deck
from phase10.game.rules import Group, InvalidGroup, color_of, run_lows, set_value

SET, RUN, COLOR = GroupKind.SET, GroupKind.RUN, GroupKind.COLOR


def hand_of(specs: str) -> list[Card]:
    game = Game(2, seed=0)
    return rig(game, 0, specs)


def turn_to(game: Game, seat: int) -> None:
    game.current = seat
    game.step_ = Step.DRAW
    game.skipped.clear()
    game.skip_spent.clear()


# ---------------------------------------------------------------------- the deck and the phases
def test_deck_has_108_cards():
    deck = make_deck()
    assert len(deck) == 108
    kinds = Counter(c.kind for c in deck)
    assert kinds == {Kind.NUMBER: 96, Kind.WILD: 8, Kind.SKIP: 4}
    numbers = Counter((c.color, c.value) for c in deck if c.natural)
    assert len(numbers) == 48 and set(numbers.values()) == {2}
    assert len({c.id for c in deck}) == 108


def test_card_points():
    deck = make_deck()
    pts = {c.label(): c.points for c in deck}
    assert pts["red 1"] == pts["blue 9"] == 5
    assert pts["green 10"] == pts["yellow 12"] == 10
    assert pts["Skip"] == 15 and pts["Wild"] == 25


def test_ten_phases():
    assert len(PHASES) == 10
    assert [(r.kind, r.size) for r in PHASES[0]] == [(SET, 3), (SET, 3)]
    assert [(r.kind, r.size) for r in PHASES[1]] == [(SET, 3), (RUN, 4)]
    assert [(r.kind, r.size) for r in PHASES[7]] == [(COLOR, 7)]
    assert [(r.kind, r.size) for r in PHASES[9]] == [(SET, 5), (SET, 3)]


def test_deal():
    game = Game(4, seed=1)
    assert all(len(h) == 10 for h in game.hands)
    assert len(game.discard) == 1 and len(game.draw) == 108 - 41
    assert game.current == (game.dealer + 1) % 4 or game.discard[-1].skip
    assert game.step == Step.DRAW and game.card_count() == 108
    with pytest.raises(ValueError):
        Game(1)
    with pytest.raises(ValueError):
        Game(7)


def test_hands_are_not_sorted():
    game = Game(2, seed=3)
    hand = game.hands[0]
    values = [c.value for c in hand]
    assert values != sorted(values) or [c.color for c in hand] != sorted(c.color for c in hand if c.color)


# ---------------------------------------------------------------------- group validation
def test_sets():
    assert set_value(hand_of("r7 b7 g7"), 3) == 7
    assert set_value(hand_of("r7 w b7 w"), 3) == 7
    with pytest.raises(InvalidGroup, match="same number"):
        set_value(hand_of("r7 b7 g8"), 3)
    with pytest.raises(InvalidGroup, match="at least 3"):
        set_value(hand_of("r7 b7"), 3)
    with pytest.raises(InvalidGroup, match="number card"):
        set_value(hand_of("w w w"), 3)
    with pytest.raises(InvalidGroup, match="Skip"):
        set_value(hand_of("r7 b7 s"), 3)


def test_runs():
    assert run_lows(hand_of("r3 b4 g5 y6"), 4) == [3]
    assert run_lows(hand_of("r3 w g5 y6"), 4) == [3]
    assert run_lows(hand_of("w r3 b4 g5"), 4) == [2, 3]  # the wild may be a 2 or a 6
    assert run_lows(hand_of("w r1 b2 g3"), 4) == [1]  # nothing below 1
    assert run_lows(hand_of("r12 w b10 g9"), 4) == [9]
    with pytest.raises(InvalidGroup, match="same number twice"):
        run_lows(hand_of("r3 b3 g4 y5"), 4)
    with pytest.raises(InvalidGroup, match="gaps"):
        run_lows(hand_of("r3 b4 g7 y8"), 4)
    with pytest.raises(InvalidGroup, match="at least 4"):
        run_lows(hand_of("r3 b4 g5"), 4)


def test_color_groups():
    assert color_of(hand_of("r1 r3 r5 r7 r9 r11 w"), 7) == "red"
    with pytest.raises(InvalidGroup, match="same color"):
        color_of(hand_of("r1 r3 r5 r7 r9 r11 b2"), 7)


def test_group_build_orders_a_run_and_places_wilds():
    cards = hand_of("g5 w r3 y6")
    g = Group.build(0, 0, RUN, cards, 4, None)
    assert (g.low, g.high) == (3, 6)
    assert g.as_values() == [3, 4, 5, 6]
    assert [c.wild for c in g.cards] == [False, True, False, False]
    with pytest.raises(InvalidGroup, match="only make the run"):
        Group.build(0, 0, RUN, hand_of("w r3 b4 g5"), 4, 7)
    g2 = Group.build(0, 0, RUN, hand_of("w r3 b4 g5"), 4, 2)
    assert (g2.low, g2.high) == (2, 5)


def test_hitting_groups():
    s = Group.build(0, 0, SET, hand_of("r7 b7 g7"), 3)
    more = hand_of("y7 w r8 s")
    assert s.ends_for(more[0]) == ["any"] and s.ends_for(more[1]) == ["any"]
    assert s.ends_for(more[2]) == [] and s.ends_for(more[3]) == []
    run = Group.build(1, 0, RUN, hand_of("r3 b4 g5 y6"), 4)
    extra = hand_of("r2 r7 w r9")
    assert run.ends_for(extra[0]) == ["low"] and run.ends_for(extra[1]) == ["high"]
    assert run.ends_for(extra[2]) == ["low", "high"] and run.ends_for(extra[3]) == []
    assert run.add(extra[2], "low") == "low" and run.low == 2
    with pytest.raises(InvalidGroup):
        run.add(extra[0])  # 2 is now taken by the wild
    full = Group.build(2, 0, RUN, hand_of("r1 b2 g3 y4 r5 b6 g7 y8 r9 b10 g11 y12"), 9)
    with pytest.raises(InvalidGroup):
        full.add(hand_of("w")[0])


# ---------------------------------------------------------------------- turns
def test_draw_then_discard():
    game = Game(3, seed=2)
    seat = game.current
    with pytest.raises(IllegalMove, match="Draw a card first"):
        game.play(seat, Discard(game.hands[seat][0].id))
    with pytest.raises(IllegalMove, match="not your turn"):
        game.play((seat + 1) % 3, DrawDeck())
    game.play(seat, DrawDeck())
    assert len(game.hands[seat]) == 11
    with pytest.raises(IllegalMove, match="already drew"):
        game.play(seat, DrawDeck())
    card = game.hands[seat][-1]
    game.play(seat, Discard(card.id))
    assert game.discard[-1] == card and game.current == (seat + 1) % 3 and game.step == Step.DRAW


def test_take_the_discard_but_never_a_skip():
    game = Game(2, seed=4)
    rig(game, game.current, "r1 r2 r3 r4 r5 r6 r7 r8 r9 r10", top="b5")
    seat = game.current
    game.play(seat, DrawDiscard())
    assert game.hands[seat][-1].label() == "blue 5"
    turn_to(game, seat)
    rig(game, seat, "r1 r2 r3", top="s")
    assert not game.options(seat)["draw_discard"]
    with pytest.raises(IllegalMove, match="Skip can't be picked"):
        game.play(seat, DrawDiscard())


def test_lay_down_and_hit():
    game = Game(2, seed=5)
    seat = game.current
    hand = rig(game, seat, "r7 b7 g7 y9 r9 w r1 b2 g3 y4")
    game.play(seat, DrawDeck())
    with pytest.raises(IllegalMove, match="before adding"):
        game.play(seat, Hit(0, hand[0].id))
    with pytest.raises(IllegalMove, match="needs 2 group"):
        game.play(seat, LayDown((GroupSpec(SET, ids(hand, 0, 1, 2)),)))
    with pytest.raises(IllegalMove):
        game.play(seat, LayDown((GroupSpec(SET, ids(hand, 0, 1, 2)), GroupSpec(SET, ids(hand, 3, 4, 6)))))
    assert not game.laid[seat] and len(game.hands[seat]) == 11  # a failed lay-down changes nothing
    events = game.play(seat, LayDown((GroupSpec(SET, ids(hand, 0, 1, 2)), GroupSpec(SET, ids(hand, 3, 4, 5)))))
    assert events[0]["kind"] == "lay_down" and game.laid[seat]
    assert len(game.groups) == 2 and len(game.hands[seat]) == 5
    with pytest.raises(IllegalMove, match="already laid"):
        game.play(seat, LayDown((GroupSpec(SET, ids(hand, 6, 7, 8)), GroupSpec(SET, ids(hand, 6, 7, 8)))))
    with pytest.raises(IllegalMove):
        game.play(seat, Hit(game.groups[0].id, hand[6].id))  # a 1 doesn't fit the 7s
    rig_more = next(c for c in game.deck if c.natural and c.value == 7 and c not in game.groups[0].cards)
    for pile in (*game.hands, game.draw, game.discard):
        if rig_more in pile:
            pile.remove(rig_more)
    game.hands[seat].append(rig_more)
    game.draw.append(game.hands[seat].pop(0))
    game.play(seat, Hit(game.groups[0].id, rig_more.id))
    assert len(game.groups[0].cards) == 4 and game.card_count() == 108


def test_groups_can_be_given_in_any_order():
    game = Game(2, seed=6)
    seat = game.current
    game.phases[seat] = 2  # set of 3 + run of 4
    hand = rig(game, seat, "r1 b2 g3 y4 r9 b9 g9 y11 y12 r12")
    game.play(seat, DrawDeck())
    game.play(seat, LayDown((GroupSpec(RUN, ids(hand, 0, 1, 2, 3)), GroupSpec(SET, ids(hand, 4, 5, 6)))))
    assert sorted(g.kind for g in game.groups) == sorted([SET, RUN]) and game.laid[seat]


def test_hit_on_another_players_group_in_the_same_turn():
    game = Game(2, seed=7)
    a = game.current
    b = 1 - a
    game.laid[b] = True
    other = rig(game, b, "r5 b5 g5 y1")
    game.groups.append(Group.build(50, b, SET, other[:3], 3))
    game.hands[b] = [other[3]]
    game._next_group = 51
    hand = rig(game, a, "r7 b7 g7 y8 r8 b8 y5")
    game.play(a, DrawDeck())
    game.play(a, LayDown((GroupSpec(SET, ids(hand, 0, 1, 2)), GroupSpec(SET, ids(hand, 3, 4, 5)))))
    game.play(a, Hit(50, hand[6].id))
    assert len(game.group(50).cards) == 4


def test_going_out_by_discarding_scores_the_others():
    game = Game(3, seed=8)
    seat = game.current
    game.laid[seat] = True
    rig(game, seat, "r3")
    nxt = (seat + 1) % 3
    rig(game, nxt, "w s r10 b1")
    game.play(seat, DrawDeck())
    drawn = game.hands[seat][-1]
    game.hands[seat].remove(drawn)
    game.draw.append(drawn)
    events = game.play(seat, Discard(game.hands[seat][0].id))
    kinds = [e["kind"] for e in events]
    assert "out" in kinds and "hand_over" in kinds
    assert game.step == Step.HAND_OVER
    assert game.scores[nxt] == 25 + 15 + 10 + 5 and game.scores[seat] == 0
    assert game.phases[seat] == 2 and game.phases[nxt] == 1
    game.next_hand()
    assert game.hand_no == 2 and all(len(h) == 10 for h in game.hands) and game.card_count() == 108


def test_going_out_by_laying_down_everything():
    game = Game(2, seed=9)
    seat = game.current
    game.phases[seat] = 4  # run of 7
    hand = rig(game, seat, "r1 b2 g3 y4 r5 b6 w")
    game.step_ = Step.PLAY  # as if the 7th card was just drawn
    events = game.play(seat, LayDown((GroupSpec(RUN, tuple(c.id for c in hand), low=1),)))
    assert events[-1]["kind"] == "hand_over" and game.history[-1].went_out == seat


def test_skip_is_aimed_and_lies_in_front_of_the_target():
    game = Game(3, seed=10)
    seat = game.current
    turn_to(game, seat)
    hand = rig(game, seat, "s s r1 r2")
    game.play(seat, DrawDeck())
    with pytest.raises(IllegalMove, match="Choose a player"):
        game.play(seat, Discard(hand[0].id))
    with pytest.raises(IllegalMove, match="can't be skipped"):
        game.play(seat, Discard(hand[0].id, target=seat))
    top = game.discard[-1]
    target = (seat + 2) % 3
    events = game.play(seat, Discard(hand[0].id, target=target))
    assert events[0]["target"] == target and target in game.skipped
    # The Skip lies in front of the target, not on the discard pile.
    assert game.skip_cards[target] is hand[0] and game.discard[-1] is top and game.card_count() == 108
    nxt = (seat + 1) % 3
    assert game.skip_targets(nxt) == [seat]  # not the player with a Skip in front of them
    game.play(nxt, DrawDeck())
    events = game.play(nxt, Discard(game.hands[nxt][-1].id))
    # On the target's turn the Skip goes onto the discard pile and play moves on.
    assert {"kind": "skipped", "seat": target, "card": hand[0].to_json()} in events and game.current == seat
    assert game.discard[-1] is hand[0] and not game.skip_cards and game.card_count() == 108
    game.play(seat, DrawDeck())
    assert game.options(seat)["skip_targets"] == [nxt, target]  # the target can be skipped again right away
    events = game.play(seat, Discard(hand[1].id, target=target))
    assert [e["seat"] for e in events if e["kind"] == "skipped"] == [] and game.current == nxt


def test_skip_cooldown_house_rule():
    for cooldown, targets in ((False, [1]), (True, [])):
        game = Game(2, seed=17, rules=RulesConfig(skip_cooldown=cooldown))
        turn_to(game, 0)
        hand = rig(game, 0, "s s r1 r2 r3")
        game.play(0, DrawDeck())
        game.play(0, Discard(hand[0].id))  # 1 loses its turn
        assert game.current == 0 and game.discard[-1] is hand[0]
        game.play(0, DrawDeck())
        assert game.options(0)["skip_targets"] == targets
        events = game.play(0, Discard(hand[1].id))
        if cooldown:
            # A Skip with nobody to skip is just a discard; after 1 plays a turn it can be skipped again.
            assert events[0]["target"] is None and game.current == 1
            game.play(1, DrawDeck())
            game.play(1, Discard(game.hands[1][-1].id))
            game.play(0, DrawDeck())
            assert game.options(0)["skip_targets"] == [1]
        else:
            assert events[0]["target"] == 1 and game.current == 0


def _finish_last_phase(game: Game, seat: int, discard_last: bool) -> list[dict]:
    """Rig `seat` to lay down phase 1 (the last phase of a one-phase game) this turn."""
    turn_to(game, seat)
    hand = rig(game, seat, "r7 b7 g7 r9 b9 g9 y1" if discard_last else "r7 b7 g7 r9 b9 g9 y1 y2")
    game.play(seat, DrawDeck())
    game.draw.append(game.hands[seat].pop())
    game.play(seat, LayDown((GroupSpec(SET, ids(hand, 0, 1, 2)), GroupSpec(SET, ids(hand, 3, 4, 5)))))
    return game.play(seat, Discard(hand[6].id))


def test_tie_on_points_is_replayed_by_the_tied_players():
    game2 = Game(3, seed=20, rules=RulesConfig(last_phase=1))
    a = game2.current
    b, c = (a + 1) % 3, (a + 2) % 3
    game2.laid[a] = True
    game2.scores = [0, 0, 0]
    game2.scores[b] = 5  # a's 5 points left in hand will tie b
    rig(game2, a, "r3")
    events = _finish_last_phase(game2, b, discard_last=True)
    assert game2.scores[a] == game2.scores[b] == 5
    assert game2.step == Step.HAND_OVER and {"kind": "tiebreak", "seats": sorted([a, b])} in events
    assert game2.result is None and game2.history[-1].tiebreak == sorted([a, b])
    game2.next_hand()
    assert game2.active[c] is False and game2.hands[c] == [] and len(game2.hands[a]) == len(game2.hands[b]) == 10
    assert game2.current in (a, b) and c not in game2.skip_targets(game2.current)
    assert game2.phases[a] == game2.phases[b] == 1 and game2.card_count() == 108
    # The first of the tied players to go out wins.
    winner = game2.current
    game2.laid[winner] = True
    rig(game2, winner, "r4")
    game2.play(winner, DrawDeck())
    game2.draw.append(game2.hands[winner].pop())
    events = game2.play(winner, Discard(game2.hands[winner][0].id))
    assert game2.step == Step.GAME_OVER and game2.result.winners == [winner]
    assert sorted(game2.result.finishers) == sorted([a, b])


def test_two_players_skip_targets_the_other_player():
    game = Game(2, seed=11)
    seat = game.current
    hand = rig(game, seat, "s r1 r2")
    game.play(seat, DrawDeck())
    game.play(seat, Discard(hand[0].id))
    assert game.current == seat  # the opponent lost their turn


def test_starting_skip_skips_the_first_player():
    for seed in range(400):
        game = Game(3, seed=seed)
        if game.discard[0].skip:
            first = (game.dealer + 1) % 3
            assert game.current == (first + 1) % 3
            break
    else:
        pytest.fail("no deal started with a Skip")


def test_reshuffle_when_the_deck_runs_out():
    game = Game(2, seed=12)
    seat = game.current
    game.discard = game.draw + game.discard
    game.draw = []
    top = game.discard[-1]
    events = game.play(seat, DrawDeck())
    assert events[0]["kind"] == "reshuffle" and game.discard == [top]
    assert game.card_count() == 108


def test_dry_hand_ends_without_a_winner():
    game = Game(2, seed=13)
    skip = next(c for c in game.deck if c.skip)
    for pile in (*game.hands, game.draw, game.discard):
        if skip in pile:
            pile.remove(skip)
    game.hands[0].extend(game.draw + game.discard)
    game.draw, game.discard = [], [skip]  # nothing to draw: only a Skip on the discard pile
    assert game.card_count() == 108
    events: list[dict] = []
    game._begin_turn(events)
    assert {"kind": "dry"} in events and game.step == Step.HAND_OVER
    assert game.history[-1].went_out is None


def test_arrange_reorders_only_the_same_cards():
    game = Game(2, seed=14)
    hand = game.hands[0]
    order = [c.id for c in reversed(hand)]
    game.arrange(0, order)
    assert [c.id for c in game.hands[0]] == order
    with pytest.raises(IllegalMove):
        game.arrange(0, order[:-1])
    with pytest.raises(IllegalMove):
        game.arrange(0, [*order[:-1], game.hands[1][0].id])


def test_drawn_card_goes_to_the_end_of_the_hand():
    game = Game(2, seed=15)
    seat = game.current
    before = [c.id for c in game.hands[seat]]
    game.play(seat, DrawDeck())
    assert [c.id for c in game.hands[seat]][:-1] == before


# ---------------------------------------------------------------------- the end of the game
def test_finishing_the_last_phase_ends_the_game_and_lowest_score_wins():
    game = Game(3, seed=16, rules=RulesConfig(last_phase=1))
    seat = game.current
    hand = rig(game, seat, "r7 b7 g7 r9 b9 g9 y1")
    game.scores = [0, 0, 0]
    game.scores[seat] = 50
    game.play(seat, DrawDeck())
    game.draw.append(game.hands[seat].pop())
    game.play(seat, LayDown((GroupSpec(SET, ids(hand, 0, 1, 2)), GroupSpec(SET, ids(hand, 3, 4, 5)))))
    events = game.play(seat, Discard(hand[6].id))
    assert events[-1]["kind"] == "game_over"
    assert game.step == Step.GAME_OVER and game.result is not None
    assert game.result.winners == [seat] and game.result.finishers == [seat]
    with pytest.raises(IllegalMove):
        game.next_hand()


def test_rules_config_is_checked():
    with pytest.raises(ValueError):
        RulesConfig(last_phase=11)
    with pytest.raises(ValueError):
        RulesConfig(hand_size=0)


def test_card_conservation_over_random_play():
    for seed in range(6):
        rng = random.Random(seed)
        game = Game(rng.randint(2, 6), seed=seed)
        bots = [make_bot("pro", seed * 10 + i) for i in range(game.n)]
        for _ in range(4000):
            if game.step == Step.GAME_OVER:
                break
            if game.step == Step.HAND_OVER:
                game.next_hand()
                continue
            seat = game.current
            if rng.random() < 0.05:
                hand = [c.id for c in game.hands[seat]]
                rng.shuffle(hand)
                game.arrange(seat, hand)
            game.play(seat, bots[seat].act(game.view(seat)))
            assert game.card_count() == 108
            assert len({c.id for h in game.hands for c in h}) == sum(len(h) for h in game.hands)


# ---------------------------------------------------------------------- the wire format
def test_actions_round_trip():
    acts = [
        DrawDeck(),
        DrawDiscard(),
        LayDown((GroupSpec(SET, (1, 2, 3)), GroupSpec(RUN, (4, 5, 6, 7), low=3))),
        Hit(3, 9, "low"),
        Discard(5),
        Discard(104, target=2),
    ]
    for a in acts:
        assert from_json(to_json(a)) == a
    for bad in [
        {},
        {"type": "fly"},
        {"type": "discard"},
        {"type": "lay_down", "groups": "x"},
        {"type": "hit", "group": "a", "card": 1},
    ]:
        with pytest.raises(BadAction):
            from_json(bad)
