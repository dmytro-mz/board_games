"""Battle tactics shared by the bots and by their Monte-Carlo battle estimates."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cache

from avel.game import actions as A
from avel.game.actions import Action
from avel.game.engine import Item, RolledDie, clash_outcome, hero_pool, monster_pool, one_time_effect
from avel.game.model import CLASHES, DIE_FACES, Die, EffectKind, Face, MonsterType, Size


def choose_split(dice: list[RolledDie], bonus: list[Face], toughness: int, left: int) -> int:
    spells = sum(1 for d in dice if d.face == Face.SPELL)
    best, best_score = 0, -1e9
    for k in range(spells + 1):
        dealt, taken = clash_outcome(dice, bonus, k)
        kill = dealt >= left
        stun = taken >= toughness
        score = 20 * kill - 15 * stun + min(dealt, left) - 0.9 * taken
        if score > best_score:
            best, best_score = k, score
    return best


def _value(dice: list[RolledDie], bonus: list[Face], toughness: int, left: int) -> float:
    k = choose_split(dice, bonus, toughness, left)
    dealt, taken = clash_outcome(dice, bonus, k)
    return 20 * (dealt >= left) - 15 * (taken >= toughness) + min(dealt, left) - 0.9 * taken


def _die_gain(d: RolledDie, dice: list[RolledDie], bonus: list[Face], toughness: int, left: int) -> float:
    """Expected improvement from rerolling one die."""
    base = _value(dice, bonus, toughness, left)
    idx = dice.index(d)
    total = 0.0
    for face in DIE_FACES[d.die]:
        trial = list(dice)
        trial[idx] = RolledDie(d.die, face)
        total += _value(trial, bonus, toughness, left)
    return total / len(DIE_FACES[d.die]) - base


def clash_choice(
    dice: list[RolledDie],
    bonus: list[Face],
    items: list[Item],
    used: list[str],
    mtype: MonsterType,
    toughness: int,
    left: int,
) -> Action:
    """Use a one-time effect if it helps right now, otherwise resolve."""
    base = _value(dice, bonus, toughness, left)
    best: tuple[float, Action] | None = None
    for item in items:
        if item.id in used:
            continue
        effect = one_time_effect(item, mtype)
        if effect is None:
            continue
        if effect.kind == EffectKind.BONUS and effect.symbol is not None:
            gain = _value(dice, [*bonus, effect.symbol], toughness, left) - base
            if gain > 0.5 and (best is None or gain > best[0]):
                best = (gain, A.Bonus(item.id))
        elif effect.kind == EffectKind.REROLL:
            gains = sorted(
                ((_die_gain(d, dice, bonus, toughness, left), i) for i, d in enumerate(dice) if d.die in effect.colors),
                reverse=True,
            )
            picked = [i for g, i in gains[: effect.count] if g > 0.25]
            gain = sum(g for g, _ in gains[: len(picked)])
            if picked and (best is None or gain > best[0]):
                best = (gain, A.Reroll(item.id, tuple(sorted(picked))))
    if best is not None:
        return best[1]
    return A.Resolve(choose_split(dice, bonus, toughness, left))


@cache
def stun_chance(pool: tuple[Die, ...], toughness: int) -> float:
    """Chance that one clash with these dice deals at least `toughness` wounds (spells used as shields)."""
    dist: dict[int, float] = {0: 1.0}
    for die in pool:
        faces = DIE_FACES[die]
        steps = Counter(-1 if f in (Face.SHIELD, Face.SPELL) else 1 if f == Face.CLAW else 0 for f in faces)
        nxt: dict[int, float] = defaultdict(float)
        for net, p in dist.items():
            for step, n in steps.items():
                nxt[net + step] += p * n / len(faces)
        dist = nxt
    return sum(p for net, p in dist.items() if net >= toughness)


def keep_fighting(pool: list[Die], toughness: int, left: int, clash: int, desperate: bool = False) -> bool:
    if clash >= CLASHES or left <= 0 or toughness <= 0:
        return False
    return stun_chance(tuple(sorted(pool)), toughness) <= (0.3 if desperate else 0.12)


@dataclass(frozen=True)
class Estimate:
    kill: float
    stun: float
    dealt: float
    taken: float


def simulate(
    items: list[Item],
    potions: list[Die],
    toughness: int,
    mtype: MonsterType,
    left: int,
    rng: random.Random,
    runs: int = 120,
    desperate: bool = False,
) -> Estimate:
    pool = hero_pool(items, potions, mtype) + monster_pool(mtype)
    kills = stuns = 0
    dealt_total = taken_total = 0
    for _ in range(runs):
        hp, mleft, used = toughness, left, []
        clash = 0
        while True:
            clash += 1
            dice = [RolledDie(d, rng.choice(DIE_FACES[d])) for d in pool]
            bonus: list[Face] = []
            while True:
                act = clash_choice(dice, bonus, items, used, mtype, hp, mleft)
                if isinstance(act, A.Resolve):
                    dealt, taken = clash_outcome(dice, bonus, act.spell_swords)
                    break
                used.append(act.item)
                if isinstance(act, A.Bonus):
                    effect = one_time_effect(next(i for i in items if i.id == act.item), mtype)
                    assert effect is not None and effect.symbol is not None
                    bonus.append(effect.symbol)
                else:
                    assert isinstance(act, A.Reroll)
                    for i in act.dice:
                        dice[i] = RolledDie(dice[i].die, rng.choice(DIE_FACES[dice[i].die]))
            dealt = min(dealt, mleft)
            taken = min(taken, hp)
            mleft -= dealt
            hp -= taken
            dealt_total += dealt
            taken_total += taken
            if not keep_fighting(pool, hp, mleft, clash, desperate):
                break
        kills += mleft <= 0
        stuns += hp <= 0
    return Estimate(kills / runs, stuns / runs, dealt_total / runs, taken_total / runs)


def reward_value(mtype: MonsterType) -> float:
    r = mtype.reward
    if mtype.size == Size.BEAST:
        return 30.0
    return r.coins + 3.5 * r.equipment + 3.5 * r.upgrades + (2 if mtype.size == Size.BIG else 0)


def item_value(item: Item, equipped: bool) -> float:
    t = item.type
    if t.heals:
        return 3.0
    if t.potion is not None:
        return 2.5
    v = 3.0 + (2.5 if item.upgraded else 0)
    return v + (2.0 if equipped else 0)


def pool_counts(items: list[Item], potions: list[Die], mtype: MonsterType) -> Counter[Die]:
    return Counter(hero_pool(items, potions, mtype))
