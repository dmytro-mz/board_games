"""The Chronicles of Avel state machine: `Game.step(seat, action) -> events`, `Game.legal_actions(seat)`,
`Game.view(seat)`.

`legal_actions` is the single source of truth: `step` rejects anything it doesn't list, so an illegal action
never changes the state. Everything random goes through `Game.rng`.
"""

from __future__ import annotations

import copy
import random
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from typing import Any

from avel.game import actions as A
from avel.game import backpack
from avel.game.actions import Action
from avel.game.model import (
    ACTIONS_PER_TURN,
    ATTRIBUTE_BLOCKS,
    BASE_GREEN,
    BEAST,
    BEAST_TOUGHNESS,
    BIG_MONSTERS,
    CASTLE_HEX,
    CLASHES,
    COIN_SUPPLY,
    CRATER_HEX,
    CRATERS,
    DICE_SUPPLY,
    DIE_FACES,
    EQUIPMENT_TOKENS,
    EQUIPMENT_TYPES,
    EXTRA_HEXES,
    HERO_DICE,
    LAND_HEXES,
    LAST_SEAL_SPACE,
    LAST_TRAP_SPACE,
    MAX_TOUGHNESS,
    MONSTER_TYPES,
    MOON_START,
    MOON_TRACK,
    PRICE,
    REST_HEAL,
    SEALS,
    SELL_PRICE,
    SLOTS,
    SMALL_MONSTERS,
    SOLO_ACTIONS,
    START_HEXES,
    TILE_TYPES,
    TRAPS,
    WALLS,
    WISH_COINS,
    WISH_COST,
    WORK_COINS,
    Attribute,
    Crater,
    Die,
    Effect,
    EffectKind,
    EquipmentType,
    Face,
    Hex,
    Kind,
    MonsterType,
    Moon,
    Size,
    Symbol,
    TileType,
    neighbours,
)
from avel.game.model import Action as TileAction

Event = dict[str, Any]
HERO_COLORS = ("red", "blue", "green", "yellow")
MAX_ROUNDS = 80  # safety stop; real games end long before


class IllegalMove(Exception):
    pass


class Phase(StrEnum):
    TURN = "turn"  # the current hero picks actions (and free moves: equip, trade, healing elixir)
    PREPARE = "prepare"  # a battle was declared: drink elixirs, then roll
    CLASH = "clash"  # dice on the table: rerolls, bonuses, then resolve
    AFTER_CLASH = "after_clash"  # clash resolved, both standing: fight on or retreat
    CHOOSE_UPGRADE = "choose_upgrade"  # a free upgrade: pick the item
    OVERFLOW = "overflow"  # the backpack overflows: discard until everything fits
    STUN_LOSS = "stun_loss"  # stunned: pick the equipment token to lose
    STEER = "steer"  # a marching monster has several shortest paths
    GAME_OVER = "game_over"


# ---------------------------------------------------------------------------------------------- state
@dataclass
class Item:
    id: str
    key: str
    upgraded: bool = False

    @property
    def type(self) -> EquipmentType:
        return EQUIPMENT_TYPES[self.key]

    @property
    def kind(self) -> Kind:
        return self.type.kind

    @property
    def effects(self) -> tuple[Effect, ...]:
        return self.type.upgraded if self.upgraded else self.type.basic

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "key": self.key, "kind": self.kind.value, "upgraded": self.upgraded}


@dataclass
class Tile:
    hex: Hex
    key: str
    face_up: bool = False
    seals: list[bool] = field(default_factory=list)
    crater: bool = False
    trap: int | None = None

    @property
    def type(self) -> TileType:
        return TILE_TYPES[self.key]

    def to_json(self) -> dict[str, Any]:
        return {
            "hex": list(self.hex),
            "key": self.key if self.face_up else None,
            "face_up": self.face_up,
            "seals": list(self.seals) if self.face_up else [],
            "crater": self.crater,
            "trap": self.trap,
        }


@dataclass
class Monster:
    id: str
    key: str
    at: Hex
    lair: int | None = None  # which lair of its tile it sits on (None once it marched away)
    damage: int = 0
    toughness: int = 0

    @property
    def type(self) -> MonsterType:
        return MONSTER_TYPES[self.key]

    @property
    def left(self) -> int:
        return self.toughness - self.damage

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "hex": list(self.at),
            "lair": self.lair,
            "damage": self.damage,
            "toughness": self.toughness,
        }


@dataclass
class Hero:
    seat: int
    name: str
    color: str
    at: Hex = CASTLE_HEX
    toughness: int = MAX_TOUGHNESS
    coins: int = 0
    slots: dict[Kind, str | None] = field(default_factory=lambda: dict.fromkeys(SLOTS))
    pack: list[str] = field(default_factory=list)

    @property
    def equipped(self) -> list[str]:
        return [i for i in self.slots.values() if i is not None]

    @property
    def owned(self) -> list[str]:
        return [*self.equipped, *self.pack]

    def to_json(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "name": self.name,
            "color": self.color,
            "hex": list(self.at),
            "toughness": self.toughness,
            "coins": self.coins,
            "slots": {k.value: v for k, v in self.slots.items()},
            "pack": list(self.pack),
        }


@dataclass
class RolledDie:
    die: Die
    face: Face

    def to_json(self) -> dict[str, str]:
        return {"die": self.die.value, "face": self.face.value}


@dataclass
class BattleState:
    seat: int
    monster: str
    clash: int = 0  # clashes rolled so far
    dice: list[RolledDie] = field(default_factory=list)
    used: list[str] = field(default_factory=list)  # one-time equipment used this battle
    potions: list[Die] = field(default_factory=list)  # battle elixirs drunk
    bonus: list[Face] = field(default_factory=list)  # symbols added this clash
    rerolled: list[int] = field(default_factory=list)  # dice rerolled this clash
    last: dict[str, Any] | None = None  # the previous clash's outcome

    def to_json(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "monster": self.monster,
            "clash": self.clash,
            "dice": [d.to_json() for d in self.dice],
            "used": list(self.used),
            "potions": [p.value for p in self.potions],
            "bonus": [b.value for b in self.bonus],
            "rerolled": list(self.rerolled),
            "last": self.last,
        }


