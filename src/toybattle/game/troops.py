"""The 48 troop tiles: two armies of 24 (8 kinds × 3 copies), and what each kind does.

A troop id is an int: `side * 24 + kind * 3 + copy`. Kind 0 is the joker (no strength), kinds 1–7 have their
strength equal to the kind. Side 0 is Blue (bottom of the board), side 1 is Red (top).
"""

from __future__ import annotations

from dataclasses import dataclass

SIDES = 2
KINDS = 8
COPIES = 3
ARMY = KINDS * COPIES  # 24 troops per side
JOKER = 0
RACK_MAX = 8
REMOVED_AT_SETUP = 4
START_RACK = (3, 4)  # the starting player takes 3, the other 4

SIDE_NAMES = ("Blue", "Red")


@dataclass(frozen=True)
class Kind:
    kind: int
    name: str
    effect: str  # "" | "draw2" | "extra" | "knock" | "airdrop" | "snatch" | "draw1"
    title: str  # the effect's short name
    text: str  # rules text (our own words)
    motto: str


KIND_INFO: tuple[Kind, ...] = (
    Kind(
        0,
        "Jack-in-the-Box",
        "",
        "Joker",
        "No effect. Jack may cover any enemy troop, and any enemy troop may cover Jack.",
        "Surprise!",
    ),
    Kind(1, "Wind-up Mouse", "draw2", "Reinforcements", "You may draw 2 troops from your reserve.", "Tick-tick-tick…"),
    Kind(
        2,
        "Tin Drummer",
        "extra",
        "Rally",
        "You may place 1 extra troop (normal placement rules) and apply its effect.",
        "Rat-a-tat, follow me!",
    ),
    Kind(
        3,
        "Slingshot Frog",
        "knock",
        "Knock-off",
        "You may discard 1 visible enemy troop adjacent to the Frog.",
        "Ribbit. Pow!",
    ),
    Kind(
        4,
        "Paper Plane",
        "airdrop",
        "Airdrop",
        "May be placed on any base, connected to your H.Q. or not (the enemy H.Q. still needs a connection).",
        "Whoosh, over the lines!",
    ),
    Kind(
        5,
        "Magnet Bot",
        "snatch",
        "Magnet",
        "You may discard 1 random troop from your opponent's rack.",
        "Clank! That's mine now.",
    ),
    Kind(6, "Teddy Bear", "draw1", "Big Hug", "You may draw 1 troop from your reserve.", "Who needs a cuddle?"),
    Kind(7, "Tin Tank", "", "Heavy Armour", "No effect. The strongest troop.", "Rumble rumble."),
)


def side_of(troop: int) -> int:
    return troop // ARMY


def kind_of(troop: int) -> int:
    return (troop % ARMY) // COPIES


def army(side: int) -> list[int]:
    return list(range(side * ARMY, (side + 1) * ARMY))


def beats(attacker_kind: int, defender_kind: int) -> bool:
    """May an attacker of this kind cover an enemy troop of that kind? Jokers cover and are covered by anything."""
    if attacker_kind == JOKER or defender_kind == JOKER:
        return True
    return attacker_kind > defender_kind


def troop_json(troop: int) -> dict[str, int]:
    return {"id": troop, "side": side_of(troop), "kind": kind_of(troop)}
