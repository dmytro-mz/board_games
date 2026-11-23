from __future__ import annotations

import json
import random
from collections.abc import Iterable

import pytest

from avel.bots import BOT_TYPES, RandomBot
from avel.bots.hero import HeroBot
from avel.game import actions as A
from avel.game import backpack
from avel.game.engine import (
    Game,
    IllegalMove,
    Monster,
    Phase,
    RolledDie,
    clash_outcome,
    distances,
    hero_pool,
)
from avel.game.model import (
    BEAST_TOUGHNESS,
    CASTLE_HEX,
    COIN_SUPPLY,
    EQUIPMENT_TOKENS,
    MAX_TOUGHNESS,
    MONSTER_TYPES,
    MOON_START,
    MOON_TRACK,
    START_HEXES,
    Die,
    Face,
    Kind,
    Moon,
    Size,
    neighbours,
)

MARKET = START_HEXES["marketplace"]
WOODS = START_HEXES["whispering_woods"]


def new_game(players: int = 2, seed: int = 1, crater: str = "easy") -> Game:
    return Game(players, seed=seed, crater=crater)


def rig(game: Game, faces: Iterable[Face]) -> None:
    """Make the next rolls come out as `faces`, in order."""
    queue = list(faces)
    game.roll = lambda die: queue.pop(0)  # type: ignore[method-assign]


def put_monster(game: Game, key: str, at: tuple[int, int], mid: str | None = None) -> Monster:
    mtype = MONSTER_TYPES[key]
    if mid is None:
        stack = game.stacks[mtype.size] if mtype.size != Size.BEAST else ["beast"]
        mid = stack.pop()
    game.monster_keys[mid] = key
    toughness = BEAST_TOUGHNESS[game.n] if mtype.size == Size.BEAST else mtype.toughness
    game.monsters[mid] = Monster(mid, key, at, None, toughness=toughness)
    return game.monsters[mid]


def give_item(game: Game, seat: int, key: str) -> str:
    item = next(i for i in game.bag if game.items[i].key == key)
    game.bag.remove(item)
    game._receive(game.heroes[seat], item)
    return item


def strip(game: Game) -> None:
    """Heroes without gear or coins and an empty board, for controlled scenarios."""
    for hero in game.heroes:
        for item in hero.owned:
            game._remove(hero, item)
            game.bag.append(item)
        game.supply += hero.coins
        hero.coins = 0
    game.monsters.clear()


def coins(game: Game, seat: int, n: int) -> None:
    game.supply -= n
    game.heroes[seat].coins += n


def reveal_all(game: Game) -> None:
    for t in game.tiles.values():
        t.face_up = True


def tile_with(game: Game, key: str) -> tuple[int, int]:
    return next(h for h, t in game.tiles.items() if t.key == key)


def check_invariants(game: Game) -> None:
    assert game.supply + sum(h.coins for h in game.heroes) == COIN_SUPPLY
    owned = [i for h in game.heroes for i in h.owned]
    assert len(owned) == len(set(owned))
    assert sorted(owned + game.bag) == sorted(game.items)
    for hero in game.heroes:
        assert 0 <= hero.toughness <= MAX_TOUGHNESS
        for kind, item in hero.slots.items():
            assert item is None or game.items[item].kind == kind
        if game.phase in (Phase.TURN, Phase.STEER) and not game.tasks:
            assert game.fits(hero), "backpacks always fit between decisions"
    assert game.walls + game.walls_left <= 3
    json.dumps(game.to_json())


# ---------------------------------------------------------------------- setup
@pytest.mark.parametrize("players", [1, 2, 3, 4])
def test_setup(players: int) -> None:
    game = new_game(players)
    assert len(game.heroes) == players
    assert game.moon == MOON_START[players]
    assert game.per_turn == (4 if players == 1 else 2)
    for hero in game.heroes:
        assert hero.at == CASTLE_HEX
        assert hero.coins == 1 and len(hero.owned) == 1
        assert hero.toughness == MAX_TOUGHNESS
    # the start tiles are face up and their lairs are filled
    for h in START_HEXES.values():
        tile = game.tiles[h]
        assert tile.face_up
        assert len(game.monsters_at(h)) == len(tile.type.lairs)
    assert sum(1 for t in game.tiles.values() if t.crater) == 1
    face_down = [t for t in game.tiles.values() if not t.face_up]
    assert face_down and all(not t.to_json().get("key") for t in face_down)
    assert len(game.items) == len(EQUIPMENT_TOKENS)
    check_invariants(game)


