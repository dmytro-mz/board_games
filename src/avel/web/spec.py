"""Chronicles of Avel on the platform: its tile, its table and the static data its client needs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from avel.game.engine import HERO_COLORS
from avel.game.model import (
    ATTRIBUTE_TEXT,
    BACKPACK_H,
    BACKPACK_W,
    BEAST_TOUGHNESS,
    CASTLE_HEX,
    CRATERS,
    DIE_FACES,
    EQUIPMENT_TYPES,
    FOOTPRINT,
    LAST_SEAL_SPACE,
    LAST_TRAP_SPACE,
    MAX_TOUGHNESS,
    MONSTER_TYPES,
    MOON_START,
    MOON_TRACK,
    PRICE,
    SELL_PRICE,
    TILE_TYPES,
    TRAPS,
    Effect,
    EffectKind,
)
from avel.web.room import MAX_SEATS, MIN_SEATS, Room, RoomError, bots_public
from boardgames.games import GameSpec


def _dice(colors: tuple[Any, ...]) -> str:
    names = [c.value for c in colors]
    return " or ".join(names)


def describe(effect: Effect) -> dict[str, Any]:
    vs = f" against {effect.vs.value} monsters" if effect.vs else ""
    if effect.kind == EffectKind.DIE:
        assert effect.die is not None
        text = f"Roll 1 extra {effect.die.value} die in every clash."
    elif effect.kind == EffectKind.REROLL:
        count = "1 die" if effect.count == 1 else f"up to {effect.count} dice"
        text = f"Once per battle{vs}: reroll {count} ({_dice(effect.colors)})."
    else:
        assert effect.symbol is not None
        text = f"Once per battle{vs}: add 1 {effect.symbol.value}."
    return {
        "kind": effect.kind.value,
        "die": effect.die.value if effect.die else None,
        "colors": [c.value for c in effect.colors],
        "count": effect.count,
        "symbol": effect.symbol.value if effect.symbol else None,
        "vs": effect.vs.value if effect.vs else None,
        "text": text,
    }


def catalogue() -> dict[str, Any]:
    """Static game data the client needs to draw and explain things."""
    return {
        "bots": bots_public(),
        "hero_colors": list(HERO_COLORS),
        "max_toughness": MAX_TOUGHNESS,
        "backpack": {"w": BACKPACK_W, "h": BACKPACK_H},
        "footprint": {k.value: list(v) for k, v in FOOTPRINT.items()},
        "price": PRICE,
        "sell_price": SELL_PRICE,
        "castle": list(CASTLE_HEX),
        "dice": {d.value: [f.value for f in faces] for d, faces in DIE_FACES.items()},
        "moon_track": [m.value for m in MOON_TRACK],
        "moon_start": MOON_START,
        "last_seal_space": LAST_SEAL_SPACE,
        "last_trap_space": LAST_TRAP_SPACE,
        "beast_toughness": BEAST_TOUGHNESS,
        "tiles": {
            t.key: {
                "key": t.key,
                "name": t.name,
                "lairs": [s.value for s in t.lairs],
                "action": t.action.value if t.action else None,
                "symbol": t.symbol.value if t.symbol else None,
                "shortcut": t.shortcut,
                "min_players": t.min_players,
                "start": t.start,
                "castle": t.castle,
            }
            for t in TILE_TYPES.values()
        },
        "monsters": {
            m.key: {
                "key": m.key,
                "name": m.name,
                "size": m.size.value,
                "color": m.color.value if m.color else None,
                "toughness": m.toughness,
                "black": m.black,
                "purple": m.purple,
                "reward": {"coins": m.reward.coins, "equipment": m.reward.equipment, "upgrades": m.reward.upgrades},
                "attribute": m.attribute.value if m.attribute else None,
                "attribute_text": ATTRIBUTE_TEXT[m.attribute] if m.attribute else None,
            }
            for m in MONSTER_TYPES.values()
        },
        "equipment": {
            e.key: {
                "key": e.key,
                "name": e.name,
                "kind": e.kind.value,
                "basic": [describe(x) for x in e.basic],
                "upgraded": [describe(x) for x in e.upgraded],
                "potion": e.potion.value if e.potion else None,
                "heals": e.heals,
            }
            for e in EQUIPMENT_TYPES.values()
        },
        "craters": {
            c.key: {
                "key": c.key,
                "name": c.name,
                "flames": c.flames,
                "monsters": {str(n): [s.value for s in sizes] for n, sizes in c.monsters.items()},
                "claw": c.claw.value,
                "blank": c.blank.value,
                "parry": c.parry.value,
            }
            for c in CRATERS.values()
        },
        "traps": {
            str(t.level): {"level": t.level, "dice": [d.value for d in t.dice], "damage": t.damage}
            for t in TRAPS.values()
        },
    }


class Backend:
    def __init__(self, delay_scale: float = 1.0) -> None:
        self.delay_scale = delay_scale
        self._catalogue = catalogue()

    def new_room(self, code: str) -> Room:
        return Room(code, delay_scale=self.delay_scale)

    def config(self) -> dict[str, Any]:
        return self._catalogue


GAME = GameSpec(
    key="avel",
    title="Chronicles of Avel",
    tagline="Explore, gear up and build the defences together before the Beast marches on the castle.",
    min_players=MIN_SEATS,
    max_players=MAX_SEATS,
    bots=True,
    kind="coop",
    minutes="45–75",
    static=Path(__file__).parent / "static",
    backend=Backend,
    error=RoomError,
    accent="#5e9b4f",
)