@dataclass
class March:
    queue: deque[str]
    monster: str | None = None  # waiting for a steering decision
    options: list[Hex] = field(default_factory=list)


@dataclass(frozen=True)
class Result:
    won: bool
    reason: str
    rounds: int


# ---------------------------------------------------------------------------------------------- pure rules
def blocked_kinds(mtype: MonsterType) -> set[Kind]:
    kind = ATTRIBUTE_BLOCKS.get(mtype.attribute) if mtype.attribute else None
    return {kind} if kind else set()


def applies(effect: Effect, mtype: MonsterType) -> bool:
    return effect.vs is None or mtype.color is None or effect.vs == mtype.color


def hero_pool(equipped: list[Item], potions: list[Die], mtype: MonsterType) -> list[Die]:
    """The heroic dice for one clash against `mtype`."""
    counts: Counter[Die] = Counter({Die.GREEN: BASE_GREEN})
    blocked = blocked_kinds(mtype)
    for item in equipped:
        if item.kind in blocked:
            continue
        for e in item.effects:
            if e.kind == EffectKind.DIE and e.die is not None:
                counts[e.die] += 1
    for p in potions:
        counts[p] += 1
    for c in HERO_DICE:
        counts[c] = min(DICE_SUPPLY[c], counts[c])
    if mtype.attribute == Attribute.LESS_GREEN:
        counts[Die.GREEN] -= 1
    if mtype.attribute == Attribute.LESS_COLORED:
        for c in (Die.ORANGE, Die.BLUE, Die.YELLOW):
            counts[c] -= 1
    return [c for c in HERO_DICE for _ in range(max(0, counts[c]))]


def monster_pool(mtype: MonsterType) -> list[Die]:
    return [Die.BLACK] * mtype.black + [Die.PURPLE] * mtype.purple


def one_time_effect(item: Item, mtype: MonsterType) -> Effect | None:
    """The item's usable once-per-battle effect against this monster, if any."""
    if item.kind in blocked_kinds(mtype) or item.kind == Kind.ELIXIR:
        return None
    for e in item.effects:
        if e.one_time and applies(e, mtype):
            return e
    return None


def clash_outcome(dice: list[RolledDie], bonus: list[Face], spell_swords: int) -> tuple[int, int]:
    """(wounds dealt to the monster, wounds dealt to the hero)."""
    faces = Counter(d.face for d in dice)
    spells = faces[Face.SPELL]
    swords = faces[Face.SWORD] + min(spell_swords, spells) + bonus.count(Face.SWORD)
    shields = faces[Face.SHIELD] + spells - min(spell_swords, spells) + bonus.count(Face.SHIELD)
    return max(0, swords - faces[Face.PARRY]), max(0, faces[Face.CLAW] - shields)


def best_spell_split(dice: list[RolledDie], bonus: list[Face]) -> int:
    """Spells as swords: block the claws that would hurt first, everything else attacks."""
    faces = Counter(d.face for d in dice)
    spells = faces[Face.SPELL]
    shields = faces[Face.SHIELD] + bonus.count(Face.SHIELD)
    need = max(0, faces[Face.CLAW] - shields)
    return max(0, spells - need)


def distances(tiles: dict[Hex, Any], goal: Hex = CASTLE_HEX) -> dict[Hex, int]:
    dist = {goal: 0}
    frontier = deque([goal])
    while frontier:
        h = frontier.popleft()
        for n in neighbours(h):
            if n in tiles and n not in dist:
                dist[n] = dist[h] + 1
                frontier.append(n)
    return dist


def pack_kinds(items: dict[str, Item], ids: list[str]) -> list[Kind]:
    return [items[i].kind for i in ids]


# ---------------------------------------------------------------------------------------------- view
@dataclass
class View:
    """Everything a player may know: the whole table except face-down tiles and the order of stacks and bag."""

    seat: int | None
    n: int
    phase: Phase
    current: int
    actor: int | None
    actions_left: int
    round: int
    moon: int
    beast_out: bool
    march_rounds: int
    tiles: dict[Hex, Tile]  # face-down tiles have key ""
    monsters: dict[str, Monster]
    heroes: list[Hero]
    items: dict[str, Item]  # items owned by heroes
    bag: int
    battle: BattleState | None
    march: March | None
    upgrade_for: int | None
    walls: int
    walls_left: int
    seals_left: int
    traps: dict[int, Hex | None]
    supply: int
    small_left: int
    big_left: int
    crater: Crater
    legal: list[Action]
    result: Result | None

    def hero(self, seat: int | None = None) -> Hero:
        return self.heroes[self.seat if seat is None else seat]  # type: ignore[index]

    def monsters_at(self, h: Hex) -> list[Monster]:
        return [m for m in self.monsters.values() if m.at == h]