def test_only_the_actor_may_act_and_only_legally() -> None:
    game = new_game()
    assert game.legal_actions(1) == []
    with pytest.raises(IllegalMove):
        game.step(1, A.EndTurn())
    with pytest.raises(IllegalMove):
        game.step(0, A.Move((9, 9)))
    with pytest.raises(IllegalMove):
        game.step(0, A.Wall())  # not on the quarry


# ---------------------------------------------------------------------- turns and rounds
def test_two_actions_then_the_next_hero_and_the_moon_moves() -> None:
    game = new_game(2)
    strip(game)
    game.step(0, A.Move(MARKET))
    game.step(0, A.Move(CASTLE_HEX))
    assert game.actions_left == 0
    assert not any(isinstance(a, A.Move) for a in game.legal_actions(0))
    game.step(0, A.EndTurn())
    assert game.current == 1 and game.actions_left == 2
    moon = game.moon
    game.step(1, A.EndTurn())
    assert game.current == 0 and game.round == 2 and game.moon == moon + 1


def test_moving_onto_a_face_down_tile_reveals_it_and_fills_lairs() -> None:
    game = new_game(2, seed=3)
    strip(game)
    hidden = next(n for n in neighbours(MARKET) if n in game.tiles and not game.tiles[n].face_up)
    game.heroes[0].at = MARKET
    events = game.step(0, A.Move(hidden))
    tile = game.tiles[hidden]
    assert tile.face_up
    assert "reveal" in [e["kind"] for e in events]
    assert len(game.monsters_at(hidden)) == len(tile.type.lairs)


def test_shortcuts_link_face_up_shortcut_tiles() -> None:
    game = new_game(2, seed=2)
    strip(game)
    reveal_all(game)
    village = tile_with(game, "abandoned_village")
    game.heroes[0].at = WOODS
    assert A.Move(village) in game.legal_actions(0)
    game.step(0, A.Move(village))
    assert game.heroes[0].at == village


def test_spawn_space_fills_empty_lairs_only_on_tiles_without_monsters() -> None:
    game = new_game(2)
    strip(game)
    game.moon = 0
    assert MOON_TRACK[1] == Moon.SPAWN
    occupied = START_HEXES["glowcap_grove"]
    put_monster(game, "skeleton", occupied)
    game.step(0, A.EndTurn())
    game.step(1, A.EndTurn())
    assert len(game.monsters_at(WOODS)) == 1
    assert len(game.monsters_at(occupied)) == 1  # already had a monster: nothing new


# ---------------------------------------------------------------------- battle
def test_clash_outcome_counts_swords_shields_spells_claws_and_parries() -> None:
    dice = [
        RolledDie(Die.GREEN, Face.SWORD),
        RolledDie(Die.YELLOW, Face.SPELL),
        RolledDie(Die.YELLOW, Face.SPELL),
        RolledDie(Die.BLACK, Face.CLAW),
        RolledDie(Die.BLACK, Face.CLAW),
        RolledDie(Die.PURPLE, Face.PARRY),
    ]
    assert clash_outcome(dice, [], 0) == (0, 0)  # 1 sword - 1 parry; 2 claws - 2 spell shields
    assert clash_outcome(dice, [], 2) == (2, 2)
    assert clash_outcome(dice, [Face.SHIELD], 1) == (1, 0)


def test_hero_pool_respects_equipment_attributes_and_supply() -> None:
    game = new_game()
    for key in ("battle_axe", "long_sword"):
        item = next(i for i in game.items.values() if i.key == key)
        item.upgraded = True
    axe = next(i for i in game.items.values() if i.key == "battle_axe")
    sword = next(i for i in game.items.values() if i.key == "long_sword")
    snapjaw = MONSTER_TYPES["snapjaw"]
    assert sorted(hero_pool([axe, sword], [], snapjaw)) == sorted([Die.GREEN, Die.GREEN, Die.ORANGE, Die.YELLOW])
    # potions add dice, capped by the dice supply
    assert hero_pool([axe], [Die.ORANGE, Die.ORANGE], snapjaw).count(Die.ORANGE) == 2
    # Mycelid Knight: one green die fewer
    assert hero_pool([], [], MONSTER_TYPES["mycelid_knight"]) == [Die.GREEN]
    # Bone Shaman: weapons don't work
    assert Die.ORANGE not in hero_pool([axe], [], MONSTER_TYPES["bone_shaman"])


