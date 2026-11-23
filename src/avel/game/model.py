"""Static game data: dice, monsters, equipment, board tiles, the moon track and the crater tokens.

Every number here was read off the published components (rulebook, player aid and token scans), see README.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Face(StrEnum):
    SWORD = "sword"
    SHIELD = "shield"
    SPELL = "spell"  # yellow die only: counts as a sword or a shield, the hero chooses
    CLAW = "claw"  # monster attack
    PARRY = "parry"  # monster defence: ignores one hero sword
    BLANK = "blank"


class Die(StrEnum):
    GREEN = "green"
    BLUE = "blue"
    ORANGE = "orange"
    YELLOW = "yellow"
    BLACK = "black"
    PURPLE = "purple"


S, D, M, C, P, B = Face.SWORD, Face.SHIELD, Face.SPELL, Face.CLAW, Face.PARRY, Face.BLANK
DIE_FACES: dict[Die, tuple[Face, ...]] = {
    Die.GREEN: (S, S, S, D, B, B),
    Die.BLUE: (S, S, D, D, D, D),
    Die.ORANGE: (S, S, S, S, D, D),
    Die.YELLOW: (S, S, S, M, M, B),
    Die.BLACK: (C, C, C, P, B, B),
    Die.PURPLE: (C, C, P, B, B, B),
}
HERO_DICE = (Die.GREEN, Die.BLUE, Die.ORANGE, Die.YELLOW)
MONSTER_DICE = (Die.BLACK, Die.PURPLE)
DICE_SUPPLY: dict[Die, int] = {Die.GREEN: 2, Die.BLUE: 2, Die.ORANGE: 2, Die.YELLOW: 2, Die.BLACK: 2, Die.PURPLE: 3}
BASE_GREEN = 2


class Color(StrEnum):
    """Monster colour (the ring around the token)."""

    BLUE = "blue"
    BROWN = "brown"
    GREEN = "green"


class Size(StrEnum):
    SMALL = "small"
    BIG = "big"
    BEAST = "beast"


class Attribute(StrEnum):
    """Big monster attributes (rulebook p. 11)."""

    LESS_GREEN = "less_green"  # roll 1 fewer green die
    LESS_COLORED = "less_colored"  # roll 1 fewer orange, blue and yellow die
    NO_WEAPON = "no_weapon"
    NO_SHIELD = "no_shield"
    NO_HELMET = "no_helmet"
    NO_ELIXIR = "no_elixir"


ATTRIBUTE_TEXT = {
    Attribute.LESS_GREEN: "You roll 1 fewer green die.",
    Attribute.LESS_COLORED: "You roll 1 fewer orange, blue and yellow die.",
    Attribute.NO_WEAPON: "You cannot use weapon effects.",
    Attribute.NO_SHIELD: "You cannot use shield effects.",
    Attribute.NO_HELMET: "You cannot use helmet effects.",
    Attribute.NO_ELIXIR: "You cannot drink elixirs before this battle.",
}


@dataclass(frozen=True)
class Reward:
    coins: int = 0
    equipment: int = 0
    upgrades: int = 0


@dataclass(frozen=True)
class MonsterType:
    key: str
    name: str
    size: Size
    color: Color | None  # None: the Beast, which counts as every colour
    toughness: int
    black: int
    purple: int
    reward: Reward
    attribute: Attribute | None = None


def _m(
    key: str, name: str, size: Size, color: Color, tough: int, black: int, purple: int, reward: Reward, attr=None
) -> MonsterType:
    return MonsterType(key, name, size, color, tough, black, purple, reward, attr)


SM, BG = Size.SMALL, Size.BIG
BL, BR, GR = Color.BLUE, Color.BROWN, Color.GREEN


def coins(n: int) -> Reward:
    return Reward(coins=n)


EQUIP = Reward(equipment=1)
UPGRADE = Reward(upgrades=1)

SMALL_MONSTERS: tuple[MonsterType, ...] = (
    # blue
    _m("moss_troll", "Moss Troll", SM, BL, 3, 1, 2, UPGRADE),
    _m("snapjaw", "Snapjaw", SM, BL, 1, 1, 3, EQUIP),
    _m("goblin_porter", "Goblin Porter", SM, BL, 2, 2, 0, EQUIP),
    _m("stormcap", "Stormcap", SM, BL, 1, 1, 3, coins(3)),
    _m("maw_plant", "Maw Plant", SM, BL, 3, 1, 1, coins(4)),
    _m("rock_golem", "Rock Golem", SM, BL, 3, 1, 1, Reward(coins=2, equipment=1)),
    _m("goblin_spear", "Goblin Spearman", SM, BL, 2, 1, 2, coins(3)),
    _m("cave_jelly", "Cave Jelly", SM, BL, 2, 1, 2, Reward(coins=1, equipment=1)),
    # brown
    _m("skull_shaman", "Skull Shaman", SM, BR, 3, 2, 1, UPGRADE),
    _m("lizard_rogue", "Lizard Rogue", SM, BR, 3, 1, 2, Reward(coins=1, equipment=1)),
    _m("spear_heron", "Spear Heron", SM, BR, 2, 1, 1, EQUIP),
    _m("dread_crow", "Dread Crow", SM, BR, 3, 2, 0, Reward(coins=1, equipment=1)),
    _m("bog_serpent", "Bog Serpent", SM, BR, 2, 1, 1, coins(4)),
    _m("gloom_worm", "Gloom Worm", SM, BR, 2, 0, 2, coins(3)),
    _m("gold_toad", "Gold Toad", SM, BR, 1, 1, 3, EQUIP),
    _m("old_toad", "Old Toad", SM, BR, 1, 2, 1, coins(2)),
    # green
    _m("skeleton", "Skeleton", SM, GR, 1, 0, 3, coins(2)),
    _m("skeleton_brawler", "Skeleton Brawler", SM, GR, 1, 2, 2, EQUIP),
    _m("wraith_knight", "Wraith Knight", SM, GR, 2, 1, 2, EQUIP),
    _m("blood_bat", "Blood Bat", SM, GR, 2, 2, 2, UPGRADE),
    _m("shadow_wolf", "Shadow Wolf", SM, GR, 2, 2, 0, Reward(coins=1, equipment=1)),
    _m("werewolf", "Werewolf", SM, GR, 2, 1, 1, EQUIP),
    _m("ghoul_warrior", "Ghoul Warrior", SM, GR, 3, 0, 3, Reward(coins=1, equipment=1)),
    _m("scarecrow", "Scarecrow", SM, GR, 3, 1, 2, Reward(coins=2, equipment=1)),
)

BIG_MONSTERS: tuple[MonsterType, ...] = (
    _m("colossus", "Stone Colossus", BG, BL, 5, 2, 0, Reward(coins=3, upgrades=1), Attribute.NO_SHIELD),
    _m("mycelid_knight", "Mycelid Knight", BG, BL, 4, 2, 0, Reward(equipment=1, upgrades=1), Attribute.LESS_GREEN),
    _m("dragon", "Dragon", BG, BR, 4, 1, 2, coins(5), Attribute.NO_ELIXIR),
    _m("sand_wyrm", "Sand Wyrm", BG, BR, 5, 1, 1, Reward(coins=3, equipment=1), Attribute.NO_HELMET),
    _m("bone_shaman", "Bone Shaman", BG, GR, 4, 1, 2, Reward(equipment=1, upgrades=1), Attribute.NO_WEAPON),
    _m("vampire", "Vampire", BG, GR, 3, 1, 3, Reward(equipment=2), Attribute.LESS_COLORED),
)

BEAST = MonsterType("beast", "Beast", Size.BEAST, None, 14, 2, 3, Reward())
BEAST_TOUGHNESS = {1: 14, 2: 14, 3: 17, 4: 20}

MONSTER_TYPES: dict[str, MonsterType] = {m.key: m for m in (*SMALL_MONSTERS, *BIG_MONSTERS, BEAST)}


# ---------------------------------------------------------------------------------------------- equipment
class Kind(StrEnum):
    WEAPON = "weapon"
    SHIELD = "shield"
    HELMET = "helmet"
    ELIXIR = "elixir"


SLOTS = (Kind.WEAPON, Kind.SHIELD, Kind.HELMET)
ATTRIBUTE_BLOCKS = {
    Attribute.NO_WEAPON: Kind.WEAPON,
    Attribute.NO_SHIELD: Kind.SHIELD,
    Attribute.NO_HELMET: Kind.HELMET,
}


class EffectKind(StrEnum):
    DIE = "die"  # permanent: roll one more die of `die` in every clash
    REROLL = "reroll"  # once per battle: reroll up to `count` dice of the listed colours
    BONUS = "bonus"  # once per battle: add `symbol` to the roll result


@dataclass(frozen=True)
class Effect:
    kind: EffectKind
    die: Die | None = None  # DIE: the extra die
    colors: tuple[Die, ...] = ()  # REROLL: dice that may be rerolled
    count: int = 1  # REROLL: how many
    symbol: Face | None = None  # BONUS
    vs: Color | None = None  # only against monsters of this colour (the Beast has every colour)

    @property
    def one_time(self) -> bool:
        return self.kind != EffectKind.DIE


def extra(die: Die) -> Effect:
    return Effect(EffectKind.DIE, die=die)


def reroll(*colors: Die, count: int = 1, vs: Color | None = None) -> Effect:
    return Effect(EffectKind.REROLL, colors=colors, count=count, vs=vs)


def bonus(symbol: Face, vs: Color) -> Effect:
    return Effect(EffectKind.BONUS, symbol=symbol, vs=vs)


@dataclass(frozen=True)
class EquipmentType:
    key: str
    name: str
    kind: Kind
    basic: tuple[Effect, ...]
    upgraded: tuple[Effect, ...] = ()
    potion: Die | None = None  # battle elixir: one more die of this colour for the whole battle
    heals: bool = False  # healing elixir

    @property
    def upgradable(self) -> bool:
        return self.kind != Kind.ELIXIR


G, BU, O, Y, K, PU = Die.GREEN, Die.BLUE, Die.ORANGE, Die.YELLOW, Die.BLACK, Die.PURPLE
W, SH, H, E = Kind.WEAPON, Kind.SHIELD, Kind.HELMET, Kind.ELIXIR

EQUIPMENT_TYPES: dict[str, EquipmentType] = {
    e.key: e
    for e in (
        EquipmentType("battle_axe", "Battle Axe", W, (reroll(K),), (extra(O),)),
        EquipmentType("long_sword", "Long Sword", W, (bonus(S, GR),), (extra(Y),)),
        EquipmentType("broad_sword", "Broad Sword", W, (bonus(S, BR),), (extra(Y),)),
        EquipmentType("morning_star", "Morning Star", W, (reroll(PU),), (extra(O),)),
        EquipmentType("hand_axe", "Hand Axe", W, (bonus(S, BL),), (extra(Y),)),
        EquipmentType("dagger", "Dagger", W, (reroll(G),), (extra(O),)),
        EquipmentType("wolf_shield", "Wolf Shield", SH, (bonus(D, GR),), (extra(BU), reroll(G, count=2, vs=GR))),
        EquipmentType("knight_shield", "Knight's Shield", SH, (reroll(K),), (extra(O),)),
        EquipmentType("wooden_shield", "Wooden Shield", SH, (reroll(PU),), (extra(O),)),
        EquipmentType("spider_shield", "Spider Shield", SH, (bonus(D, BR),), (extra(BU), reroll(G, count=2, vs=BR))),
        EquipmentType("bear_shield", "Bear Shield", SH, (reroll(G),), (extra(O),)),
        EquipmentType("round_shield", "Round Shield", SH, (bonus(D, BL),), (extra(BU), reroll(G, count=2, vs=BL))),
        EquipmentType(
            "eagle_helm", "Eagle Helm", H, (reroll(K, PU, count=2, vs=BR),), (extra(BU), reroll(K, PU, count=2, vs=BR))
        ),
        EquipmentType(
            "horned_helm",
            "Horned Helm",
            H,
            (reroll(K, PU, count=2, vs=GR),),
            (extra(BU), reroll(K, PU, count=2, vs=GR)),
        ),
        EquipmentType("viking_helm", "Viking Helm", H, (reroll(G),), (extra(Y),)),
        EquipmentType(
            "knight_helm",
            "Knight's Helm",
            H,
            (reroll(K, PU, count=2, vs=BL),),
            (extra(BU), reroll(K, PU, count=2, vs=BL)),
        ),
        EquipmentType("iron_helm", "Iron Helm", H, (reroll(PU),), (extra(Y),)),
        EquipmentType("demon_helm", "Demon Helm", H, (reroll(K),), (extra(Y),)),
        EquipmentType("blue_elixir", "Elixir of Defence", E, (), potion=BU),
        EquipmentType("orange_elixir", "Elixir of Fury", E, (), potion=O),
        EquipmentType("yellow_elixir", "Elixir of Magic", E, (), potion=Y),
        EquipmentType("healing_elixir", "Healing Elixir", E, (), heals=True),
    )
}

# the 25 physical tokens in the bag
EQUIPMENT_TOKENS: tuple[str, ...] = (
    *(k for k, e in EQUIPMENT_TYPES.items() if e.kind != E),
    "blue_elixir",
    "blue_elixir",
    "orange_elixir",
    "orange_elixir",
    "yellow_elixir",
    "yellow_elixir",
    "healing_elixir",
)
assert len(EQUIPMENT_TOKENS) == 25

# footprint in backpack cells (one coin = one cell); the backpack is BACKPACK_W x BACKPACK_H
FOOTPRINT: dict[Kind, tuple[int, int]] = {W: (1, 3), SH: (2, 2), H: (2, 2), E: (1, 2)}
BACKPACK_W, BACKPACK_H = 3, 4


# ---------------------------------------------------------------------------------------------- board
class Action(StrEnum):
    """Tile actions."""

    MARKET = "market"
    SEAL = "seal"
    WALL = "wall"
    TRAP = "trap"
    WORK = "work"
    UPGRADE = "upgrade"
    WISH = "wish"


class Symbol(StrEnum):
    """Tile symbols on the crater tokens (where monsters appear when the Black Moon rises)."""

    UPGRADE = "upgrade"
    WALL = "wall"
    SEAL = "seal"
    TRAP = "trap"


@dataclass(frozen=True)
class TileType:
    key: str
    name: str
    lairs: tuple[Size, ...] = ()
    action: Action | None = None
    symbol: Symbol | None = None
    shortcut: bool = False
    min_players: int = 1  # the 2+, 3+ and 4 marks
    start: bool = False
    castle: bool = False


TILE_TYPES: dict[str, TileType] = {
    t.key: t
    for t in (
        TileType("castle", "Avel Castle", castle=True),
        TileType("whispering_woods", "Whispering Woods", lairs=(SM,), shortcut=True, start=True),
        TileType("marketplace", "Marketplace", action=Action.MARKET, start=True),
        TileType("glowcap_grove", "Glowcap Grove", lairs=(SM, SM), start=True),
        TileType("wishing_lake", "Wishing Lake", action=Action.WISH),
        TileType("stone_circles", "Stone Circles", action=Action.SEAL, symbol=Symbol.SEAL),
        TileType("ruined_tower", "Ruined Tower", lairs=(BG,)),
        TileType("abandoned_village", "Abandoned Village", lairs=(SM,), action=Action.WORK, shortcut=True),
        TileType("elven_camp", "Elven Camp", action=Action.TRAP, symbol=Symbol.TRAP),
        TileType("quarry", "Quarry", action=Action.WALL, symbol=Symbol.WALL),
        TileType("old_bridge", "Old Bridge", lairs=(SM,), shortcut=True),
        TileType("alchemist", "Alchemist Workshop", action=Action.UPGRADE, symbol=Symbol.UPGRADE),
        TileType("murky_swamp", "Murky Swamp", lairs=(BG,), min_players=2),
        TileType("wilderness", "Wilderness", lairs=(SM,), action=Action.WORK, min_players=3),
        TileType("barrow_hill", "Barrow Hill", lairs=(BG,), min_players=4),
    )
}

# "Basic layout" from the player aid, flat-topped hexes in doubled coordinates (col, row; col + row even).
# Rows grow away from the castle, which sits on the moon track at the bottom.
Hex = tuple[int, int]
CASTLE_HEX: Hex = (2, 0)
START_HEXES: dict[str, Hex] = {"whispering_woods": (1, 1), "marketplace": (2, 2), "glowcap_grove": (3, 1)}
LAND_HEXES: tuple[Hex, ...] = ((0, 2), (1, 3), (3, 3), (2, 4), (1, 5), (3, 5), (2, 6), (3, 7))
EXTRA_HEXES: dict[int, Hex] = {2: (4, 4), 3: (4, 6), 4: (0, 4)}  # filled from this many players up
CRATER_HEX: Hex = (3, 7)
HEX_DIRS: tuple[Hex, ...] = ((0, 2), (1, 1), (1, -1), (0, -2), (-1, -1), (-1, 1))


def neighbours(h: Hex) -> list[Hex]:
    return [(h[0] + dc, h[1] + dr) for dc, dr in HEX_DIRS]


# ---------------------------------------------------------------------------------------------- moon track
class Moon(StrEnum):
    START = "start"
    SPAWN = "spawn"  # monsters appear on empty lairs
    HEAL = "heal"  # every hero heals 1
    BLACK_MOON = "black_moon"


MOON_TRACK: tuple[Moon, ...] = (
    Moon.START,
    *(Moon.SPAWN, Moon.HEAL) * 5,
    Moon.SPAWN,
    Moon.BLACK_MOON,
)
assert len(MOON_TRACK) == 13
MOON_START = {1: 0, 2: 0, 3: 2, 4: 2}  # index of the 1-2 and 3-4 marks
LAST_SEAL_SPACE = 10  # seals are gone once the astrolabe passes space 11 (index 10)
LAST_TRAP_SPACE = 11  # traps are gone in the round the Beast is out

# ---------------------------------------------------------------------------------------------- crater tokens


@dataclass(frozen=True)
class Crater:
    key: str
    name: str
    flames: int
    monsters: dict[int, tuple[Size, ...]]  # by number of players
    claw: Symbol  # black die result -> tile symbol where the monster appears
    blank: Symbol
    parry: Symbol


CRATERS: dict[str, Crater] = {
    c.key: c
    for c in (
        Crater(
            "easy",
            "Easy",
            1,
            {1: (), 2: (), 3: (SM,), 4: (SM, SM)},
            claw=Symbol.UPGRADE,
            blank=Symbol.WALL,
            parry=Symbol.SEAL,
        ),
        Crater(
            "moderate",
            "Moderate",
            2,
            {1: (SM,), 2: (SM,), 3: (BG,), 4: (SM, BG)},
            claw=Symbol.UPGRADE,
            blank=Symbol.WALL,
            parry=Symbol.TRAP,
        ),
        Crater(
            "difficult",
            "Difficult",
            3,
            {1: (BG,), 2: (BG,), 3: (SM, BG), 4: (BG, BG)},
            claw=Symbol.TRAP,
            blank=Symbol.SEAL,
            parry=Symbol.WALL,
        ),
    )
}


@dataclass(frozen=True)
class TrapType:
    level: int  # = price
    dice: tuple[Die, ...]
    damage: int  # added to the swords rolled


TRAPS: dict[int, TrapType] = {
    3: TrapType(3, (G, G, O), 0),
    5: TrapType(5, (G, G, O), 1),
    7: TrapType(7, (G, G, O, O), 2),
}

MAX_TOUGHNESS = 5
COIN_SUPPLY = 27
WALLS = 3
SEALS = 3
PRICE = 3  # market, seal, wall, alchemist
SELL_PRICE = 2
WORK_COINS = 2
WISH_COST = 1
WISH_COINS = 4
REST_HEAL = 2
CLASHES = 3
ACTIONS_PER_TURN = 2
SOLO_ACTIONS = 4