# ---------------------------------------------------------------------------------------------- the game
class Game:
    def __init__(
        self,
        players: int,
        seed: int | None = None,
        crater: str = "easy",
        names: list[str] | None = None,
    ) -> None:
        if not 1 <= players <= 4:
            raise ValueError("1-4 players")
        if crater not in CRATERS:
            raise ValueError("unknown crater token")
        self.n = players
        self.rng = random.Random(seed)
        self.crater = CRATERS[crater]
        self.per_turn = SOLO_ACTIONS if players == 1 else ACTIONS_PER_TURN
        names = names or [f"Hero {i + 1}" for i in range(players)]
        self.heroes = [Hero(i, names[i], HERO_COLORS[i]) for i in range(players)]
        self.supply = COIN_SUPPLY
        self.walls = 0  # standing on the castle tile
        self.walls_left = WALLS
        self.seals_left = SEALS
        self.traps: dict[int, Hex | None] = dict.fromkeys(TRAPS)
        self.moon = MOON_START[players]
        self.beast_out = False
        self.march_rounds = 0  # rounds ended with the Beast on the board
        self.round = 1
        self.start_seat = 0
        self.current = 0
        self.actions_left = self.per_turn
        self.phase = Phase.TURN
        self.battle: BattleState | None = None
        self.march: March | None = None
        self.tasks: deque[tuple[str, int]] = deque()
        self.upgrade_for: int | None = None
        self.result: Result | None = None
        self.events: list[Event] = []
        self._setup_board()
        self._setup_items()
        self._setup_monsters()

    # ------------------------------------------------------------------ setup
    def _setup_board(self) -> None:
        self.tiles: dict[Hex, Tile] = {CASTLE_HEX: Tile(CASTLE_HEX, "castle", face_up=True)}
        for key, h in START_HEXES.items():
            self.tiles[h] = Tile(h, key, face_up=True, seals=[False] * len(TILE_TYPES[key].lairs))
        keys = [t.key for t in TILE_TYPES.values() if not t.start and not t.castle and t.min_players <= self.n]
        self.rng.shuffle(keys)
        spots = [*LAND_HEXES, *(h for k, h in EXTRA_HEXES.items() if k <= self.n)]
        assert len(keys) == len(spots)
        for h, key in zip(spots, keys, strict=True):
            self.tiles[h] = Tile(h, key, seals=[False] * len(TILE_TYPES[key].lairs), crater=h == CRATER_HEX)

    def _setup_items(self) -> None:
        self.items = {f"e{i + 1:02d}": Item(f"e{i + 1:02d}", key) for i, key in enumerate(EQUIPMENT_TOKENS)}
        self.bag = list(self.items)
        self.rng.shuffle(self.bag)
        for hero in self.heroes:
            self._receive(hero, self._draw_item())
            self._pay_out(hero, 1)

    def _setup_monsters(self) -> None:
        small = [f"s{i + 1:02d}" for i in range(len(SMALL_MONSTERS))]
        big = [f"b{i + 1:02d}" for i in range(len(BIG_MONSTERS))]
        self.monster_keys = {
            **{mid: m.key for mid, m in zip(small, SMALL_MONSTERS, strict=True)},
            **{mid: m.key for mid, m in zip(big, BIG_MONSTERS, strict=True)},
        }
        self.stacks: dict[Size, list[str]] = {Size.SMALL: small, Size.BIG: big}
        self.defeated: dict[Size, list[str]] = {Size.SMALL: [], Size.BIG: []}
        for stack in self.stacks.values():
            self.rng.shuffle(stack)
        self.monsters: dict[str, Monster] = {}
        for h in START_HEXES.values():
            self._fill_lairs(h)

    # ------------------------------------------------------------------ helpers
    def hero(self, seat: int) -> Hero:
        return self.heroes[seat]

    @property
    def actor(self) -> int | None:
        if self.phase == Phase.GAME_OVER:
            return None
        if self.phase in (Phase.CHOOSE_UPGRADE, Phase.OVERFLOW, Phase.STUN_LOSS):
            return self.tasks[0][1]
        if self.phase == Phase.STEER:
            return self.start_seat
        return self.current

    def monsters_at(self, h: Hex) -> list[Monster]:
        return [m for m in self.monsters.values() if m.at == h]

    def _emit(self, kind: str, **data: Any) -> None:
        self.events.append({"kind": kind, **data})

    def _draw_item(self) -> str | None:
        return self.bag.pop() if self.bag else None

    def _to_bag(self, item_id: str) -> None:
        self.items[item_id].upgraded = False
        self.bag.append(item_id)
        self.rng.shuffle(self.bag)

    def _pay_out(self, hero: Hero, n: int) -> int:
        n = min(n, self.supply)
        self.supply -= n
        hero.coins += n
        return n

    def _pay(self, hero: Hero, n: int) -> None:
        assert hero.coins >= n
        hero.coins -= n
        self.supply += n

    def _receive(self, hero: Hero, item_id: str | None) -> None:
        """A new token: onto the empty matching slot, otherwise into the backpack."""
        if item_id is None:
            return
        kind = self.items[item_id].kind
        if kind in hero.slots and hero.slots[kind] is None:
            hero.slots[kind] = item_id
        else:
            hero.pack.append(item_id)

    def _remove(self, hero: Hero, item_id: str) -> None:
        for k, v in hero.slots.items():
            if v == item_id:
                hero.slots[k] = None
                return
        hero.pack.remove(item_id)

    def fits(self, hero: Hero, pack: list[str] | None = None, coins: int | None = None) -> bool:
        ids = hero.pack if pack is None else pack
        return backpack.fits(pack_kinds(self.items, ids), hero.coins if coins is None else coins)

    def arrangement(self, hero: Hero) -> list[backpack.Placement] | None:
        return backpack.arrange(pack_kinds(self.items, hero.pack), hero.coins)

    def upgradable(self, hero: Hero) -> list[str]:
        return [i for i in hero.owned if self.items[i].type.upgradable and not self.items[i].upgraded]

    def _new_monster(self, size: Size) -> str | None:
        stack = self.stacks[size]
        if not stack and self.defeated[size]:
            stack.extend(self.defeated[size])
            self.defeated[size].clear()
            self.rng.shuffle(stack)
            self._emit("reshuffle", size=size.value)
        return stack.pop() if stack else None

    def _place_monster(self, mid: str, at: Hex, lair: int | None) -> None:
        key = self.monster_keys[mid]
        self.monsters[mid] = Monster(mid, key, at, lair, toughness=MONSTER_TYPES[key].toughness)
        self._emit("spawn", monster=self.monsters[mid].to_json())

    def _fill_lairs(self, h: Hex) -> None:
        tile = self.tiles[h]
        for i, size in enumerate(tile.type.lairs):
            if tile.seals[i]:
                continue
            mid = self._new_monster(size)
            if mid is not None:
                self._place_monster(mid, h, i)

    def _reveal(self, h: Hex) -> None:
        tile = self.tiles[h]
        if tile.face_up:
            return
        tile.face_up = True
        self._emit("reveal", tile=tile.to_json())
        self._fill_lairs(h)

    def lair_empty(self, h: Hex, lair: int) -> bool:
        return not any(m.at == h and m.lair == lair for m in self.monsters.values())

    @property
    def walls_allowed(self) -> bool:
        return not self.beast_out or self.march_rounds == 0

    @property
    def seals_allowed(self) -> bool:
        return not self.beast_out and self.moon <= LAST_SEAL_SPACE

    @property
    def traps_allowed(self) -> bool:
        return not self.beast_out and self.moon <= LAST_TRAP_SPACE

    def shortcut_targets(self, h: Hex) -> list[Hex]:
        tile = self.tiles[h]
        if not tile.type.shortcut:
            return []
        return [t.hex for t in self.tiles.values() if t.face_up and t.type.shortcut and t.hex != h]

    # ------------------------------------------------------------------ legal actions
    def legal_actions(self, seat: int | None) -> list[Action]:
        if seat is None or seat != self.actor:
            return []
        hero = self.heroes[seat]
        match self.phase:
            case Phase.TURN:
                return self._turn_actions(hero)
            case Phase.PREPARE:
                return self._prepare_actions(hero)
            case Phase.CLASH:
                return self._clash_actions(hero)
            case Phase.AFTER_CLASH:
                return [A.Fight(), A.Retreat()]
            case Phase.CHOOSE_UPGRADE:
                return [A.ChooseUpgrade(i) for i in self.upgradable(hero)]
            case Phase.OVERFLOW:
                return self._overflow_actions(hero)
            case Phase.STUN_LOSS:
                return [A.Lose(i) for i in hero.owned]
            case Phase.STEER:
                assert self.march is not None
                return [A.Steer(h) for h in self.march.options]
        return []

    def _turn_actions(self, hero: Hero) -> list[Action]:
        out: list[Action] = []
        if self.actions_left > 0:
            out += self._main_actions(hero)
        out += self._free_actions(hero)
        out.append(A.EndTurn())
        return out

    def _main_actions(self, hero: Hero) -> list[Action]:
        out: list[Action] = []
        here = hero.at
        for n in neighbours(here):
            if n in self.tiles:
                out.append(A.Move(n))
        for h in self.shortcut_targets(here):
            if h not in neighbours(here):
                out.append(A.Move(h))
        out += [A.Battle(m.id) for m in self.monsters_at(here)]
        if hero.toughness < MAX_TOUGHNESS:
            out.append(A.Rest())
        tile = self.tiles[here]
        match tile.type.action:
            case TileAction.MARKET:
                out += self._market_actions(hero)
            case TileAction.SEAL if self.seals_allowed and self.seals_left and hero.coins >= PRICE:
                for t in self.tiles.values():
                    if t.face_up:
                        for i, sealed in enumerate(t.seals):
                            if not sealed and self.lair_empty(t.hex, i):
                                out.append(A.Seal(t.hex, i))
            case TileAction.WALL if self.walls_allowed and self.walls_left and hero.coins >= PRICE:
                out.append(A.Wall())
            case TileAction.TRAP if self.traps_allowed:
                taken = {h for h in self.traps.values() if h is not None}
                for level, at in self.traps.items():
                    if at is None and hero.coins >= level:
                        out += [
                            A.Trap(level, t.hex)
                            for t in self.tiles.values()
                            if t.face_up and t.hex not in taken and not t.type.castle
                        ]
            case TileAction.WORK if not self.monsters_at(here) and self.supply:
                out.append(A.Work())
            case TileAction.UPGRADE if hero.coins >= PRICE:
                out += [A.Upgrade(i) for i in self.upgradable(hero)]
            case TileAction.WISH if hero.coins >= WISH_COST:
                out.append(A.Wish())
        return out

    def _market_actions(self, hero: Hero) -> list[Action]:
        out: list[Action] = []
        owned = sorted(hero.owned)
        for k in range(3):
            for sell in combinations(owned, k):
                coins = hero.coins + min(self.supply, SELL_PRICE * k)
                for buy in range(3 - k):
                    if k + buy == 0:
                        continue
                    if coins >= PRICE * buy and len(self.bag) + k >= buy:
                        out.append(A.Market(tuple(sell), buy))
        return out

    def _free_actions(self, hero: Hero) -> list[Action]:
        out: list[Action] = []
        for i in hero.pack:
            item = self.items[i]
            if item.type.heals and hero.toughness < MAX_TOUGHNESS:
                out.append(A.Drink(i))
            if item.kind in SLOTS and self._swap_fits(hero, i):
                out.append(A.Equip(i))
        for i in hero.equipped:
            if self.fits(hero, [*hero.pack, i]):
                out.append(A.Unequip(i))
        out += [A.Discard(item=i) for i in hero.owned]
        if hero.coins:
            out.append(A.Discard(coins=1))
        if not self.monsters_at(hero.at):
            for other in self.heroes:
                if other is hero or other.at != hero.at:
                    continue
                out += self._transfers(hero, other, give=True)
                out += self._transfers(other, hero, give=False)
        return out

    def _transfers(self, giver: Hero, taker: Hero, give: bool) -> list[Action]:
        out: list[Action] = []
        for i in giver.owned:
            if self._accepts(taker, i):
                out.append(A.Give(taker.seat, item=i) if give else A.Take(giver.seat, item=i))
        room = backpack.free_cells(pack_kinds(self.items, taker.pack)) - taker.coins
        for c in range(1, min(giver.coins, room) + 1):
            out.append(A.Give(taker.seat, coins=c) if give else A.Take(giver.seat, coins=c))
        return out

    def _accepts(self, hero: Hero, item_id: str) -> bool:
        kind = self.items[item_id].kind
        if kind in hero.slots and hero.slots[kind] is None:
            return True
        return self.fits(hero, [*hero.pack, item_id])

    def _swap_fits(self, hero: Hero, item_id: str) -> bool:
        kind = self.items[item_id].kind
        pack = [i for i in hero.pack if i != item_id]
        current = hero.slots[kind]
        if current is not None:
            pack.append(current)
        return self.fits(hero, pack)

    def _overflow_actions(self, hero: Hero) -> list[Action]:
        out: list[Action] = [A.Discard(item=i) for i in hero.owned]
        if hero.coins:
            out.append(A.Discard(coins=1))
        for i in hero.pack:
            if self.items[i].kind in SLOTS:
                out.append(A.Equip(i))
        out += [A.Unequip(i) for i in hero.equipped]
        if self.fits(hero):
            out.append(A.Done())
        return out

    def _prepare_actions(self, hero: Hero) -> list[Action]:
        battle = self.battle
        assert battle is not None
        mtype = self.monsters[battle.monster].type
        out: list[Action] = [A.Fight(), A.Retreat()]
        if mtype.attribute != Attribute.NO_ELIXIR:
            current = hero_pool(self._equipped_items(hero), battle.potions, mtype)
            for i in hero.pack:
                potion = self.items[i].type.potion
                if potion is not None and current.count(potion) < DICE_SUPPLY[potion]:
                    out.append(A.Drink(i))
        return out

    def _equipped_items(self, hero: Hero) -> list[Item]:
        return [self.items[i] for i in hero.equipped]

    def _clash_actions(self, hero: Hero) -> list[Action]:
        battle = self.battle
        assert battle is not None
        mtype = self.monsters[battle.monster].type
        out: list[Action] = []
        for i in hero.equipped:
            if i in battle.used:
                continue
            effect = one_time_effect(self.items[i], mtype)
            if effect is None:
                continue
            if effect.kind == EffectKind.BONUS:
                out.append(A.Bonus(i))
            elif effect.kind == EffectKind.REROLL:
                idx = [n for n, d in enumerate(battle.dice) if d.die in effect.colors]
                for k in range(1, effect.count + 1):
                    out += [A.Reroll(i, combo) for combo in combinations(idx, k)]
        spells = sum(1 for d in battle.dice if d.face == Face.SPELL)
        out += [A.Resolve(k) for k in range(spells + 1)]
        return out

    # ------------------------------------------------------------------ step
    def step(self, seat: int, action: Action) -> list[Event]:
        if self.phase == Phase.GAME_OVER:
            raise IllegalMove("The game is over")
        if seat != self.actor:
            raise IllegalMove("It's not your move")
        if action not in self.legal_actions(seat):
            raise IllegalMove(f"Not possible now: {A.NAMES[type(action)]}")
        self.events = []
        hero = self.heroes[seat]
        match action:
            case A.Move(to):
                self._do_move(hero, to)
            case A.Battle(mid):
                self._spend()
                self.battle = BattleState(seat, mid)
                self.phase = Phase.PREPARE
                self._emit("battle", seat=seat, monster=mid, key=self.monsters[mid].key)
            case A.Drink(item):
                self._do_drink(hero, item)
            case A.Fight():
                self._do_fight(hero)
            case A.Reroll(item, dice):
                self._do_reroll(item, dice)
            case A.Bonus(item):
                self._do_bonus(item)
            case A.Resolve(k):
                self._do_resolve(hero, k)
            case A.Retreat():
                self._do_retreat(hero)
            case A.Rest():
                self._spend()
                healed = min(REST_HEAL, MAX_TOUGHNESS - hero.toughness)
                hero.toughness += healed
                self._emit("rest", seat=seat, healed=healed)
            case A.Market(sell, buy):
                self._do_market(hero, sell, buy)
            case A.Seal(at, lair):
                self._spend()
                self._pay(hero, PRICE)
                self.tiles[at].seals[lair] = True
                self.seals_left -= 1
                self._emit("seal", seat=seat, hex=list(at), lair=lair)
            case A.Wall():
                self._spend()
                self._pay(hero, PRICE)
                self.walls += 1
                self.walls_left -= 1
                self._emit("wall", seat=seat, walls=self.walls)
            case A.Trap(level, at):
                self._spend()
                self._pay(hero, level)
                self.traps[level] = at
                self.tiles[at].trap = level
                self._emit("trap", seat=seat, level=level, hex=list(at))
            case A.Work():
                self._spend()
                got = self._pay_out(hero, WORK_COINS)
                self._emit("work", seat=seat, coins=got)
                self.tasks.append(("fit", seat))
            case A.Upgrade(item):
                self._spend()
                self._pay(hero, PRICE)
                self._flip(hero, item)
            case A.Wish():
                self._do_wish(hero)
            case A.ChooseUpgrade(item):
                self.tasks.popleft()
                self._flip(hero, item)
            case A.Equip(item):
                kind = self.items[item].kind
                old = hero.slots[kind]
                hero.pack.remove(item)
                if old is not None:
                    hero.pack.append(old)
                hero.slots[kind] = item
                self._emit("equip", seat=seat, item=item, replaced=old)
            case A.Unequip(item):
                self._remove(hero, item)
                hero.pack.append(item)
                self._emit("unequip", seat=seat, item=item)
            case A.Discard(item, coins):
                if item is not None:
                    self._remove(hero, item)
                    self._to_bag(item)
                    self._emit("discard", seat=seat, item=item, key=self.items[item].key)
                else:
                    self._pay(hero, coins)
                    self._emit("discard", seat=seat, coins=coins)
            case A.Give(to, item, coins):
                self._transfer(hero, self.heroes[to], item, coins)
            case A.Take(source, item, coins):
                self._transfer(self.heroes[source], hero, item, coins)
            case A.Lose(item):
                self.tasks.popleft()
                self._remove(hero, item)
                self._to_bag(item)
                self._emit("lose", seat=seat, item=item, key=self.items[item].key)
            case A.Steer(to):
                self._steer(to)
            case A.Done():
                self.tasks.popleft()
            case A.EndTurn():
                self._end_turn()
        self._settle()
        return self.events

    def _spend(self) -> None:
        assert self.actions_left > 0
        self.actions_left -= 1

    # ------------------------------------------------------------------ actions
    def _do_move(self, hero: Hero, to: Hex) -> None:
        self._spend()
        frm = hero.at
        shortcut = to not in neighbours(frm)
        if not self.tiles[to].face_up:
            self._reveal(to)
        hero.at = to
        self._emit("move", seat=hero.seat, frm=list(frm), to=list(to), shortcut=shortcut)

    def _do_drink(self, hero: Hero, item_id: str) -> None:
        item = self.items[item_id]
        hero.pack.remove(item_id)
        self._to_bag(item_id)
        if item.type.heals:
            healed = MAX_TOUGHNESS - hero.toughness
            hero.toughness = MAX_TOUGHNESS
            self._emit("drink", seat=hero.seat, item=item_id, key=item.key, healed=healed)
        else:
            assert self.battle is not None and item.type.potion is not None
            self.battle.potions.append(item.type.potion)
            self._emit("drink", seat=hero.seat, item=item_id, key=item.key, die=item.type.potion.value)

    def roll(self, die: Die) -> Face:
        return self.rng.choice(DIE_FACES[die])

    def _do_fight(self, hero: Hero) -> None:
        battle = self.battle
        assert battle is not None
        monster = self.monsters[battle.monster]
        pool = hero_pool(self._equipped_items(hero), battle.potions, monster.type) + monster_pool(monster.type)
        battle.clash += 1
        battle.dice = [RolledDie(d, self.roll(d)) for d in pool]
        battle.bonus = []
        battle.rerolled = []
        self.phase = Phase.CLASH
        self._emit("roll", seat=hero.seat, clash=battle.clash, dice=[d.to_json() for d in battle.dice])

    def _do_reroll(self, item_id: str, dice: tuple[int, ...]) -> None:
        battle = self.battle
        assert battle is not None
        battle.used.append(item_id)
        for i in dice:
            battle.dice[i] = RolledDie(battle.dice[i].die, self.roll(battle.dice[i].die))
            battle.rerolled.append(i)
        self._emit(
            "reroll", seat=battle.seat, item=item_id, indices=list(dice), dice=[d.to_json() for d in battle.dice]
        )

    def _do_bonus(self, item_id: str) -> None:
        battle = self.battle
        assert battle is not None
        effect = one_time_effect(self.items[item_id], self.monsters[battle.monster].type)
        assert effect is not None and effect.symbol is not None
        battle.used.append(item_id)
        battle.bonus.append(effect.symbol)
        self._emit("bonus", seat=battle.seat, item=item_id, symbol=effect.symbol.value)

    def _do_resolve(self, hero: Hero, spell_swords: int) -> None:
        battle = self.battle
        assert battle is not None
        monster = self.monsters[battle.monster]
        dealt, taken = clash_outcome(battle.dice, battle.bonus, spell_swords)
        dealt = min(dealt, monster.left)
        taken = min(taken, hero.toughness)
        monster.damage += dealt
        hero.toughness -= taken
        slain = monster.left <= 0
        stunned = hero.toughness <= 0
        battle.last = {"clash": battle.clash, "dealt": dealt, "taken": taken, "spell_swords": spell_swords}
        self._emit(
            "clash",
            seat=hero.seat,
            monster=monster.id,
            clash=battle.clash,
            dealt=dealt,
            taken=taken,
            spell_swords=spell_swords,
            monster_left=monster.left,
            toughness=hero.toughness,
        )
        if slain:
            self._slay(hero, monster)
            if self.phase == Phase.GAME_OVER:
                return
        if stunned:
            self.tasks.append(("stun", hero.seat))
        if slain or stunned or battle.clash >= CLASHES:
            self._end_battle(hero, "slain" if slain else "stunned" if stunned else "over")
        else:
            self.phase = Phase.AFTER_CLASH

    def _do_retreat(self, hero: Hero) -> None:
        battle = self.battle
        assert battle is not None
        if battle.clash == 0 and not battle.potions:
            self.actions_left += 1  # changed their mind before anything happened
        self._end_battle(hero, "retreat")

    def _end_battle(self, hero: Hero, outcome: str) -> None:
        assert self.battle is not None
        self._emit("battle_end", seat=hero.seat, monster=self.battle.monster, outcome=outcome)
        self.battle = None
        self.phase = Phase.TURN

    def _slay(self, hero: Hero, monster: Monster) -> None:
        del self.monsters[monster.id]
        mtype = monster.type
        self._emit("slain", seat=hero.seat, monster=monster.id, key=monster.key)
        if mtype.size == Size.BEAST:
            self._check_victory()
            return
        self.defeated[mtype.size].append(monster.id)
        self._reward(hero, mtype.reward.coins, mtype.reward.equipment, mtype.reward.upgrades, source=monster.key)
        self._check_victory()

    def _reward(self, hero: Hero, coins: int, equipment: int, upgrades: int, source: str) -> None:
        got = self._pay_out(hero, coins) if coins else 0
        drawn = []
        for _ in range(equipment):
            item = self._draw_item()
            if item is not None:
                self._receive(hero, item)
                drawn.append({"id": item, "key": self.items[item].key})
        self._emit("reward", seat=hero.seat, source=source, coins=got, items=drawn, upgrades=upgrades)
        for _ in range(upgrades):
            self.tasks.append(("upgrade", hero.seat))
        self.tasks.append(("fit", hero.seat))

    def _flip(self, hero: Hero, item_id: str) -> None:
        self.items[item_id].upgraded = True
        self._emit("upgrade", seat=hero.seat, item=item_id, key=self.items[item_id].key)

    def _do_market(self, hero: Hero, sell: tuple[str, ...], buy: int) -> None:
        self._spend()
        for item in sell:
            self._remove(hero, item)
            self._to_bag(item)
            got = self._pay_out(hero, SELL_PRICE)
            self._emit("sell", seat=hero.seat, item=item, key=self.items[item].key, coins=got)
        for _ in range(buy):
            item = self._draw_item()
            if item is None:
                break
            self._pay(hero, PRICE)
            self._receive(hero, item)
            self._emit("buy", seat=hero.seat, item=item, key=self.items[item].key)
        self.tasks.append(("fit", hero.seat))

    def _do_wish(self, hero: Hero) -> None:
        self._spend()
        self._pay(hero, WISH_COST)
        rolls = []
        outcome = None
        for _ in range(2):
            faces = sorted((self.roll(Die.GREEN), self.roll(Die.GREEN)), key=lambda f: f.value)
            rolls.append([f.value for f in faces])
            if faces == [Face.SWORD, Face.SWORD]:
                outcome = "coins"
            elif faces == [Face.SHIELD, Face.SWORD]:
                outcome = "equipment"
            elif faces == [Face.SHIELD, Face.SHIELD]:
                outcome = "upgrade"
            if outcome:
                break
        self._emit("wish", seat=hero.seat, rolls=rolls, outcome=outcome)
        if outcome == "coins":
            self._reward(hero, WISH_COINS, 0, 0, "wishing_lake")
        elif outcome == "equipment":
            self._reward(hero, 0, 1, 0, "wishing_lake")
        elif outcome == "upgrade":
            self._reward(hero, 0, 0, 1, "wishing_lake")

    def _transfer(self, giver: Hero, taker: Hero, item: str | None, coins: int) -> None:
        if item is not None:
            self._remove(giver, item)
            self._receive(taker, item)
            self._emit("transfer", frm=giver.seat, to=taker.seat, item=item, key=self.items[item].key)
        else:
            giver.coins -= coins
            taker.coins += coins
            self._emit("transfer", frm=giver.seat, to=taker.seat, coins=coins)

    def _stun(self, hero: Hero) -> None:
        lost = hero.coins
        self.supply += hero.coins
        hero.coins = 0
        frm = hero.at
        hero.at = CASTLE_HEX
        hero.toughness = MAX_TOUGHNESS
        self._emit("stunned", seat=hero.seat, frm=list(frm), coins=lost)

    # ------------------------------------------------------------------ settling
    def _settle(self) -> None:
        """Run everything automatic until somebody has to decide."""
        while self.phase != Phase.GAME_OVER:
            if self.battle is not None:
                return
            if self.tasks:
                kind, seat = self.tasks[0]
                hero = self.heroes[seat]
                if kind == "upgrade":
                    if self.upgradable(hero):
                        self.phase = Phase.CHOOSE_UPGRADE
                        return
                    self.tasks.popleft()
                elif kind == "fit":
                    stun_pending = any(t == ("stun", seat) for t in self.tasks)
                    if not stun_pending and not self.fits(hero):
                        self.phase = Phase.OVERFLOW
                        return
                    self.tasks.popleft()
                elif kind == "stun":
                    self.tasks.popleft()
                    self._stun(hero)
                    if hero.owned:
                        self.tasks.appendleft(("lose", seat))
                    self.tasks.append(("fit", seat))
                    self.tasks.append(("end_turn", seat))
                elif kind == "lose":
                    self.phase = Phase.STUN_LOSS
                    return
                elif kind == "end_turn":
                    self.tasks.popleft()
                    self.phase = Phase.TURN
                    self._end_turn()
                continue
            if self.march is not None:
                if self.march.monster is not None:
                    self.phase = Phase.STEER
                    return
                self._march_next()
                continue
            self.phase = Phase.TURN
            return

    # ------------------------------------------------------------------ rounds
    def _end_turn(self) -> None:
        self._emit("end_turn", seat=self.current)
        self.current = (self.current + 1) % self.n
        self.actions_left = self.per_turn
        if self.current == self.start_seat:
            self._end_round()
        if self.phase != Phase.GAME_OVER and self.march is None:
            self._emit("turn", seat=self.current)

    def _end_round(self) -> None:
        if self.beast_out:
            self._start_march()
            return
        self.moon += 1
        space = MOON_TRACK[self.moon]
        self._emit("moon", space=self.moon, symbol=space.value)
        if space == Moon.SPAWN:
            for tile in self.tiles.values():
                if tile.face_up and tile.type.lairs and not self.monsters_at(tile.hex):
                    self._fill_lairs(tile.hex)
        elif space == Moon.HEAL:
            for hero in self.heroes:
                if hero.toughness < MAX_TOUGHNESS:
                    hero.toughness += 1
                    self._emit("heal", seat=hero.seat, toughness=hero.toughness)
        elif space == Moon.BLACK_MOON:
            self._black_moon()
        self._next_round()

    def _next_round(self) -> None:
        self.round += 1
        if self.round > MAX_ROUNDS:
            self._finish(False, "time")
            return
        self._emit("round", round=self.round)

    def _black_moon(self) -> None:
        self._emit("black_moon")
        for tile in self.tiles.values():
            if not tile.face_up:
                self._reveal(tile.hex)
        by_symbol: dict[Symbol, Hex] = {t.type.symbol: t.hex for t in self.tiles.values() if t.type.symbol}
        for size in self.crater.monsters[self.n]:
            mid = self._new_monster(size)
            if mid is None:
                continue
            face = self.roll(Die.BLACK)
            symbol = {Face.CLAW: self.crater.claw, Face.BLANK: self.crater.blank, Face.PARRY: self.crater.parry}[face]
            self._emit("crater_roll", face=face.value, symbol=symbol.value)
            self._place_monster(mid, by_symbol[symbol], None)
        crater = next(t for t in self.tiles.values() if t.crater)
        crater.crater = False
        self.monsters["beast"] = Monster("beast", BEAST.key, crater.hex, None, toughness=BEAST_TOUGHNESS[self.n])
        self.beast_out = True
        self._emit("beast", monster=self.monsters["beast"].to_json())

    def march_order(self) -> list[str]:
        dist = distances(self.tiles)
        rank = {Size.SMALL: 0, Size.BIG: 1, Size.BEAST: 2}
        return sorted(self.monsters, key=lambda m: (rank[self.monsters[m].type.size], dist[self.monsters[m].at], m))

    def _start_march(self) -> None:
        self._emit("march")
        self.march = March(deque(self.march_order()))

    def _march_next(self) -> None:
        march = self.march
        assert march is not None
        if not march.queue:
            self.march = None
            self.march_rounds += 1
            self._emit("march_end")
            self._next_round()
            if self.phase != Phase.GAME_OVER:
                self._emit("turn", seat=self.current)
            return
        mid = march.queue.popleft()
        monster = self.monsters.get(mid)
        if monster is None:
            return
        dist = distances(self.tiles)
        d = dist[monster.at]
        if d == 1:
            self._assault(monster)
            return
        options = sorted(n for n in neighbours(monster.at) if dist.get(n) == d - 1)
        if len(options) == 1:
            self._advance(monster, options[0])
        else:
            march.monster = mid
            march.options = options

    def _steer(self, to: Hex) -> None:
        march = self.march
        assert march is not None and march.monster is not None
        monster = self.monsters[march.monster]
        march.monster = None
        march.options = []
        self._advance(monster, to)

    def _advance(self, monster: Monster, to: Hex) -> None:
        frm = monster.at
        monster.at = to
        monster.lair = None
        self._emit("monster_move", monster=monster.id, frm=list(frm), to=list(to))
        tile = self.tiles[to]
        if monster.type.size == Size.BEAST and tile.trap is not None:
            trap = TRAPS[tile.trap]
            faces = [self.roll(d) for d in trap.dice]
            dmg = sum(1 for f in faces if f == Face.SWORD) + trap.damage
            dmg = min(dmg, monster.left)
            monster.damage += dmg
            self.traps[tile.trap] = None
            self._emit(
                "trap_sprung",
                level=tile.trap,
                hex=list(to),
                dice=[{"die": d.value, "face": f.value} for d, f in zip(trap.dice, faces, strict=True)],
                damage=dmg,
                left=monster.left,
            )
            tile.trap = None
            if monster.left <= 0:
                del self.monsters[monster.id]
                self._emit("slain", seat=None, monster=monster.id, key=monster.key)
                self._check_victory()

    def _assault(self, monster: Monster) -> None:
        if self.walls:
            broken = self.walls if monster.type.size == Size.BEAST else 1
            self.walls -= broken
            self._emit("wall_broken", monster=monster.id, key=monster.key, broken=broken, walls=self.walls)
            return
        frm = monster.at
        monster.at = CASTLE_HEX
        self._emit("monster_move", monster=monster.id, frm=list(frm), to=list(CASTLE_HEX))
        self._emit("castle_falls", monster=monster.id, key=monster.key)
        self._finish(False, "castle")

    def _check_victory(self) -> None:
        if self.beast_out and not self.monsters:
            self._finish(True, "victory")

    def _finish(self, won: bool, reason: str) -> None:
        self.result = Result(won, reason, self.round)
        self.phase = Phase.GAME_OVER
        self.battle = None
        self.march = None
        self.tasks.clear()
        self._emit("game_over", won=won, reason=reason)

    # ------------------------------------------------------------------ views
    def view(self, seat: int | None) -> View:
        tiles = {}
        for h, t in self.tiles.items():
            tv = copy.copy(t)
            tv.seals = list(t.seals) if t.face_up else []
            if not t.face_up:
                tv.key = ""
            tiles[h] = tv
        owned = {i for hero in self.heroes for i in hero.owned}
        return View(
            seat=seat,
            n=self.n,
            phase=self.phase,
            current=self.current,
            actor=self.actor,
            actions_left=self.actions_left,
            round=self.round,
            moon=self.moon,
            beast_out=self.beast_out,
            march_rounds=self.march_rounds,
            tiles=tiles,
            monsters=copy.deepcopy(self.monsters),
            heroes=copy.deepcopy(self.heroes),
            items={i: copy.copy(self.items[i]) for i in owned},
            bag=len(self.bag),
            battle=copy.deepcopy(self.battle),
            march=copy.deepcopy(self.march),
            upgrade_for=self.tasks[0][1] if self.phase == Phase.CHOOSE_UPGRADE else None,
            walls=self.walls,
            walls_left=self.walls_left,
            seals_left=self.seals_left,
            traps=dict(self.traps),
            supply=self.supply,
            small_left=len(self.stacks[Size.SMALL]) + len(self.defeated[Size.SMALL]),
            big_left=len(self.stacks[Size.BIG]) + len(self.defeated[Size.BIG]),
            crater=self.crater,
            legal=self.legal_actions(seat),
            result=self.result,
        )

    def to_json(self) -> dict[str, Any]:
        """The public table (no hidden information)."""
        heroes = []
        for hero in self.heroes:
            data = hero.to_json()
            arrangement = self.arrangement(hero)
            data["layout"] = [list(p) for p in arrangement] if arrangement is not None else None  # same order as `pack`
            data["coin_cells"] = (
                [list(c) for c in backpack.coin_cells(arrangement, hero.coins)] if arrangement is not None else None
            )
            heroes.append(data)
        owned = {i for hero in self.heroes for i in hero.owned}
        battle = None
        if self.battle is not None:
            b = self.battle
            monster = self.monsters[b.monster]
            hero = self.heroes[b.seat]
            battle = b.to_json()
            battle["pool"] = [d.value for d in hero_pool(self._equipped_items(hero), b.potions, monster.type)] + [
                d.value for d in monster_pool(monster.type)
            ]
            battle["preview"] = None
            if self.phase == Phase.CLASH:
                split = best_spell_split(b.dice, b.bonus)
                dealt, taken = clash_outcome(b.dice, b.bonus, split)
                battle["preview"] = {"dealt": dealt, "taken": taken, "spell_swords": split}
        march = None
        if self.march is not None:
            march = {
                "monster": self.march.monster,
                "options": [list(h) for h in self.march.options],
                "queue": list(self.march.queue),
            }
        return {
            "n": self.n,
            "phase": self.phase.value,
            "current": self.current,
            "actor": self.actor,
            "start_seat": self.start_seat,
            "actions_left": self.actions_left,
            "per_turn": self.per_turn,
            "round": self.round,
            "moon": self.moon,
            "moon_start": MOON_START[self.n],
            "beast_out": self.beast_out,
            "march_rounds": self.march_rounds,
            "tiles": [t.to_json() for t in self.tiles.values()],
            "monsters": [m.to_json() for m in self.monsters.values()],
            "heroes": heroes,
            "items": {i: self.items[i].to_json() for i in sorted(owned)},
            "bag": len(self.bag),
            "bag_contents": dict(Counter(self.items[i].key for i in self.bag)),
            "battle": battle,
            "march": march,
            "task": list(self.tasks[0]) if self.tasks and self.phase != Phase.TURN else None,
            "walls": self.walls,
            "walls_left": self.walls_left,
            "walls_allowed": self.walls_allowed,
            "seals_left": self.seals_left,
            "seals_allowed": self.seals_allowed,
            "traps": {str(k): (list(v) if v else None) for k, v in self.traps.items()},
            "traps_allowed": self.traps_allowed,
            "supply": self.supply,
            "small_left": len(self.stacks[Size.SMALL]),
            "big_left": len(self.stacks[Size.BIG]),
            "crater": self.crater.key,
            "beast_toughness": BEAST_TOUGHNESS[self.n],
            "result": None
            if self.result is None
            else {"won": self.result.won, "reason": self.result.reason, "rounds": self.result.rounds},
        }