def start_battle(game: Game, key: str, seat: int = 0) -> Monster:
    hero = game.heroes[seat]
    monster = put_monster(game, key, hero.at)
    game.step(seat, A.Battle(monster.id))
    assert game.phase == Phase.PREPARE
    return monster


def test_slaying_a_monster_pays_the_reward() -> None:
    game = new_game(2)
    strip(game)
    monster = start_battle(game, "bog_serpent")  # toughness 2, 1 black 1 purple, reward 4 coins
    rig(game, [Face.SWORD, Face.SWORD, Face.BLANK, Face.BLANK])
    game.step(0, A.Fight())
    assert game.phase == Phase.CLASH
    events = game.step(0, A.Resolve(0))
    kinds = [e["kind"] for e in events]
    assert "slain" in kinds and "reward" in kinds
    assert monster.id not in game.monsters
    assert game.heroes[0].coins == 4
    assert game.phase == Phase.TURN and game.actions_left == 1
    check_invariants(game)


def test_wounds_stay_on_a_monster_after_retreating() -> None:
    game = new_game(2)
    strip(game)
    monster = start_battle(game, "maw_plant")  # toughness 3
    rig(game, [Face.SWORD, Face.BLANK, Face.BLANK, Face.BLANK])
    game.step(0, A.Fight())
    game.step(0, A.Resolve(0))
    assert game.phase == Phase.AFTER_CLASH
    game.step(0, A.Retreat())
    assert game.phase == Phase.TURN
    assert game.monsters[monster.id].damage == 1


def test_a_battle_has_at_most_three_clashes() -> None:
    game = new_game(2)
    strip(game)
    start_battle(game, "maw_plant")
    rig(game, [Face.BLANK] * 12)
    for _ in range(3):
        game.step(0, A.Fight())
        game.step(0, A.Resolve(0))
    assert game.phase == Phase.TURN and game.battle is None


def test_changing_your_mind_before_rolling_refunds_the_action() -> None:
    game = new_game(2)
    strip(game)
    start_battle(game, "maw_plant")
    assert game.actions_left == 1
    game.step(0, A.Retreat())
    assert game.actions_left == 2


def test_stun_sends_the_hero_home_healed_without_coins_and_loses_an_item() -> None:
    game = new_game(2)
    strip(game)
    hero = game.heroes[0]
    hero.at = WOODS
    hero.toughness = 1
    coins(game, 0, 5)
    sword = give_item(game, 0, "long_sword")
    start_battle(game, "blood_bat")  # 2 black 2 purple
    rig(game, [Face.BLANK, Face.BLANK, Face.CLAW, Face.BLANK, Face.BLANK, Face.BLANK])
    game.step(0, A.Fight())
    events = game.step(0, A.Resolve(0))
    assert "stunned" in [e["kind"] for e in events]
    assert hero.at == CASTLE_HEX and hero.toughness == MAX_TOUGHNESS and hero.coins == 0
    assert game.phase == Phase.STUN_LOSS and game.actor == 0
    assert game.legal_actions(0) == [A.Lose(sword)]
    game.step(0, A.Lose(sword))
    assert sword in game.bag and game.current == 1  # a stun ends the turn
    check_invariants(game)


def test_one_time_effects_reroll_and_bonus() -> None:
    game = new_game(2)
    strip(game)
    dagger = give_item(game, 0, "dagger")  # basic: reroll 1 green die
    hand_axe = give_item(game, 0, "hand_axe")  # backpack only: no effect
    assert game.heroes[0].slots[Kind.WEAPON] == dagger and hand_axe in game.heroes[0].pack
    start_battle(game, "snapjaw")
    rig(game, [Face.BLANK, Face.BLANK, Face.BLANK, Face.BLANK, Face.BLANK, Face.BLANK, Face.SWORD])
    game.step(0, A.Fight())
    legal = game.legal_actions(0)
    assert A.Reroll(dagger, (0,)) in legal and A.Reroll(dagger, (1,)) in legal
    assert not any(isinstance(a, A.Bonus) for a in legal)
    game.step(0, A.Reroll(dagger, (1,)))
    assert game.battle is not None and game.battle.dice[1].face == Face.SWORD
    assert not any(isinstance(a, A.Reroll) for a in game.legal_actions(0)), "once per battle"
    game.step(0, A.Resolve(0))
    assert "snapjaw" not in [m.key for m in game.monsters.values()]


