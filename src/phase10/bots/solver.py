"""How far a hand is from a phase, and how to lay it down once it's complete.

A plan picks a target for every requirement (the number of a set, the first number of a run, the colour of a colour
group) and counts the natural cards that fit. `deficit` is how many more cards the hand needs: missing slots minus
the wilds held, but never less than the number of groups that still have no natural card at all.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import product

from phase10.game.actions import GroupSpec, LayDown
from phase10.game.model import MAX_VALUE, MIN_VALUE, Card, Color, GroupKind, Req


@dataclass(frozen=True)
class Plan:
    targets: tuple[int | Color, ...]  # per requirement: set number, run low or colour
    naturals: tuple[int, ...]  # natural cards that fit each group
    deficit: int
    wilds_used: int


def _targets(req: Req) -> Sequence[int | Color]:
    if req.kind == GroupKind.SET:
        return range(MIN_VALUE, MAX_VALUE + 1)
    if req.kind == GroupKind.RUN:
        return range(MIN_VALUE, MAX_VALUE - req.size + 2)
    return tuple(Color)


def _fits(
    reqs: Sequence[Req], targets: Sequence[int | Color], values: Counter[int], colors: Counter[Color]
) -> list[int]:
    """Natural cards counted towards each group (a value shared by a set and a run goes to the run once)."""
    used: Counter[int] = Counter()
    out = [0] * len(reqs)
    order = sorted(range(len(reqs)), key=lambda i: reqs[i].kind != GroupKind.RUN)
    for k, i in enumerate(order):
        req, t = reqs[i], targets[i]
        if req.kind == GroupKind.RUN:
            assert isinstance(t, int)
            present = [v for v in range(t, t + req.size) if values[v] - used[v] > 0]
            for v in present:
                used[v] += 1
            out[i] = len(present)
        elif req.kind == GroupKind.SET:
            assert isinstance(t, int)
            avail = max(0, values[t] - used[t])
            later = sum(1 for j in order[k + 1 :] if reqs[j].kind == GroupKind.SET and targets[j] == t)
            take = min(req.size, max(avail - later, min(avail, 1)))
            out[i] = take
            used[t] += take
        else:
            assert isinstance(t, Color)
            out[i] = colors[t]
    return out


def plans(hand: Sequence[Card], reqs: Sequence[Req]) -> Iterator[Plan]:
    values = Counter(c.value for c in hand if c.natural)
    colors = Counter(c.color for c in hand if c.natural and c.color)
    wilds = sum(1 for c in hand if c.wild)
    seen: set[tuple[int | Color, ...]] = set()
    for targets in product(*(_targets(r) for r in reqs)):
        # Two equal requirements (two sets of 3) need not be tried in both orders.
        if len(reqs) == 2 and reqs[0] == reqs[1]:
            key = tuple(sorted(targets, key=str))
            if key in seen:
                continue
            seen.add(key)
        nat = _fits(reqs, targets, values, colors)
        need = [max(0, r.size - n) for r, n in zip(reqs, nat, strict=True)]
        empty = sum(1 for n in nat if n == 0)
        missing = sum(need)
        deficit = max(missing - wilds, empty)
        yield Plan(
            tuple(targets), tuple(min(n, r.size) for n, r in zip(nat, reqs, strict=True)), deficit, min(missing, wilds)
        )


@dataclass(frozen=True)
class Evaluation:
    deficit: int
    flex: int  # how many plans reach that deficit (more = more ways to finish)
    best: Plan


def evaluate(hand: Sequence[Card], reqs: Sequence[Req]) -> Evaluation:
    best: Plan | None = None
    flex = 0
    for p in plans(hand, reqs):
        if best is None or (p.deficit, p.wilds_used) < (best.deficit, best.wilds_used):
            if best is None or p.deficit < best.deficit:
                flex = 0
            best = p
        if p.deficit == best.deficit:
            flex += 1
    assert best is not None
    return Evaluation(best.deficit, flex, best)


def lay_down(hand: Sequence[Card], reqs: Sequence[Req]) -> LayDown | None:
    """The phase laid with as many natural cards as fit and as few wilds as possible, or None if not complete."""
    ev = evaluate(hand, reqs)
    if ev.deficit > 0:
        return None
    plan = ev.best
    pool = [c for c in hand if c.natural]
    wilds = [c for c in hand if c.wild]
    groups: list[list[Card]] = [[] for _ in reqs]
    order = sorted(range(len(reqs)), key=lambda i: reqs[i].kind != GroupKind.RUN)
    same_sets = len(reqs) == 2 and all(r.kind == GroupKind.SET for r in reqs) and plan.targets[0] == plan.targets[1]
    for i in order:
        req, t = reqs[i], plan.targets[i]
        if req.kind == GroupKind.RUN:
            for v in range(int(t), int(t) + req.size):
                card = next((c for c in pool if c.value == v), None)
                if card is not None:
                    pool.remove(card)
                    groups[i].append(card)
        elif req.kind == GroupKind.SET:
            fit = [c for c in pool if c.value == t]
            if same_sets and i == order[0]:
                fit = fit[: max(1, min(req.size, len(fit) - 1))]
            for c in fit:
                pool.remove(c)
            groups[i].extend(fit)
        else:
            fit = [c for c in pool if c.color == t]
            for c in fit:
                pool.remove(c)
            groups[i].extend(fit)
    for i, req in enumerate(reqs):
        while len(groups[i]) < req.size:
            groups[i].append(wilds.pop())
    specs = tuple(
        GroupSpec(r.kind, tuple(c.id for c in g), int(plan.targets[i]) if r.kind == GroupKind.RUN else None)
        for i, (r, g) in enumerate(zip(reqs, groups, strict=True))
    )
    return LayDown(specs)