def test_bonus_only_against_its_colour() -> None:
    game = new_game(2)
    strip(game)
    sword = give_item(game, 0, "long_sword")  # +1 sword against green monsters
    start_battle(game, "skeleton")  # green
    rig(game, [Face.BLANK] * 5)
    game.step(0, A.Fight())
    assert A.Bonus(sword) in game.legal_actions(0)
    game.step(0, A.Bonus(sword))
    assert game.battle is not None and game.battle.bonus == [Face.SWORD]


def test_battle_elixir_adds_a_die_for_the_whole_battle() -> None:
    game = new_game(2)
    strip(game)
    elixir = give_item(game, 0, "orange_elixir")
    start_battle(game, "maw_plant")
    assert A.Drink(elixir) in game.legal_actions(0)
    game.step(0, A.Drink(elixir))
    assert elixir in game.bag
    game.step(0, A.Fight())
    assert game.battle is not None and [d.die for d in game.battle.dice].count(Die.ORANGE) == 1


def test_dragon_forbids_elixirs() -> None:
    game = new_game(2)
    strip(game)
    give_item(game, 0, "orange_elixir")
    start_battle(game, "dragon")
    assert not any(isinstance(a, A.Drink) for a in game.legal_actions(0))


# ---------------------------------------------------------------------- backpack and rewards
def test_rewards_that_dont_fit_must_be_repacked() -> None:
    game = new_game(2)
    strip(game)
    hero = game.heroes[0]
    coins(game, 0, 12)  # a full backpack of coins
    assert game.fits(hero)
    give_item(game, 0, "long_sword")  # equipped: fine
    game._reward(hero, 0, 1, 0, "test")
    game._settle()
    assert game.phase == Phase.OVERFLOW and game.actor == 0
    assert A.Done() not in game.legal_actions(0)
    while game.phase == Phase.OVERFLOW:
        game.step(0, A.Discard(coins=1))
    assert game.phase == Phase.TURN and hero.coins < 12 and hero.pack
    check_invariants(game)


def test_backpack_arrangement_matches_fits() -> None:
    rng = random.Random(5)
    kinds = [Kind.WEAPON, Kind.SHIELD, Kind.HELMET, Kind.ELIXIR]
    for _ in range(300):
        pack = [rng.choice(kinds) for _ in range(rng.randrange(0, 5))]
        n = rng.randrange(0, 13)
        placements = backpack.arrange(pack, n)
        assert (placements is not None) == backpack.fits(pack, n)


def test_market_sells_and_buys() -> None:
    game = new_game(2)
    strip(game)
    hero = game.heroes[0]
    hero.at = MARKET
    axe = give_item(game, 0, "battle_axe")
    coins(game, 0, 1)
    assert A.Market((axe,), 1) in game.legal_actions(0)
    game.step(0, A.Market((axe,), 1))
    assert axe in game.bag
    assert hero.coins == 0 and len(hero.owned) == 1


def test_walls_seals_and_traps() -> None:
    game = new_game(2)
    strip(game)
    reveal_all(game)
    hero = game.heroes[0]
    coins(game, 0, 12)
    hero.at = tile_with(game, "quarry")
    game.step(0, A.Wall())
    assert game.walls == 1 and game.walls_left == 2 and hero.coins == 9
    hero.at = tile_with(game, "stone_circles")
    seal = next(a for a in game.legal_actions(0) if isinstance(a, A.Seal))
    game.step(0, A.Seal(seal.at, seal.lair))
    assert game.tiles[seal.at].seals[seal.lair] and game.seals_left == 2
    game.step(0, A.EndTurn())
    game.step(1, A.EndTurn())
    hero.at = tile_with(game, "elven_camp")
    assert not any(isinstance(a, A.Trap) and a.level == 7 for a in game.legal_actions(0)), "6 coins"
    trap = next(a for a in game.legal_actions(0) if isinstance(a, A.Trap) and a.level == 5)
    game.step(0, trap)
    assert game.traps[5] == trap.at and game.tiles[trap.at].trap == 5 and hero.coins == 1
    check_invariants(game)


def test_seals_and_traps_run_out_with_the_moon() -> None:
    game = new_game(2)
    strip(game)
    reveal_all(game)
    coins(game, 0, 12)
    game.moon = 11
    game.heroes[0].at = tile_with(game, "stone_circles")
    assert not any(isinstance(a, A.Seal) for a in game.legal_actions(0))
    game.heroes[0].at = tile_with(game, "elven_camp")
    assert any(isinstance(a, A.Trap) for a in game.legal_actions(0))
    game.moon = 12
    assert not any(isinstance(a, A.Trap) for a in game.legal_actions(0))


def test_wish_outcomes() -> None:
    game = new_game(2)
    strip(game)
    reveal_all(game)
    hero = game.heroes[0]
    hero.at = tile_with(game, "wishing_lake")
    coins(game, 0, 2)
    rig(game, [Face.SWORD, Face.SWORD])
    game.step(0, A.Wish())
    assert hero.coins == 1 + 4
    rig(game, [Face.BLANK, Face.BLANK, Face.SHIELD, Face.SWORD])  # nothing, then the free reroll
    game.step(0, A.Wish())
    assert len(hero.owned) == 1


def test_trading_items_and_coins_between_heroes_on_one_tile() -> None:
    game = new_game(2)
    strip(game)
    coins(game, 0, 3)
    sword = give_item(game, 0, "long_sword")
    legal = game.legal_actions(0)
    assert A.Give(1, item=sword) in legal and A.Give(1, coins=3) in legal
    game.step(0, A.Give(1, item=sword))
    game.step(0, A.Give(1, coins=2))
    assert game.heroes[1].slots[Kind.WEAPON] == sword and game.heroes[1].coins == 2
    assert game.actions_left == 2, "trading is free"
    game.heroes[1].at = MARKET
    assert not any(isinstance(a, (A.Give, A.Take)) for a in game.legal_actions(0))


# ---------------------------------------------------------------------- Black Moon and the march
def black_moon(game: Game) -> list[dict]:
    game.moon = len(MOON_TRACK) - 2
    events = []
    for seat in range(game.n):
        events += game.step(seat, A.EndTurn())
    return events


def test_black_moon_reveals_everything_and_the_beast_appears() -> None:
    game = new_game(2, crater="difficult")
    strip(game)
    crater = next(h for h, t in game.tiles.items() if t.crater)
    events = black_moon(game)
    kinds = [e["kind"] for e in events]
    assert "black_moon" in kinds and "beast" in kinds
    assert all(t.face_up for t in game.tiles.values())
    beast = game.monsters["beast"]
    assert beast.at == crater and beast.toughness == BEAST_TOUGHNESS[2]
    assert game.beast_out and not any(t.crater for t in game.tiles.values())
    assert kinds.count("crater_roll") == len(game.crater.monsters[2]) > 0


def test_every_monster_marches_one_tile_towards_the_castle() -> None:
    game = new_game(2)
    strip(game)
    black_moon(game)
    game.walls = 3
    game.walls_left = 0
    dist = distances(game.tiles)
    before = {m.id: dist[m.at] for m in game.monsters.values()}
    for seat in range(2):
        game.step(seat, A.EndTurn())
    while game.phase == Phase.STEER:
        game.step(game.actor, game.legal_actions(game.actor)[0])
    for mid, d in before.items():
        if mid in game.monsters:
            assert dist[game.monsters[mid].at] == max(1, d - 1)
    assert game.march_rounds == 1


def test_walls_hold_monsters_back_and_the_beast_breaks_them_all() -> None:
    game = new_game(2)
    strip(game)
    reveal_all(game)
    game.beast_out = True
    game.walls, game.walls_left = 3, 0
    put_monster(game, "skeleton", WOODS)
    game._start_march()
    game._settle()
    assert game.walls == 2 and game.phase == Phase.TURN
    assert game.monsters_at(WOODS), "the monster stays on its tile"
    put_monster(game, "beast", MARKET, mid="beast")
    game._start_march()
    game._settle()
    assert game.walls == 0
    game._start_march()
    game._settle()
    assert game.phase == Phase.GAME_OVER and game.result is not None and not game.result.won


def test_steering_when_several_shortest_paths_exist() -> None:
    game = new_game(2)
    strip(game)
    reveal_all(game)
    game.beast_out = True
    dist = distances(game.tiles)
    two_ways = next(
        h for h in game.tiles if sum(1 for n in neighbours(h) if dist.get(n) == dist[h] - 1) > 1 and dist[h] > 1
    )
    m = put_monster(game, "skeleton", two_ways)
    game.start_seat = game.current = 1
    game._start_march()
    game._settle()
    assert game.phase == Phase.STEER and game.actor == 1
    choice = game.legal_actions(1)[-1]
    game.step(1, choice)
    assert game.monsters[m.id].at == choice.to


def test_traps_hurt_the_beast() -> None:
    game = new_game(2)
    strip(game)
    reveal_all(game)
    game.beast_out = True
    beast = put_monster(game, "beast", (2, 4), mid="beast")
    dist = distances(game.tiles)
    nxt = [n for n in neighbours(beast.at) if dist.get(n) == dist[beast.at] - 1]
    for h in nxt:
        game.tiles[h].trap = 7
    game.traps[7] = nxt[0]
    rig(game, [Face.SWORD] * 10)
    game._start_march()
    game._settle()
    while game.phase == Phase.STEER:
        game.step(game.actor, game.legal_actions(game.actor)[0])
    assert beast.damage >= 4


def test_slaying_every_monster_including_the_beast_wins() -> None:
    game = new_game(2)
    strip(game)
    game.beast_out = True
    beast = put_monster(game, "beast", CASTLE_HEX, mid="beast")
    beast.damage = beast.toughness - 1
    game.step(0, A.Battle("beast"))
    rig(game, [Face.SWORD, Face.SWORD] + [Face.BLANK] * 5)
    game.step(0, A.Fight())
    events = game.step(0, A.Resolve(0))
    assert game.phase == Phase.GAME_OVER and game.result is not None and game.result.won
    assert events[-1]["kind"] == "game_over"


def test_the_beast_dying_with_monsters_left_is_not_yet_victory() -> None:
    game = new_game(2)
    strip(game)
    game.beast_out = True
    beast = put_monster(game, "beast", CASTLE_HEX, mid="beast")
    put_monster(game, "skeleton", WOODS)
    beast.damage = beast.toughness - 1
    game.step(0, A.Battle("beast"))
    rig(game, [Face.SWORD, Face.SWORD] + [Face.BLANK] * 5)
    game.step(0, A.Fight())
    game.step(0, A.Resolve(0))
    assert game.phase == Phase.TURN and game.result is None


# ---------------------------------------------------------------------- whole games
def play(game: Game, bots: list, limit: int = 20_000) -> None:
    for _ in range(limit):
        if game.phase == Phase.GAME_OVER:
            return
        seat = game.actor
        assert seat is not None
        legal = game.legal_actions(seat)
        assert legal, f"no legal action in {game.phase}"
        for a in legal:
            assert A.from_json(json.loads(json.dumps(A.to_json(a)))) == a
        action = bots[seat].act(game.view(seat))
        assert action in legal
        game.step(seat, action)
        check_invariants(game)
    raise AssertionError("game did not finish")


@pytest.mark.parametrize("players", [1, 2, 3, 4])
@pytest.mark.parametrize("crater", ["easy", "moderate", "difficult"])
def test_random_games_finish(players: int, crater: str) -> None:
    for seed in range(4):
        game = new_game(players, seed=seed, crater=crater)
        play(game, [RandomBot(seed * 10 + i) for i in range(players)])
        assert game.result is not None


@pytest.mark.parametrize("players", [1, 2, 3, 4])
def test_hero_bot_games_finish(players: int) -> None:
    results = []
    for seed in range(3):
        game = new_game(players, seed=100 + seed)
        play(game, [HeroBot(seed=seed * 7 + i, runs=30) for i in range(players)])
        assert game.result is not None
        results.append(game.result)
    assert all(r.reason in ("victory", "castle") for r in results)


def test_bot_registry() -> None:
    assert {"knight", "squire"} <= set(BOT_TYPES)
    for bt in BOT_TYPES.values():
        bot = bt.make(1)
        game = new_game(2)
        assert bot.act(game.view(0)) in game.legal_actions(0)


def test_same_seed_same_game() -> None:
    def run(seed: int) -> dict:
        game = new_game(2, seed=seed)
        play(game, [RandomBot(1), RandomBot(2)])
        return game.to_json()

    assert run(7) == run(7)
